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
import winreg
from datetime import datetime, timezone
from pathlib import Path

from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
import httpx
import pystray
import segno
from PIL import Image
from pynput.keyboard import Controller as Keyboard, Key, KeyCode
from pynput.mouse import Button, Controller as Mouse
from realtime import RealtimeSubscribeStates
from supabase import AsyncClientOptions, acreate_client
from supabase_auth import AsyncSupportedStorage

# Debe coincidir con la etiqueta de la versión en GitHub (v0.2.0); el workflow lo verifica.
VERSION = "0.6.0"
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
    # Multimedia.
    "play": Key.media_play_pause,
    "next": Key.media_next,
    "prev": Key.media_previous,
    "volup": Key.media_volume_up,
    "voldown": Key.media_volume_down,
    "mute": Key.media_volume_mute,
}
# Gestos de tres dedos, como en el trackpad de Windows.
GESTURES = {
    "right": (Key.alt, Key.tab),  # cambiar a la ventana siguiente
    "left": (Key.alt, Key.shift, Key.tab),  # y a la anterior
    "up": (Key.cmd, Key.tab),  # vista de tareas
    "down": (Key.cmd, "d"),  # mostrar el escritorio
}
MAX_NAME = 40

def windows_spanish() -> bool:
    """El idioma de la interfaz de Windows decide el de Vincle: español o, si no, inglés."""
    try:
        return ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x0A  # LANG_SPANISH
    except (AttributeError, OSError):
        return True


