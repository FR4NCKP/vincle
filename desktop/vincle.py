"""Vincle para la PC: recibe del celular los movimientos, clics y teclas, y los ejecuta.

La conexión pasa por Supabase Realtime (canal privado "room:<id>"). La PC crea la sala y
muestra un QR y un PIN de 6 dígitos; el celular la reclama y la PC pide permiso antes de
obedecerle. El protocolo está descrito en el README.
"""

import asyncio
import ctypes
import json
import os
import queue
import socket
import sys
import threading
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox

import segno
from pynput.keyboard import Controller as Keyboard, Key, KeyCode
from pynput.mouse import Button, Controller as Mouse
from realtime import RealtimeSubscribeStates
from supabase import AsyncClientOptions, acreate_client
from supabase_auth import AsyncSupportedStorage

# Valores públicos: la seguridad la dan las políticas RLS, no el secreto de esta clave.
SUPABASE_URL = "https://rmhuktsftptgrrzmqcon.supabase.co"
SUPABASE_KEY = "sb_publishable_2adm7NJ_11XgwuWZglo01A_7C5TI56i"
# Para probar la app web en la red local: VINCLE_APP_URL=http://192.168.x.x:5173/
APP_URL = os.environ.get("VINCLE_APP_URL", "https://fr4nckp.github.io/vincle/")

HOST_NAME = socket.gethostname()[:64] or "PC"
DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "Vincle"

# Un "clic" de rueda (120 unidades en Windows) equivale a unos 40 px de dedo.
SCROLL_PX_PER_NOTCH = 40
MAX_MOVE = 2000
MAX_TEXT = 2000
SPECIAL_KEYS = {
    "esc": Key.esc,
    "tab": Key.tab,
    "left": Key.left,
    "right": Key.right,
    "enter": Key.enter,
    "backspace": Key.backspace,
}

PAPER, INK, MUTED = "#F5F5F3", "#0A0A0A", "#5C5C5A"


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
        self.keyboard = Keyboard()
        self.dragging = False
        self.scroll_rest = [0.0, 0.0]

    # ---------- Hilo y llamadas desde la ventana ----------

    def start(self) -> None:
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.call(self.connect())

    def call(self, coro) -> None:
        asyncio.run_coroutine_threadsafe(coro, self.loop)

    # ---------- Sala ----------

    async def connect(self) -> None:
        try:
            if self.client is None:
                self.client = await acreate_client(
                    SUPABASE_URL,
                    SUPABASE_KEY,
                    options=AsyncClientOptions(storage=FileStorage(), realtime={"max_retries": 1_000_000}),
                )
            if await self.client.auth.get_session() is None:
                await self.client.auth.sign_in_anonymously()
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
        for event in ("move", "scroll", "click", "drag", "text", "key"):
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

    # ---------- Permiso ----------

    def on_hello(self) -> None:
        """El celular entró (o volvió a entrar) al canal."""
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

    # ---------- Órdenes del celular ----------

    def on_input(self, message) -> None:
        if not self.accepted:
            return  # Nada se ejecuta sin el permiso explícito de quien está en la PC.
        handler = getattr(self, f"do_{message.get('event')}", None)
        if handler is None:
            return
        try:
            handler(message.get("payload") or {})
        except (TypeError, ValueError, KeyError):
            pass  # Mensaje mal formado: se ignora.

    def do_move(self, d: dict) -> None:
        x = max(-MAX_MOVE, min(MAX_MOVE, int(d["x"])))
        y = max(-MAX_MOVE, min(MAX_MOVE, int(d["y"])))
        self.mouse.move(x, y)

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
            self.dragging = False
            self.mouse.release(Button.left)

    def do_text(self, d: dict) -> None:
        self.keyboard.type(str(d["text"])[:MAX_TEXT])

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


class Window:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Vincle")
        self.root.configure(bg=PAPER, padx=36, pady=28)
        self.root.resizable(False, False)
        self.ui: queue.Queue = queue.Queue()
        self.link = Link(self.ui)
        self.expires: datetime | None = None

        serif = ("Georgia", 54, "italic")
        tk.Label(self.root, text="Vincle", font=serif, bg=PAPER, fg=INK).pack(anchor="w")

        # Vista "esperando": QR + PIN.
        self.waiting = tk.Frame(self.root, bg=PAPER)
        self.eyebrow(self.waiting, "ESCANEA CON TU CELULAR").pack(anchor="w", pady=(18, 8))
        self.qr = tk.Label(self.waiting, bg=PAPER)
        self.qr.pack()
        self.eyebrow(self.waiting, "O ESCRIBE EL CÓDIGO").pack(anchor="w", pady=(18, 4))
        self.pin = tk.Label(self.waiting, text="······", font=("Georgia", 44), bg=PAPER, fg=INK)
        self.pin.pack(anchor="w")
        self.countdown = tk.Label(self.waiting, text="", font=("Segoe UI", 10), bg=PAPER, fg=MUTED)
        self.countdown.pack(anchor="w")

        # Vista "conectado".
        self.linked = tk.Frame(self.root, bg=PAPER)
        self.eyebrow(self.linked, "ESTADO").pack(anchor="w", pady=(18, 4))
        self.linked_text = tk.Label(self.linked, text="", font=("Georgia", 26), bg=PAPER, fg=INK, justify="left")
        self.linked_text.pack(anchor="w")
        tk.Button(
            self.linked, text="Desconectar", command=self.disconnect, font=("Segoe UI", 11),
            bg=INK, fg="white", activebackground="#3A3A38", activeforeground="white",
            relief="flat", padx=18, pady=10, cursor="hand2",
        ).pack(anchor="w", pady=(24, 0))

        self.status = tk.Label(self.root, text="Conectando con el servidor…", font=("Segoe UI", 10),
                               bg=PAPER, fg=MUTED, justify="left", wraplength=300)
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
        self.waiting.pack_forget()
        self.linked.pack(anchor="w")
        self.linked_text.config(text="Celular conectado" if guest_here else "El celular se\ndesconectó")
        self.status.config(text="Lo que hagas en el celular se ejecuta aquí." if guest_here
                           else "Se reconectará solo al volver a abrir Vincle en el celular.")

    def on_status(self, text: str) -> None:
        self.status.config(text=text)

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
    Window().run()


if __name__ == "__main__":
    main()
