"""Vincle para la PC: recibe del celular los movimientos, clics y teclas, y los ejecuta.

La conexión pasa por Supabase Realtime (canal privado "room:<id>"). La PC crea la sala y
muestra un QR y un PIN de 6 dígitos; el celular la reclama y la PC pide permiso antes de
obedecerle. El protocolo está descrito en el README.
"""

import asyncio
import ctypes
import hashlib
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox

from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
import httpx
import segno
from pynput.keyboard import Controller as Keyboard, Key, KeyCode
from pynput.mouse import Button, Controller as Mouse
from realtime import RealtimeSubscribeStates
from supabase import AsyncClientOptions, acreate_client
from supabase_auth import AsyncSupportedStorage

# Debe coincidir con la etiqueta de la versión en GitHub (v0.2.0); el workflow lo verifica.
VERSION = "0.4.3"
RELEASES_API = "https://api.github.com/repos/FR4NCKP/vincle/releases/latest"
EXE_NAME = "Vincle.exe"

# Valores públicos: la seguridad la dan las políticas RLS, no el secreto de esta clave.
SUPABASE_URL = "https://rmhuktsftptgrrzmqcon.supabase.co"
SUPABASE_KEY = "sb_publishable_2adm7NJ_11XgwuWZglo01A_7C5TI56i"
# Para probar la app web en la red local: VINCLE_APP_URL=http://192.168.x.x:5173/
APP_URL = os.environ.get("VINCLE_APP_URL", "https://fr4nckp.github.io/vincle/")

HOST_NAME = socket.gethostname()[:64] or "PC"
DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "Vincle"
# Dentro del .exe de PyInstaller los archivos incluidos se descomprimen en _MEIPASS.
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))

# Un "clic" de rueda (120 unidades en Windows) equivale a unos 40 px de dedo.
SCROLL_PX_PER_NOTCH = 40
MAX_MOVE = 2000
MAX_TEXT = 2000
GAP_WAIT_S = 0.15
# Servidor STUN público y gratuito: solo le dice a cada lado su dirección vista desde internet.
STUN_URL = "stun:stun.l.google.com:19302"
MAX_SDP = 20_000
CONTINUOUS_EVENTS = ("move", "scroll", "laser_move")
SPECIAL_KEYS = {
    "esc": Key.esc,
    "tab": Key.tab,
    "left": Key.left,
    "right": Key.right,
    "enter": Key.enter,
    "backspace": Key.backspace,
    # Modo presentación: las teclas que mandan los presentadores inalámbricos.
    "pagedown": Key.page_down,
    "pageup": Key.page_up,
    "f5": Key.f5,
}

PAPER, INK, MUTED, ACCENT = "#E7EAF0", "#2F3542", "#868D9B", "#E5322D"


class FileStorage(AsyncSupportedStorage):
    """Guarda la sesión anónima en disco para que la PC sea el mismo usuario al reabrir."""

    def __init__(self) -> None:
        self.path = DATA_DIR / "session.json"

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    async def get_item(self, key: str) -> str | None:
        return self._read().get(key)

    async def set_item(self, key: str, value: str) -> None:
        data = self._read()
        data[key] = value
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data), encoding="utf-8")

    async def remove_item(self, key: str) -> None:
        data = self._read()
        if data.pop(key, None) is not None:
            self.path.write_text(json.dumps(data), encoding="utf-8")


def parse_version(tag: str) -> tuple[int, ...]:
    return tuple(int(part) for part in tag.lstrip("v").split("."))


async def find_update() -> dict | None:
    """Devuelve el Vincle.exe de la última versión publicada si es más nuevo que este."""
    async with httpx.AsyncClient(timeout=10) as http:
        res = await http.get(RELEASES_API, headers={"Accept": "application/vnd.github+json"})
        res.raise_for_status()
        release = res.json()
    if parse_version(release["tag_name"]) <= parse_version(VERSION):
        return None
    asset = next((a for a in release["assets"] if a["name"] == EXE_NAME), None)
    return asset and {"tag": release["tag_name"], **asset}