def windows_dark() -> bool:
    """Tema de las apps de Windows (Configuración > Personalización > Colores)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


LANG = "es" if windows_spanish() else "en"
TEXTS = {
    "es": {
        "scan": "ESCANEA CON TU CELULAR", "or_code": "O ESCRIBE EL CÓDIGO", "expires": "Vence en {m}:{s:02d}",
        "new_code": "Generando otro código…", "state": "ESTADO", "device": "Un dispositivo",
        "connected": "{name} conectado", "gone": "El dispositivo se\ndesconectó", "disconnect": "Desconectar",
        "connecting": "Conectando con el servidor…", "reconnecting": "Reconectando con el servidor…",
        "version": "Versión {v}", "retry": "Reintentar", "waiting": "Esperando al celular…",
        "error": "No se pudo conectar con el servidor.\n{e}",
        "st_away": "Se reconectará solo al volver a abrir Vincle en el celular.",
        "st_direct": "Conexión directa: el cursor responde al instante.",
        "st_cloud": "Conectado por internet (Supabase). Si están en la misma red Wi-Fi, se pasará solo a conexión directa.",
        "st_trusted": "Dispositivo de confianza: se conectó sin pedir permiso.",
        "update_new": "Hay una versión nueva ({tag}).", "update_btn": "Actualizar",
        "downloading": "Descargando la versión nueva…",
        "update_failed": "No se pudo actualizar. También puedes descargarla desde la página de Vincle.",
        "ask_title": "¿Permitir esta conexión?",
        "ask_body": "{name} quiere controlar el mouse y el teclado de esta computadora.",
        "ask_remember": "Recordar este dispositivo: la próxima vez se conectará solo",
        "reject": "Rechazar", "allow": "Permitir",
        "trusted_link": "Dispositivos de confianza ({n})", "trusted_title": "Dispositivos de confianza",
        "trusted_empty": "Todavía no hay dispositivos de confianza. Marca «Recordar este dispositivo» al permitir una conexión.",
        "forget": "Olvidar", "close": "Cerrar",
        "tray_open": "Abrir Vincle", "tray_autostart": "Iniciar con Windows", "tray_quit": "Salir",
        "tray_hint": "Vincle sigue abierto en la bandeja del sistema, junto al reloj.",
    },
    "en": {
        "scan": "SCAN WITH YOUR PHONE", "or_code": "OR TYPE THE CODE", "expires": "Expires in {m}:{s:02d}",
        "new_code": "Generating a new code…", "state": "STATUS", "device": "A device",
        "connected": "{name} connected", "gone": "The device\ndisconnected", "disconnect": "Disconnect",
        "connecting": "Connecting to the server…", "reconnecting": "Reconnecting to the server…",
        "version": "Version {v}", "retry": "Retry", "waiting": "Waiting for your phone…",
        "error": "Couldn't reach the server.\n{e}",
        "st_away": "It will reconnect when you open Vincle on your phone again.",
        "st_direct": "Direct connection: the cursor responds instantly.",
        "st_cloud": "Connected over the internet (Supabase). On the same Wi-Fi it switches to a direct connection.",
        "st_trusted": "Trusted device: connected without asking.",
        "update_new": "A new version is available ({tag}).", "update_btn": "Update",
        "downloading": "Downloading the new version…",
        "update_failed": "Update failed. You can also download it from the Vincle page.",
        "ask_title": "Allow this connection?",
        "ask_body": "{name} wants to control this computer's mouse and keyboard.",
        "ask_remember": "Remember this device: next time it will connect automatically",
        "reject": "Reject", "allow": "Allow",
        "trusted_link": "Trusted devices ({n})", "trusted_title": "Trusted devices",
        "trusted_empty": "No trusted devices yet. Tick “Remember this device” when you allow a connection.",
        "forget": "Forget", "close": "Close",
        "tray_open": "Open Vincle", "tray_autostart": "Start with Windows", "tray_quit": "Quit",
        "tray_hint": "Vincle keeps running in the system tray, next to the clock.",
    },
}


def tr(key: str, **kw) -> str:
    return TEXTS[LANG][key].format(**kw)


# Colores del tema claro y del oscuro (el oscuro sigue el de las apps de Windows).
DARK = windows_dark()
if DARK:
    PAPER, INK, MUTED = "#23272F", "#E7EAF0", "#8D95A3"
    BTN_BG, BTN_FG, BTN_ACTIVE = "#E7EAF0", "#23272F", "#C3C8D1"
    SOFT, SOFT_ACTIVE, TRACK = "#323843", "#3B4250", "#3B4250"
else:
    PAPER, INK, MUTED = "#E7EAF0", "#2F3542", "#868D9B"
    BTN_BG, BTN_FG, BTN_ACTIVE = "#2F3542", "#FFFFFF", "#4B5260"
    SOFT, SOFT_ACTIVE, TRACK = "#DCE1E8", "#CDD3DC", "#D5DAE2"
ACCENT, OK = "#E5322D", "#34A86B"
# El QR siempre oscuro sobre claro: varios lectores no reconocen el invertido.
QR_DARK, QR_LIGHT = "#2F3542", "#E7EAF0"


def clean_name(value) -> str:
    """Nombre del dispositivo que manda el celular: texto corto y sin saltos de línea."""
    text = " ".join(str(value or "").split())[:MAX_NAME]
    return text or tr("device")


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


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "Vincle")
        return True
    except OSError:
        return False


def set_autostart(on: bool) -> None:
    """Inicia Vincle con Windows (minimizado en la bandeja). Solo tiene sentido con el .exe."""
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, "Vincle", 0, winreg.REG_SZ, f'"{sys.executable}" --tray')
        else:
            try:
                winreg.DeleteValue(k, "Vincle")
            except FileNotFoundError:
                pass


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
        self.guest_name = ""

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
            self.ui.put(("error", tr("error", e=exc)))
            return
        await self.list_trusted()

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
        ch.on_broadcast("hello", lambda m: self.on_hello(m.get("payload") or {}))
        ch.on_broadcast("ping", lambda m: asyncio.ensure_future(self.on_ping(m.get("payload") or {})))
        ch.on_broadcast("rtc-offer", lambda m: asyncio.ensure_future(self.on_rtc_offer(m.get("payload") or {})))
        for event in ("move", "scroll", "click", "drag", "text", "key", "laser", "laser_move", "zoom", "gesture"):
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
            self.ui.put(("status", tr("reconnecting")))

    def on_presence(self) -> None:
        guest_here = "guest" in self.channel.presence_state()
        if self.accepted:
            self.ui.put(("connected", guest_here, self.guest_name))
        if not guest_here:
            self.ui.put(("laser", False))

    # ---------- Permiso ----------

    def on_hello(self, payload: dict) -> None:
        """El celular entró (o volvió a entrar) al canal; su numeración empieza de nuevo."""
        self.guest_name = clean_name(payload.get("name"))
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
            asyncio.ensure_future(self.ask_or_trust())

    async def ask_or_trust(self) -> None:
        """Si el dispositivo es de confianza (lo decide la base de datos, no lo que diga el
        celular), se acepta sin preguntar; si no, se pide permiso en la PC."""
        try:
            trusted = (await self.client.rpc("room_guest_trusted", {"p_room": self.room_id}).execute()).data is True
        except Exception:  # noqa: BLE001 — ante la duda, se pregunta
            trusted = False
        if trusted:
            await self.answer(True)
            self.ui.put(("status", tr("st_trusted")))
        else:
            self.ui.put(("ask", self.guest_name))

    async def answer(self, allow: bool, remember: bool = False) -> None:
        self.asking = False
        if allow:
            self.accepted = True
            await self.channel.send_broadcast("status", {"state": "accepted"})
            self.ui.put(("connected", True, self.guest_name))
            if remember:
                try:
                    await self.client.rpc("trust_guest", {"p_room": self.room_id, "p_guest_name": self.guest_name}).execute()
                except Exception:  # noqa: BLE001 — si no se pudo recordar, se pedirá permiso otra vez
                    pass
                await self.list_trusted()
        else:
            await self.channel.send_broadcast("status", {"state": "rejected"})
            await self.new_room()

    async def list_trusted(self) -> None:
        try:
            res = await self.client.table("trusted_devices").select("guest_id,guest_name").order("created_at").execute()
            self.ui.put(("trusted", res.data or []))
        except Exception:  # noqa: BLE001 — la lista es informativa
            pass

    async def forget(self, guest_id: str) -> None:
        try:
            await self.client.table("trusted_devices").delete().eq("guest_id", guest_id).execute()
        except Exception:  # noqa: BLE001
            pass
        await self.list_trusted()

    # ---------- Latencia ----------

    async def on_ping(self, payload: dict) -> None:
        """El celular mide cuánto tarda la ida y vuelta: se le devuelve su marca de tiempo."""
        t = payload.get("t")
        if self.accepted and isinstance(t, (int, float)) and self.channel is not None:
            await self.channel.send_broadcast("pong", {"t": t})

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
                if not isinstance(message, dict):
                    return
                if message.get("event") == "ping":
                    t = (message.get("payload") or {}).get("t")
                    if isinstance(t, (int, float)):
                        dc.send(json.dumps({"event": "pong", "payload": {"t": t}}))
                    return
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
        button = {"right": Button.right, "middle": Button.middle}.get(d["button"], Button.left)
        self.mouse.click(button)

    def do_zoom(self, d: dict) -> None:
        """Pellizco: Ctrl + rueda, que es el zoom en navegadores, documentos e imágenes."""
        steps = max(-10, min(10, int(d["steps"])))
        if steps:
            with self.keyboard.pressed(Key.ctrl):
                self.mouse.scroll(0, steps)

    def do_gesture(self, d: dict) -> None:
        keys = GESTURES.get(str(d["name"]))
        if not keys:
            return
        *mods, last = keys
        for k in mods:
            self.keyboard.press(k)
        try:
            self.keyboard.tap(KeyCode.from_char(last) if isinstance(last, str) else last)
        finally:
            for k in reversed(mods):
                self.keyboard.release(k)

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


def animations_enabled() -> bool:
    """Respeta "Mostrar animaciones en Windows" (Accesibilidad > Efectos visuales)."""
    on = ctypes.c_bool(True)
    try:
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(on), 0)  # SPI_GETCLIENTAREAANIMATION
    except (AttributeError, OSError):
        return True
    return bool(on.value)


ANIMATIONS = animations_enabled()


def ease_out(t: float) -> float:
    return 1 - (1 - t) ** 3


def animate(root: tk.Misc, duration_s: float, step, done=None) -> None:
    """Llama a step(t), con t suavizado de 0 a 1, unas 60 veces por segundo."""
    if not ANIMATIONS:
        step(1.0)
        if done:
            done()
        return
    start = time.perf_counter()

    def frame() -> None:
        t = min(1.0, (time.perf_counter() - start) / duration_s)
        step(ease_out(t))
        if t < 1:
            root.after(16, frame)
        elif done:
            done()

    frame()


def match_title_bar(win: tk.Misc) -> None:
    """En tema oscuro, la barra de título de Windows también se pone oscura."""
    if not DARK:
        return
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        on = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), ctypes.sizeof(on))  # DWMWA_USE_IMMERSIVE_DARK_MODE
    except (AttributeError, OSError):
        pass


def soft_button(parent, text, command, **kw) -> tk.Button:
    return tk.Button(parent, text=text, command=command, font=("Segoe UI", 10), bg=SOFT, fg=INK,
                     activebackground=SOFT_ACTIVE, activeforeground=INK, relief="flat", padx=18, pady=8,
                     cursor="hand2", **kw)


def main_button(parent, text, command, font=("Segoe UI Semibold", 10), **kw) -> tk.Button:
    return tk.Button(parent, text=text, command=command, font=font, bg=BTN_BG, fg=BTN_FG,
                     activebackground=BTN_ACTIVE, activeforeground=BTN_FG, relief="flat", cursor="hand2", **kw)


class AskDialog:
    """Pregunta si se permite la conexión. Reemplaza al cuadro estándar de Windows para seguir
    el diseño de la app. A propósito no tiene botón por defecto: un Enter que se escape
    mientras alguien escribe en otro programa no debe dar el control de la PC."""

    def __init__(self, root: tk.Tk, name: str) -> None:
        self.allow = False
        self.remember = tk.BooleanVar(value=False)
        top = self.top = tk.Toplevel(root, bg=PAPER, padx=28, pady=24)
        top.title("Vincle")
        top.resizable(False, False)
        top.attributes("-topmost", True)
        top.attributes("-alpha", 0.0)
        top.transient(root)
        match_title_bar(top)
        tk.Label(top, text=tr("ask_title"), font=("Segoe UI Semibold", 15), bg=PAPER, fg=INK).pack(anchor="w")
        tk.Label(
            top, text=tr("ask_body", name=name), font=("Segoe UI", 10), bg=PAPER, fg=MUTED,
            wraplength=320, justify="left",
        ).pack(anchor="w", pady=(6, 14))
        tk.Checkbutton(
            top, text=tr("ask_remember"), variable=self.remember, font=("Segoe UI", 9), bg=PAPER, fg=INK,
            activebackground=PAPER, activeforeground=INK, selectcolor=SOFT, wraplength=300, justify="left",
            cursor="hand2",
        ).pack(anchor="w", pady=(0, 18))
        row = tk.Frame(top, bg=PAPER)
        row.pack(fill="x")
        soft_button(row, tr("reject"), self.close).pack(side="left")
        main_button(row, tr("allow"), self.accept, padx=22, pady=8).pack(side="right")
        top.bind("<Escape>", lambda _e: self.close())
        top.protocol("WM_DELETE_WINDOW", self.close)

        # Aparece centrado sobre la ventana de Vincle, con un fundido y subiendo un poco.
        top.update_idletasks()
        w, h = top.winfo_reqwidth(), top.winfo_reqheight()
        x = root.winfo_rootx() + (root.winfo_width() - w) // 2
        y = root.winfo_rooty() + (root.winfo_height() - h) // 3
        top.geometry(f"+{x}+{y + 16}")
        animate(top, 0.3, lambda t: (top.attributes("-alpha", t), top.geometry(f"+{x}+{y + int(16 * (1 - t))}")))
        top.grab_set()
        top.focus_force()

    def accept(self) -> None:
        self.allow = True
        self.close()

    def close(self) -> None:
        self.top.grab_release()
        self.top.destroy()

    def wait(self) -> tuple[bool, bool]:
        self.top.wait_window()
        return self.allow, self.allow and self.remember.get()


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
        self.dot = tk.Canvas(self.dot_win, width=self.SIZE, height=self.SIZE, bg=self.KEY, highlightthickness=0)
        self.dot.pack()
        self.halo = self.dot.create_oval(1, 1, self.SIZE - 1, self.SIZE - 1, fill="#FF8C87", outline="")
        self.core = self.dot.create_oval(7, 7, self.SIZE - 7, self.SIZE - 7, fill=self.RED, outline="")
        self.anim_id = 0  # para que una animación vieja no pise a la nueva
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
        self.scale_dot(0)
        self.dot_win.deiconify()
        self.dot_win.lift()
        self.visible = True
        self.anim_id += 1
        anim = self.anim_id
        animate(self.dot, 0.18, lambda t: anim == self.anim_id and self.scale_dot(t))

    def hide(self) -> None:
        # El punto se encoge y la estela que quedó se termina de desvanecer sola (ver tick).
        self.visible = False
        self.anim_id += 1
        anim = self.anim_id

        def shrink(t: float) -> None:
            if anim == self.anim_id:
                self.scale_dot(1 - t)

        def gone() -> None:
            if anim == self.anim_id:
                self.dot_win.withdraw()

        animate(self.dot, 0.15, shrink, gone)

    def scale_dot(self, k: float) -> None:
        c, s = self.SIZE / 2, self.SIZE / 2 - 1
        self.dot.coords(self.halo, c - s * k, c - s * k, c + s * k, c + s * k)
        r = (self.SIZE / 2 - 7) * k
        self.dot.coords(self.core, c - r, c - r, c + r, c + r)

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
        self.guest_name = ""
        self.direct = False
        self.trusted: list[dict] = []
        self.trusted_win: tk.Toplevel | None = None
        self.hint_shown = False
        self.tray = self.make_tray()

        serif = ("Segoe UI Semibold", 34)
        self.title = tk.Label(self.root, text="Vincle", font=serif, bg=PAPER, fg=ACCENT)
        self.title.pack(anchor="w")

        # Aviso de versión nueva (oculto hasta que la haya).
        self.update_asset: dict | None = None
        self.update_bar = tk.Frame(self.root, bg=BTN_BG, padx=12, pady=8)
        self.update_text = tk.Label(self.update_bar, text="", font=("Segoe UI", 10), bg=BTN_BG, fg=BTN_FG,
                                    justify="left", wraplength=190)
        self.update_text.pack(side="left")
        self.update_btn = tk.Button(
            self.update_bar, text=tr("update_btn"), command=self.start_update, font=("Segoe UI", 10),
            bg=PAPER, fg=INK, activebackground=SOFT_ACTIVE, relief="flat", padx=12, pady=4, cursor="hand2",
        )
        self.update_btn.pack(side="right")

        # Vista "esperando": QR + PIN.
        self.waiting = tk.Frame(self.root, bg=PAPER)
        self.eyebrow(self.waiting, tr("scan")).pack(anchor="w", pady=(18, 8))
        self.qr = tk.Canvas(self.waiting, width=1, height=1, bg=PAPER, highlightthickness=0)
        self.qr.pack()
        self.eyebrow(self.waiting, tr("or_code")).pack(anchor="w", pady=(18, 4))
        self.pin = tk.Label(self.waiting, text="··· ···", font=("Segoe UI Semibold", 40), bg=PAPER, fg=INK)
        self.pin.pack(anchor="w")
        # Tiempo que le queda al código: una barra que se vacía (y el texto debajo).
        self.bar = tk.Canvas(self.waiting, width=290, height=8, bg=PAPER, highlightthickness=0)
        self.bar.pack(anchor="w", pady=(6, 4))
        self.bar.create_line(4, 4, 286, 4, width=6, capstyle="round", fill=TRACK)
        self.bar_fill = self.bar.create_line(4, 4, 286, 4, width=6, capstyle="round", fill=ACCENT)
        self.pin_total = 120.0
        self.countdown = tk.Label(self.waiting, text="", font=("Segoe UI", 10), bg=PAPER, fg=MUTED)
        self.countdown.pack(anchor="w")

        # Vista "conectado".
        self.linked = tk.Frame(self.root, bg=PAPER)
        self.eyebrow(self.linked, tr("state")).pack(anchor="w", pady=(18, 8))
        row = tk.Frame(self.linked, bg=PAPER)
        row.pack(anchor="w")
        self.check = tk.Canvas(row, width=44, height=44, bg=PAPER, highlightthickness=0)
        self.check.pack(side="left", padx=(0, 12))
        self.linked_text = tk.Label(row, text="", font=("Segoe UI Semibold", 20), bg=PAPER, fg=INK, justify="left")
        self.linked_text.pack(side="left")
        main_button(self.linked, tr("disconnect"), self.disconnect, font=("Segoe UI", 11),
                    padx=18, pady=10).pack(anchor="w", pady=(24, 0))

        self.status = tk.Label(self.root, text=tr("connecting"), font=("Segoe UI", 10),
                               bg=PAPER, fg=MUTED, justify="left", wraplength=300)
        tk.Label(self.root, text=tr("version", v=VERSION), font=("Segoe UI", 8), bg=PAPER, fg=MUTED).pack(
            anchor="w", side="bottom", pady=(6, 0))
        # Enlace a la lista de dispositivos de confianza (solo si hay alguno).
        self.trusted_link = tk.Label(self.root, text="", font=("Segoe UI", 9, "underline"), bg=PAPER, fg=INK,
                                     cursor="hand2")
        self.trusted_link.bind("<Button-1>", lambda _e: self.open_trusted())
        self.status.pack(anchor="w", side="bottom", pady=(18, 0))
        self.retry = tk.Button(self.root, text=tr("retry"), command=self.reconnect, relief="flat",
                               bg=PAPER, fg=INK, activebackground=PAPER, activeforeground=INK,
                               font=("Segoe UI", 10, "underline"), cursor="hand2")

        # Cerrar la ventana la manda a la bandeja; para salir del todo, «Salir» en la bandeja.
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        match_title_bar(self.root)

    # ---------- Bandeja del sistema ----------

    def make_tray(self) -> pystray.Icon:
        try:
            image = Image.open(BUNDLE_DIR / "icon.ico")
        except OSError:
            image = Image.new("RGB", (64, 64), ACCENT)
        # El menú corre en el hilo de la bandeja: las órdenes pasan a tkinter por la cola.
        menu = pystray.Menu(
            pystray.MenuItem(tr("tray_open"), lambda: self.ui.put(("show",)), default=True),
            pystray.MenuItem(tr("tray_autostart"), lambda: set_autostart(not autostart_enabled()),
                             checked=lambda _item: autostart_enabled(), visible=getattr(sys, "frozen", False)),
            pystray.MenuItem(tr("tray_quit"), lambda: self.ui.put(("quit",))),
        )
        return pystray.Icon("Vincle", image, "Vincle", menu)

    def hide(self) -> None:
        self.root.withdraw()
        if not self.hint_shown:
            self.hint_shown = True
            try:
                self.tray.notify(tr("tray_hint"), "Vincle")
            except Exception:  # noqa: BLE001 — el aviso es opcional
                pass

    def on_show(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def on_quit(self) -> None:
        self.quit()

    @staticmethod
    def eyebrow(parent, text):
        return tk.Label(parent, text=text, font=("Segoe UI", 8, "bold"), bg=PAPER, fg=INK)

    def run(self, hidden: bool = False) -> None:
        self.link.start()
        self.tray.run_detached()
        self.root.after(50, self.poll)
        self.root.after(50, self.tick)
        if hidden:
            # Al iniciar con Windows arranca en la bandeja, sin ventana.
            self.root.withdraw()
            self.hint_shown = True
        else:
            # La ventana aparece con un fundido.
            self.root.attributes("-alpha", 0.0)
            self.root.after(10, lambda: animate(self.root, 0.35, lambda t: self.root.attributes("-alpha", t)))
        self.root.mainloop()

    def poll(self) -> None:
        while not self.ui.empty():
            kind, *args = self.ui.get_nowait()
            getattr(self, f"on_{kind}")(*args)
        self.root.after(50, self.poll)

    def tick(self) -> None:
        if self.expires:
            left_s = (self.expires - datetime.now(timezone.utc)).total_seconds()
            left = int(left_s)
            self.countdown.config(text=tr("expires", m=left // 60, s=left % 60) if left > 0 else tr("new_code"))
            share = max(0.0, min(1.0, left_s / self.pin_total))
            self.bar.coords(self.bar_fill, 4, 4, 4 + 282 * share, 4)
            self.bar.itemconfigure(self.bar_fill, state="normal" if share > 0 else "hidden")
        self.root.after(50, self.tick)  # seguido, para que la barra baje suave

    # ---------- Mensajes del hilo de red ----------

    def on_pin(self, pin: str, expires: datetime) -> None:
        self.expires = expires
        url = f"{APP_URL}#{pin}"
        png = segno.make(url, error="m").png_data_uri(scale=6, border=2, dark=QR_DARK, light=QR_LIGHT)
        self.qr_image = tk.PhotoImage(data=png.split(",", 1)[1])
        self.pin_total = max(1.0, (expires - datetime.now(timezone.utc)).total_seconds())
        self.linked.pack_forget()
        self.waiting.pack(anchor="w")
        self.reveal_qr()
        self.reveal_pin(pin)
        self.retry.pack_forget()
        self.status.config(text=tr("waiting"))

    def reveal_qr(self) -> None:
        """El QR aparece de arriba hacia abajo, como si se imprimiera."""
        w, h = self.qr_image.width(), self.qr_image.height()
        self.qr.config(width=w, height=h)
        self.qr.delete("all")
        self.qr.create_image(0, 0, image=self.qr_image, anchor="nw")
        cover = self.qr.create_rectangle(0, 0, w, h, fill=PAPER, outline="")
        edge = self.qr.create_line(0, 0, w, 0, fill=ACCENT, width=2)

        def step(t: float) -> None:
            y = h * t
            self.qr.coords(cover, 0, y, w, h)
            self.qr.coords(edge, 0, y, w, y)
            if t >= 1:
                self.qr.delete(cover, edge)

        animate(self.qr, 0.6, step)

    def reveal_pin(self, pin: str) -> None:
        """Los dígitos aparecen uno tras otro."""
        def step(t: float) -> None:
            shown = pin[: round(6 * t)].ljust(6, "·")
            self.pin.config(text=f"{shown[:3]} {shown[3:]}")

        animate(self.pin, 0.45, step)

    def draw_check(self, ok: bool) -> None:
        """Círculo verde que crece y una marca de visto que se dibuja; gris si el celular se fue."""
        c = self.check
        c.delete("all")
        if not ok:
            c.create_oval(4, 4, 40, 40, outline=MUTED, width=2)
            return
        circle = c.create_oval(22, 22, 22, 22, fill=OK, outline="")
        mark = c.create_line(13, 23, 13, 23, fill="white", width=4, capstyle="round", joinstyle="round")
        pts = [(13, 23), (19, 29), (31, 16)]

        def step(t: float) -> None:
            r = 18 * min(1.0, t * 1.6)
            c.coords(circle, 22 - r, 22 - r, 22 + r, 22 + r)
            # El trazo empieza cuando el círculo ya creció: k va de 0 a 2 (dos tramos de la marca).
            k = max(0.0, (t - 0.35) / 0.65) * 2
            seg = min(1, int(k))
            frac = min(1.0, k - seg)
            (x0, y0), (x1, y1) = pts[seg], pts[seg + 1]
            done = [v for p in pts[: seg + 1] for v in p]
            c.coords(mark, *done, x0 + (x1 - x0) * frac, y0 + (y1 - y0) * frac)

        animate(c, 0.5, step)

    def on_ask(self, name: str) -> None:
        self.on_show()
        allow, remember = AskDialog(self.root, name).wait()
        self.link.call(self.link.answer(allow, remember))

    def on_connected(self, guest_here: bool, name: str = "") -> None:
        self.expires = None
        self.guest_here = guest_here
        self.guest_name = name or self.guest_name or tr("device")
        self.waiting.pack_forget()
        self.linked.pack(anchor="w")
        self.linked_text.config(text=tr("connected", name=self.guest_name) if guest_here else tr("gone"))
        self.draw_check(guest_here)
        self.show_link_status()

    def on_direct(self, on: bool) -> None:
        self.direct = on
        if self.linked.winfo_ismapped():
            self.show_link_status()

    def show_link_status(self) -> None:
        text = tr("st_away") if not self.guest_here else tr("st_direct") if self.direct else tr("st_cloud")
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
        self.update_text.config(text=tr("update_new", tag=asset["tag"]))
        self.update_btn.config(state="normal", text=tr("update_btn"))
        self.update_bar.pack(fill="x", pady=(14, 0), after=self.title)

    def start_update(self) -> None:
        self.update_btn.config(state="disabled")
        self.update_text.config(text=tr("downloading"))
        self.link.call(self.link.update(self.update_asset))

    def on_update_failed(self, detail: str) -> None:
        self.update_text.config(text=tr("update_failed"))
        self.update_btn.config(state="normal", text=tr("retry"))

    def on_restart(self) -> None:
        # La versión nueva ya se abrió; esta se cierra (y cierra su sala).
        self.quit()

    def on_error(self, text: str) -> None:
        self.status.config(text=text)
        self.retry.pack(anchor="w", side="bottom")

    # ---------- Dispositivos de confianza ----------

    def on_trusted(self, rows: list[dict]) -> None:
        self.trusted = rows
        if rows:
            self.trusted_link.config(text=tr("trusted_link", n=len(rows)))
            self.trusted_link.pack(anchor="w", side="bottom", pady=(10, 0), before=self.status)
        else:
            self.trusted_link.pack_forget()
        if self.trusted_win is not None and self.trusted_win.winfo_exists():
            self.fill_trusted()

    def open_trusted(self) -> None:
        if self.trusted_win is not None and self.trusted_win.winfo_exists():
            self.trusted_win.lift()
            return
        top = self.trusted_win = tk.Toplevel(self.root, bg=PAPER, padx=24, pady=20)
        top.title(tr("trusted_title"))
        top.resizable(False, False)
        top.transient(self.root)
        match_title_bar(top)
        tk.Label(top, text=tr("trusted_title"), font=("Segoe UI Semibold", 14), bg=PAPER, fg=INK).pack(anchor="w")
        self.trusted_rows = tk.Frame(top, bg=PAPER)
        self.trusted_rows.pack(fill="x", pady=(12, 16))
        soft_button(top, tr("close"), top.destroy).pack(anchor="e")
        top.bind("<Escape>", lambda _e: top.destroy())
        self.fill_trusted()
        top.update_idletasks()
        x = self.root.winfo_rootx() + 20
        y = self.root.winfo_rooty() + 60
        top.geometry(f"+{x}+{y}")

    def fill_trusted(self) -> None:
        for child in self.trusted_rows.winfo_children():
            child.destroy()
        if not self.trusted:
            tk.Label(self.trusted_rows, text=tr("trusted_empty"), font=("Segoe UI", 10), bg=PAPER, fg=MUTED,
                     wraplength=280, justify="left").pack(anchor="w")
            return
        for row in self.trusted:
            line = tk.Frame(self.trusted_rows, bg=PAPER)
            line.pack(fill="x", pady=3)
            tk.Label(line, text=row["guest_name"], font=("Segoe UI", 10), bg=PAPER, fg=INK).pack(side="left")
            soft_button(line, tr("forget"), lambda g=row["guest_id"]: self.link.call(self.link.forget(g)),
                        ).pack(side="right", padx=(24, 0))

    # ---------- Acciones ----------

    def reconnect(self) -> None:
        self.retry.pack_forget()
        self.status.config(text=tr("connecting"))
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
        self.tray.stop()
        self.root.destroy()


def main() -> None:
    if sys.platform == "win32":
        # Coordenadas en píxeles reales y ventana nítida en pantallas con escala.
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass
    remove_old_exe()
    Window().run(hidden="--tray" in sys.argv)


if __name__ == "__main__":
    main()