async def install_update(exe: Path, asset: dict) -> None:
    """Descarga la versión nueva junto al .exe actual, se intercambia con ella y la abre.

    Windows no deja borrar un .exe en uso, pero sí renombrarlo: el actual pasa a
    "<nombre>.old.exe" (la versión nueva lo borra al arrancar) y el nuevo toma su nombre."""
    new = exe.with_name(exe.stem + ".new.exe")
    old = exe.with_name(exe.stem + ".old.exe")
    sha = hashlib.sha256()
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as http:
        async with http.stream("GET", asset["browser_download_url"]) as res:
            res.raise_for_status()
            with new.open("wb") as f:
                async for chunk in res.aiter_bytes():
                    f.write(chunk)
                    sha.update(chunk)
    digest = asset.get("digest") or ""
    if new.stat().st_size != asset["size"] or (
        digest.startswith("sha256:") and digest != f"sha256:{sha.hexdigest()}"
    ):
        new.unlink(missing_ok=True)
        raise ValueError("la descarga llegó incompleta o alterada")

    old.unlink(missing_ok=True)
    exe.rename(old)
    try:
        new.rename(exe)
    except OSError:
        old.rename(exe)  # se deja todo como estaba
        raise
    # Sin esta variable, el .exe nuevo de PyInstaller intentaría reutilizar los archivos
    # temporales del actual, que se borran al cerrarse.
    subprocess.Popen([str(exe)], env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"})


def remove_old_exe() -> None:
    if not getattr(sys, "frozen", False):
        return
    exe = Path(sys.executable)
    old = exe.with_name(exe.stem + ".old.exe")
    if not old.exists():
        return
    try:
        old.unlink()
    except OSError:
        pass  # Si la versión anterior todavía se está cerrando, se borra la próxima vez.
    # Recién actualizado: Windows guarda los íconos por ruta de archivo y seguiría mostrando
    # el de la versión anterior; así se le pide que vuelva a leerlos.
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED


class Smoother:
    """Mueve el cursor en pasos pequeños en vez de a saltos.

    El celular manda el movimiento acumulado cada ~33 ms por Supabase, o cada ~8 ms por la
    conexión directa; aplicarlo de golpe se ve entrecortado. Aquí cada movimiento se reparte
    en pasos de 4 ms a lo largo del tiempo que suele tardar en llegar el siguiente, así el
    cursor avanza a velocidad pareja con, como mucho, un intervalo de retraso."""

    TICK_S = 0.004
    MAX_SPREAD_S = 0.04

    def __init__(self, mouse: Mouse) -> None:
        self.mouse = mouse
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.left = [0.0, 0.0]  # movimiento que falta aplicar
        self.time_left = 0.0  # en cuánto tiempo hay que terminar de aplicarlo
        self.carry = [0.0, 0.0]  # fracciones de píxel que aún no suman uno
        self.spread = 0.033  # intervalo típico entre movimientos, medido sobre la marcha
        self.last_add = 0.0
        threading.Thread(target=self.run, daemon=True).start()

    def add(self, x: float, y: float) -> None:
        now = time.perf_counter()
        with self.lock:
            gap = now - self.last_add
            self.last_add = now
            if gap < 0.1:  # una pausa del dedo no cuenta como intervalo
                self.spread = 0.7 * self.spread + 0.3 * gap
            self.left[0] += x
            self.left[1] += y
            self.time_left = min(max(self.spread, self.TICK_S), self.MAX_SPREAD_S)
        self.wake.set()

    def flush(self) -> None:
        """Aplica ya todo lo pendiente: un clic debe caer donde el usuario ve el cursor."""
        with self.lock:
            dx, dy = self._take(1.0)
        if dx or dy:
            self.mouse.move(dx, dy)

    def _take(self, share: float) -> tuple[int, int]:
        out = []
        for i in (0, 1):
            step = self.left[i] * share
            self.left[i] -= step
            self.carry[i] += step
            whole = int(self.carry[i])
            self.carry[i] -= whole
            out.append(whole)
        return out[0], out[1]

    def run(self) -> None:
        while True:
            self.wake.wait()
            with self.lock:
                if abs(self.left[0]) < 0.01 and abs(self.left[1]) < 0.01:
                    self.wake.clear()
                    continue
                share = min(1.0, self.TICK_S / self.time_left) if self.time_left > 0 else 1.0
                self.time_left = max(0.0, self.time_left - self.TICK_S)
                dx, dy = self._take(share)
            if dx or dy:
                self.mouse.move(dx, dy)
            time.sleep(self.TICK_S)  # Python 3.11+ usa temporizadores de alta resolución en Windows


class Link:
    """Conexión con Supabase y ejecución de las órdenes. Vive en un hilo con su propio loop
    de asyncio; habla con la ventana solo a través de la cola `ui`."""

    def __init__(self, ui: queue.Queue) -> None:
        self.ui = ui
        self.loop = asyncio.new_event_loop()
        self.client = None
        self.channel = None
        self.room_id: str | None = None
        self.accepted = False
        self.asking = False
        self.refresh_handle: asyncio.TimerHandle | None = None
        self.mouse = Mouse()
        self.smoother = Smoother(self.mouse)
        self.keyboard = Keyboard()
        self.dragging = False
        self.scroll_rest = [0.0, 0.0]
        # Realtime puede entregar desordenados mensajes enviados casi juntos: se ejecutan por
        # su número `n`, esperando un poco al que falte antes de darlo por perdido.
        self.next_seq = 1
        self.pending: dict[int, dict] = {}
        self.gap_handle: asyncio.TimerHandle | None = None
        self.peer: RTCPeerConnection | None = None
        self.laser_lock = threading.Lock()
        self.laser_delta = [0, 0]

    # ---------- Hilo y llamadas desde la ventana ----------

    def start(self) -> None:
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.call(self.connect())
        self.call(self.check_update())

    def call(self, coro) -> None:
        asyncio.run_coroutine_threadsafe(coro, self.loop)

    # ---------- Actualización ----------

    async def check_update(self) -> None:
        if not getattr(sys, "frozen", False):
            return  # Desde el código fuente no hay .exe que reemplazar.
        for attempt in range(3):
            try:
                asset = await find_update()
                break
            except (httpx.HTTPError, ValueError, KeyError):
                await asyncio.sleep(20)
        else:
            return  # Sin internet o GitHub no responde: se sigue con esta versión.
        if asset:
            self.ui.put(("update", asset))

    async def update(self, asset: dict) -> None:
        try:
            await install_update(Path(sys.executable), asset)
        except (httpx.HTTPError, OSError, ValueError) as exc:
            self.ui.put(("update_failed", str(exc)))
            return
        self.ui.put(("restart",))

    # ---------- Sala ----------

    async def connect(self) -> None:
        try:
            if self.client is None:
                self.client = await acreate_client(
                    SUPABASE_URL,
                    SUPABASE_KEY,
                    options=AsyncClientOptions(storage=FileStorage(), realtime={"max_retries": 1_000_000}),
                )
            session = await self.client.auth.get_session()
            if session is None:
                session = (await self.client.auth.sign_in_anonymously()).session
            # Al restaurar la sesión guardada, supabase-py no le pasa el token a Realtime y el
            # canal privado rechaza la entrada; se le pasa a mano (las renovaciones sí llegan solas).
            await self.client.realtime.set_auth(session.access_token)
            await self.new_room()
        except Exception as exc:  # noqa: BLE001 — cualquier fallo se muestra y se puede reintentar
            self.ui.put(("error", f"No se pudo conectar con el servidor.\n{exc}"))

    async def new_room(self) -> None:
        """Crea una sala nueva (y con ella un PIN nuevo), descartando la anterior."""
        await self.leave()
        res = await self.client.rpc("create_room", {"p_host_name": HOST_NAME}).execute()
        room = res.data[0]
        self.room_id = room["id"]
        self.accepted = False
        self.asking = False

        ch = self.client.channel(
            f"room:{self.room_id}",
            {"config": {"private": True, "presence": {"key": "host"}}},
        )
        ch.on_broadcast("hello", lambda _m: self.on_hello())
        ch.on_broadcast("rtc-offer", lambda m: asyncio.ensure_future(self.on_rtc_offer(m.get("payload") or {})))
        for event in ("move", "scroll", "click", "drag", "text", "key", "laser", "laser_move"):
            ch.on_broadcast(event, self.on_input)
        ch.on_presence_sync(self.on_presence)
        self.channel = ch
        await ch.subscribe(self.on_subscribe)

        expires = datetime.fromisoformat(room["expires_at"])
        self.ui.put(("pin", room["pin"], expires))
        seconds_left = (expires - datetime.now(timezone.utc)).total_seconds()
        self.refresh_handle = self.loop.call_later(
            max(5, seconds_left - 3), lambda: asyncio.ensure_future(self.refresh_if_unclaimed())
        )

    async def refresh_if_unclaimed(self) -> None:
        """El PIN vence a los 2 minutos; si nadie lo usó, se genera otro."""
        self.refresh_handle = None
        res = await self.client.table("rooms").select("guest_id").eq("id", self.room_id).execute()
        if res.data and res.data[0]["guest_id"] is None:
            await self.new_room()

    async def leave(self) -> None:
        if self.refresh_handle:
            self.refresh_handle.cancel()
            self.refresh_handle = None
        self.release_drag()
        self.reset_order()
        self.ui.put(("laser", False))
        await self.close_peer()
        if self.channel is not None:
            if self.accepted:
                await self.channel.send_broadcast("status", {"state": "closed"})
            await self.client.remove_channel(self.channel)
            self.channel = None
        self.accepted = False

    async def close(self) -> None:
        await self.leave()
        if self.room_id:
            await self.client.table("rooms").delete().eq("id", self.room_id).execute()

    def on_subscribe(self, state, err) -> None:
        if state == RealtimeSubscribeStates.SUBSCRIBED:
            asyncio.ensure_future(self.channel.track({"role": "host"}))
        elif err:
            self.ui.put(("status", "Reconectando con el servidor…"))

    def on_presence(self) -> None:
        guest_here = "guest" in self.channel.presence_state()
        if self.accepted:
            self.ui.put(("connected", guest_here))
        if not guest_here:
            self.ui.put(("laser", False))

    # ---------- Permiso ----------

    def on_hello(self) -> None:
        """El celular entró (o volvió a entrar) al canal; su numeración empieza de nuevo."""
        self.reset_order()
        asyncio.ensure_future(self.close_peer())  # el celular negociará una conexión directa nueva
        if self.accepted:
            asyncio.ensure_future(self.channel.send_broadcast("status", {"state": "accepted"}))
        elif not self.asking:
            self.asking = True
            if self.refresh_handle:
                self.refresh_handle.cancel()
                self.refresh_handle = None
            asyncio.ensure_future(self.channel.send_broadcast("status", {"state": "pending"}))
            self.ui.put(("ask",))

    async def answer(self, allow: bool) -> None:
        self.asking = False
        if allow:
            self.accepted = True
            await self.channel.send_broadcast("status", {"state": "accepted"})
            self.ui.put(("connected", True))
        else:
            await self.channel.send_broadcast("status", {"state": "rejected"})
            await self.new_room()

    # ---------- Conexión directa (WebRTC) ----------

    async def on_rtc_offer(self, payload: dict) -> None:
        """El celular propone hablar sin pasar por Supabase. La oferta llega por el canal
        privado, así que solo puede venir del celular de esta sala; igual se exige el permiso."""
        sdp = payload.get("sdp")
        if not self.accepted or not isinstance(sdp, str) or len(sdp) > MAX_SDP:
            return
        await self.close_peer()
        pc = RTCPeerConnection(RTCConfiguration([RTCIceServer(STUN_URL)]))
        self.peer = pc

        @pc.on("datachannel")
        def on_datachannel(dc) -> None:
            # Los canales que abre el celular llegan aquí ya abiertos.
            if pc is self.peer:
                self.ui.put(("direct", True))

            @dc.on("message")
            def on_message(data) -> None:
                if pc is not self.peer or not self.accepted or not isinstance(data, str):
                    return
                try:
                    message = json.loads(data)
                except ValueError:
                    return
                if isinstance(message, dict):
                    # Llega en orden ("sure") o es movimiento ("fast"): no hace falta numerar.
                    self.run(message)

        @pc.on("connectionstatechange")
        async def on_state() -> None:
            if pc is self.peer and pc.connectionState in ("failed", "closed"):
                await self.close_peer()

        await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="offer"))
        await pc.setLocalDescription(await pc.createAnswer())  # aiortc junta antes todos sus candidatos
        if pc is self.peer and self.channel is not None:
            await self.channel.send_broadcast("rtc-answer", {"sdp": pc.localDescription.sdp})

    async def close_peer(self) -> None:
        pc, self.peer = self.peer, None
        if pc is not None:
            self.ui.put(("direct", False))
            await pc.close()

    # ---------- Órdenes del celular ----------

    def on_input(self, message) -> None:
        if not self.accepted:
            return  # Nada se ejecuta sin el permiso explícito de quien está en la PC.
        n = (message.get("payload") or {}).get("n")
        if not isinstance(n, int) or n < self.next_seq or n > self.next_seq + 1000:
            return  # Repetido, ya dado por perdido o fuera de rango.
        if message.get("event") in CONTINUOUS_EVENTS:
            # Sumar desplazamientos da lo mismo en cualquier orden: se aplican al llegar y
            # solo se deja su lugar marcado, para no frenar el cursor esperando a otro mensaje.
            self.run(message)
            self.pending[n] = None
        else:
            self.pending[n] = message
        self.drain()

    def drain(self) -> None:
        while self.next_seq in self.pending:
            message = self.pending.pop(self.next_seq)
            if message is not None:
                self.run(message)
            self.next_seq += 1
        if self.pending and self.gap_handle is None:
            self.gap_handle = self.loop.call_later(GAP_WAIT_S, self.skip_gap)

    def skip_gap(self) -> None:
        """El mensaje que faltaba no llegó (Broadcast no reintenta): se sigue sin él."""
        self.gap_handle = None
        if self.pending:
            self.next_seq = min(self.pending)
            self.drain()

    def reset_order(self) -> None:
        if self.gap_handle:
            self.gap_handle.cancel()
            self.gap_handle = None
        self.pending.clear()
        self.next_seq = 1

    def run(self, message) -> None:
        event = message.get("event")
        handler = getattr(self, f"do_{event}", None)
        if handler is None:
            return
        if event not in CONTINUOUS_EVENTS:
            self.smoother.flush()  # el clic o la tecla van después de todo el movimiento previo
        try:
            handler(message.get("payload") or {})
        except (TypeError, ValueError, KeyError):
            pass  # Mensaje mal formado: se ignora.

    def do_move(self, d: dict) -> None:
        x = max(-MAX_MOVE, min(MAX_MOVE, int(d["x"])))
        y = max(-MAX_MOVE, min(MAX_MOVE, int(d["y"])))
        self.smoother.add(x, y)

    def do_scroll(self, d: dict) -> None:
        # Desplazamiento natural: el contenido sigue al dedo.
        self.scroll_rest[0] -= float(d["x"]) / SCROLL_PX_PER_NOTCH
        self.scroll_rest[1] += float(d["y"]) / SCROLL_PX_PER_NOTCH
        # Windows acepta fracciones de "clic" (unidades de 1/120); lo que no llega a 1/120 se guarda.
        sx = int(self.scroll_rest[0] * 120) / 120
        sy = int(self.scroll_rest[1] * 120) / 120
        self.scroll_rest[0] -= sx
        self.scroll_rest[1] -= sy
        if sx or sy:
            self.mouse.scroll(sx, sy)

    def do_click(self, d: dict) -> None:
        self.mouse.click(Button.right if d["button"] == "right" else Button.left)

    def do_drag(self, d: dict) -> None:
        if d["down"] and not self.dragging:
            self.dragging = True
            self.mouse.press(Button.left)
        elif not d["down"]:
            self.release_drag()

    def release_drag(self) -> None:
        if self.dragging:
            self.smoother.flush()
            self.dragging = False
            self.mouse.release(Button.left)

    def do_text(self, d: dict) -> None:
        self.keyboard.type(str(d["text"])[:MAX_TEXT])

    def do_laser(self, d: dict) -> None:
        self.ui.put(("laser", bool(d["on"])))

    def do_laser_move(self, d: dict) -> None:
        x = max(-MAX_MOVE, min(MAX_MOVE, int(d["x"])))
        y = max(-MAX_MOVE, min(MAX_MOVE, int(d["y"])))
        with self.laser_lock:
            self.laser_delta[0] += x
            self.laser_delta[1] += y

    def take_laser_delta(self) -> tuple[int, int]:
        """Lo usa la ventana (otro hilo) para mover el punto láser."""
        with self.laser_lock:
            dx, dy = self.laser_delta
            self.laser_delta = [0, 0]
        return dx, dy

    def do_key(self, d: dict) -> None:
        name = str(d["key"])
        key = SPECIAL_KEYS.get(name) or (KeyCode.from_char(name) if len(name) == 1 else None)
        if key is None:
            return
        if d.get("ctrl"):
            with self.keyboard.pressed(Key.ctrl):
                self.keyboard.tap(key)
        else:
            self.keyboard.tap(key)


def monitor_of_active_window() -> tuple[int, int, int, int]:
    """Rectángulo (izq, arriba, der, abajo) de la pantalla donde está la ventana activa: con
    proyector, la presentación suele estar en la segunda pantalla."""
    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", ctypes.c_ulong)]

    user32 = ctypes.windll.user32
    monitor = user32.MonitorFromWindow(user32.GetForegroundWindow(), 2)  # MONITOR_DEFAULTTONEAREST
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    r = info.rcMonitor
    return r.left, r.top, r.right, r.bottom


def overlay_window(root: tk.Tk, key: str) -> tk.Toplevel:
    """Ventana sin bordes, siempre encima de todo (también de una presentación a pantalla
    completa), con fondo transparente, que deja pasar los clics y no sale en la barra de tareas."""
    top = tk.Toplevel(root)
    top.withdraw()
    top.overrideredirect(True)
    top.attributes("-topmost", True)
    top.attributes("-transparentcolor", key)
    top.configure(bg=key)
    top.update_idletasks()
    user32 = ctypes.windll.user32
    hwnd = user32.GetParent(top.winfo_id())
    ex = user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
    user32.SetWindowLongW(hwnd, -20, ex | 0x80000 | 0x20 | 0x80 | 0x8000000)  # LAYERED|TRANSPARENT|TOOLWINDOW|NOACTIVATE
    return top


def mix(c1: str, c2: str, t: float) -> str:
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


class Laser:
    """Puntero láser para presentaciones: un punto rojo y, detrás, una estela que se afina y se
    desvanece en medio segundo. No mueve el mouse ni hace clic, solo se ve.

    Al soltar el dedo el punto se oculta pero recuerda dónde quedó, y al volver a tocar sigue
    desde ahí. Solo vuelve al centro la primera vez o si la ventana activa (la presentación)
    pasó a otra pantalla."""

    SIZE = 30
    KEY = "#010203"  # color que Windows vuelve transparente
    RED, LIGHT = "#E5322D", "#FFC2BF"
    TRAIL_S = 0.5
    TRAIL_WIDTH = 12

    def __init__(self, root: tk.Tk) -> None:
        # La estela va en una capa del tamaño de la pantalla, semitransparente y debajo del punto.
        self.trail_win = overlay_window(root, self.KEY)
        self.trail_win.attributes("-alpha", 0.6)
        self.trail = tk.Canvas(self.trail_win, bg=self.KEY, highlightthickness=0)
        self.trail.pack(fill="both", expand=True)
        self.dot_win = overlay_window(root, self.KEY)
        dot = tk.Canvas(self.dot_win, width=self.SIZE, height=self.SIZE, bg=self.KEY, highlightthickness=0)
        dot.pack()
        dot.create_oval(1, 1, self.SIZE - 1, self.SIZE - 1, fill="#FF8C87", outline="")  # halo
        dot.create_oval(7, 7, self.SIZE - 7, self.SIZE - 7, fill=self.RED, outline="")  # centro
        self.visible = False
        self.trail_shown = False
        self.points: list[tuple[float, float, float]] = []  # (momento, x, y) de los últimos 0,5 s
        self.x = self.y = 0.0
        self.bounds: tuple[int, int, int, int] | None = None

    def show(self) -> None:
        if self.visible:
            return
        bounds = monitor_of_active_window()
        if bounds != self.bounds:
            left, top, right, bottom = self.bounds = bounds
            self.x, self.y = (left + right) / 2, (top + bottom) / 2
            self.trail_win.geometry(f"{right - left}x{bottom - top}+{left}+{top}")
            self.points.clear()
        self.place_dot()
        self.dot_win.deiconify()
        self.dot_win.lift()
        self.visible = True

    def hide(self) -> None:
        # La estela que quedó se termina de desvanecer sola (ver tick).
        self.dot_win.withdraw()
        self.visible = False

    def move(self, dx: float, dy: float) -> None:
        left, top, right, bottom = self.bounds
        self.x = min(max(self.x + dx, left), right - 1)
        self.y = min(max(self.y + dy, top), bottom - 1)
        self.place_dot()
        if not self.points:
            self.points.append((time.perf_counter(), self.x, self.y))  # punto de partida del trazo
        self.points.append((time.perf_counter(), self.x, self.y))
        if not self.trail_shown:
            self.trail_win.deiconify()
            self.dot_win.lift()
            self.trail_shown = True

    def place_dot(self) -> None:
        half = self.SIZE // 2
        self.dot_win.geometry(f"+{int(self.x) - half}+{int(self.y) - half}")

    def tick(self) -> bool:
        """Redibuja la estela. Devuelve False cuando ya no queda nada que animar."""
        now = time.perf_counter()
        self.points = [p for p in self.points if now - p[0] < self.TRAIL_S]
        self.trail.delete("all")
        left, top = self.bounds[0], self.bounds[1]
        for (_, x0, y0), (t1, x1, y1) in zip(self.points, self.points[1:]):
            fade = (now - t1) / self.TRAIL_S  # 0 = recién, 1 = a punto de desaparecer
            self.trail.create_line(
                x0 - left, y0 - top, x1 - left, y1 - top,
                width=max(1.0, self.TRAIL_WIDTH * (1 - fade)), fill=mix(self.RED, self.LIGHT, fade),
                capstyle="round",
            )
        if not self.points and self.trail_shown:
            self.trail_win.withdraw()
            self.trail_shown = False
        return self.visible or bool(self.points)


class Window:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Vincle")
        try:
            self.root.iconbitmap(default=str(BUNDLE_DIR / "icon.ico"))
        except tk.TclError:
            pass  # Sin ícono se ve el de Tk; no impide usar la app.
        self.root.configure(bg=PAPER, padx=36, pady=28)
        self.root.resizable(False, False)
        self.ui: queue.Queue = queue.Queue()
        self.link = Link(self.ui)
        self.laser = Laser(self.root)
        self.laser_ticking = False
        self.expires: datetime | None = None
        self.guest_here = False
        self.direct = False

        serif = ("Segoe UI Semibold", 34)
        self.title = tk.Label(self.root, text="Vincle", font=serif, bg=PAPER, fg=ACCENT)
        self.title.pack(anchor="w")

        # Aviso de versión nueva (oculto hasta que la haya).
        self.update_asset: dict | None = None
        self.update_bar = tk.Frame(self.root, bg=INK, padx=12, pady=8)
        self.update_text = tk.Label(self.update_bar, text="", font=("Segoe UI", 10), bg=INK, fg="white",
                                    justify="left", wraplength=190)
        self.update_text.pack(side="left")
        self.update_btn = tk.Button(
            self.update_bar, text="Actualizar", command=self.start_update, font=("Segoe UI", 10),
            bg=PAPER, fg=INK, activebackground="white", relief="flat", padx=12, pady=4, cursor="hand2",
        )
        self.update_btn.pack(side="right")

        # Vista "esperando": QR + PIN.
        self.waiting = tk.Frame(self.root, bg=PAPER)
        self.eyebrow(self.waiting, "ESCANEA CON TU CELULAR").pack(anchor="w", pady=(18, 8))
        self.qr = tk.Label(self.waiting, bg=PAPER)
        self.qr.pack()
        self.eyebrow(self.waiting, "O ESCRIBE EL CÓDIGO").pack(anchor="w", pady=(18, 4))
        self.pin = tk.Label(self.waiting, text="······", font=("Segoe UI Semibold", 40), bg=PAPER, fg=INK)
        self.pin.pack(anchor="w")
        self.countdown = tk.Label(self.waiting, text="", font=("Segoe UI", 10), bg=PAPER, fg=MUTED)
        self.countdown.pack(anchor="w")

        # Vista "conectado".
        self.linked = tk.Frame(self.root, bg=PAPER)
        self.eyebrow(self.linked, "ESTADO").pack(anchor="w", pady=(18, 4))
        self.linked_text = tk.Label(self.linked, text="", font=("Segoe UI Semibold", 22), bg=PAPER, fg=INK, justify="left")
        self.linked_text.pack(anchor="w")
        tk.Button(
            self.linked, text="Desconectar", command=self.disconnect, font=("Segoe UI", 11),
            bg=INK, fg="white", activebackground="#4B5260", activeforeground="white",
            relief="flat", padx=18, pady=10, cursor="hand2",
        ).pack(anchor="w", pady=(24, 0))

        self.status = tk.Label(self.root, text="Conectando con el servidor…", font=("Segoe UI", 10),
                               bg=PAPER, fg=MUTED, justify="left", wraplength=300)
        tk.Label(self.root, text=f"Versión {VERSION}", font=("Segoe UI", 8), bg=PAPER, fg=MUTED).pack(
            anchor="w", side="bottom", pady=(6, 0))
        self.status.pack(anchor="w", side="bottom", pady=(18, 0))
        self.retry = tk.Button(self.root, text="Reintentar", command=self.reconnect, relief="flat",
                               bg=PAPER, fg=INK, font=("Segoe UI", 10, "underline"), cursor="hand2")

        self.root.protocol("WM_DELETE_WINDOW", self.quit)

    @staticmethod
    def eyebrow(parent, text):
        return tk.Label(parent, text=text, font=("Segoe UI", 8, "bold"), bg=PAPER, fg=INK)

    def run(self) -> None:
        self.link.start()
        self.root.after(50, self.poll)
        self.root.after(1000, self.tick)
        self.root.mainloop()

    def poll(self) -> None:
        while not self.ui.empty():
            kind, *args = self.ui.get_nowait()
            getattr(self, f"on_{kind}")(*args)
        self.root.after(50, self.poll)

    def tick(self) -> None:
        if self.expires:
            left = int((self.expires - datetime.now(timezone.utc)).total_seconds())
            self.countdown.config(text=f"Vence en {left // 60}:{left % 60:02d}" if left > 0 else "Generando otro código…")
        self.root.after(1000, self.tick)

    # ---------- Mensajes del hilo de red ----------

    def on_pin(self, pin: str, expires: datetime) -> None:
        self.expires = expires
        url = f"{APP_URL}#{pin}"
        png = segno.make(url, error="m").png_data_uri(scale=6, border=2, dark=INK, light=PAPER)
        self.qr_image = tk.PhotoImage(data=png.split(",", 1)[1])
        self.qr.config(image=self.qr_image)
        self.pin.config(text=f"{pin[:3]} {pin[3:]}")
        self.linked.pack_forget()
        self.waiting.pack(anchor="w")
        self.retry.pack_forget()
        self.status.config(text="Esperando al celular…")

    def on_ask(self) -> None:
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.lift()
        allow = messagebox.askyesno(
            "Vincle",
            "Un celular quiere controlar el mouse y el teclado de esta computadora.\n\n¿Permitir la conexión?",
            parent=self.root,
        )
        self.root.attributes("-topmost", False)
        self.link.call(self.link.answer(allow))

    def on_connected(self, guest_here: bool) -> None:
        self.expires = None
        self.guest_here = guest_here
        self.waiting.pack_forget()
        self.linked.pack(anchor="w")
        self.linked_text.config(text="Celular conectado" if guest_here else "El celular se\ndesconectó")
        self.show_link_status()

    def on_direct(self, on: bool) -> None:
        self.direct = on
        if self.linked.winfo_ismapped():
            self.show_link_status()

    def show_link_status(self) -> None:
        if not self.guest_here:
            text = "Se reconectará solo al volver a abrir Vincle en el celular."
        elif self.direct:
            text = "Conexión directa con el celular: el cursor responde al instante."
        else:
            text = "Conectado por internet (Supabase). Si están en la misma red Wi-Fi, se pasará solo a conexión directa."
        self.status.config(text=text)

    def on_laser(self, on: bool) -> None:
        if not on:
            self.laser.hide()
            return
        if self.laser.visible:
            return
        self.link.take_laser_delta()  # lo acumulado antes de encender no cuenta
        self.laser.show()
        if not self.laser_ticking:
            self.laser_ticking = True
            self.laser_tick()

    def laser_tick(self) -> None:
        dx, dy = self.link.take_laser_delta()
        if (dx or dy) and self.laser.visible:
            self.laser.move(dx, dy)
        if self.laser.tick():
            self.root.after(8, self.laser_tick)
        else:
            self.laser_ticking = False

    def on_status(self, text: str) -> None:
        self.status.config(text=text)

    def on_update(self, asset: dict) -> None:
        self.update_asset = asset
        self.update_text.config(text=f"Hay una versión nueva ({asset['tag']}).")
        self.update_btn.config(state="normal", text="Actualizar")
        self.update_bar.pack(fill="x", pady=(14, 0), after=self.title)

    def start_update(self) -> None:
        self.update_btn.config(state="disabled")
        self.update_text.config(text="Descargando la versión nueva…")
        self.link.call(self.link.update(self.update_asset))

    def on_update_failed(self, detail: str) -> None:
        self.update_text.config(text="No se pudo actualizar. También puedes descargarla desde la página de Vincle.")
        self.update_btn.config(state="normal", text="Reintentar")

    def on_restart(self) -> None:
        # La versión nueva ya se abrió; esta se cierra (y cierra su sala).
        self.quit()

    def on_error(self, text: str) -> None:
        self.status.config(text=text)
        self.retry.pack(anchor="w", side="bottom")

    # ---------- Acciones ----------

    def reconnect(self) -> None:
        self.retry.pack_forget()
        self.status.config(text="Conectando con el servidor…")
        self.link.call(self.link.connect())

    def disconnect(self) -> None:
        self.link.call(self.link.new_room())

    def quit(self) -> None:
        if self.link.client is not None:
            # Se cierra la sala para que el celular no quede apuntando a una PC que ya no está.
            done = asyncio.run_coroutine_threadsafe(self.link.close(), self.link.loop)
            try:
                done.result(timeout=3)
            except Exception:  # noqa: BLE001 — al salir, un fallo de red no debe bloquear el cierre
                pass
        self.root.destroy()


def main() -> None:
    if sys.platform == "win32":
        # Coordenadas en píxeles reales y ventana nítida en pantallas con escala.
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass
    remove_old_exe()
    Window().run()


if __name__ == "__main__":
    main()
