import './style.css'
import { claim, disconnect, join, savedRoom, send, type LinkState, type Room } from './net'
import { getSensitivity, setSensitivity, setupPad } from './pad'
import { setupKeys } from './keys'
import { keepScreenOn, setupPresent } from './present'
import { startScanner } from './scanner'

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T

const screens = { desktop: $('desktop'), connect: $('connect'), pad: $('pad'), present: $('present') }
type ScreenName = keyof typeof screens

const typingInput = $<HTMLInputElement>('texto')

let room: Room | null = null
let stopScan: (() => void) | null = null

function show(name: ScreenName) {
  for (const [key, el] of Object.entries(screens)) el.hidden = key !== name
  if (name !== 'connect') stopScanner()
  if (name !== 'pad') typingInput.blur()
  void keepScreenOn(name === 'present')
}

// ---------- Alto visible: el teclado del sistema no debe tapar la barra de teclas ----------

const vv = window.visualViewport
if (vv) {
  const fit = () => {
    document.documentElement.style.setProperty('--vvh', `${vv.height}px`)
    window.scrollTo(0, 0)
  }
  vv.addEventListener('resize', fit)
  fit()
}

// ---------- Estado de la conexión ----------

const statusEls = document.querySelectorAll<HTMLElement>('[data-status]')

function setStatus(state: LinkState) {
  if (state === 'rejected' || state === 'lost') {
    room = null
    toConnect(state === 'rejected'
      ? 'La computadora rechazó la conexión.'
      : 'La sesión terminó. Vuelve a escanear el código.', true)
    return
  }
  const name = room?.name ?? 'la computadora'
  const text =
    state === 'direct' ? 'Conectado · directo'
    : state === 'connected' ? 'Conectado'
    : state === 'waiting' ? `Acepta en ${name}`
    : state === 'host-away' ? `${name} no está en línea`
    : 'Conectando…'
  for (const el of statusEls) {
    el.querySelector('[data-status-text]')!.textContent = text
    el.classList.toggle('ok', state === 'connected' || state === 'direct')
  }
}

function enterRoom(r: Room) {
  room = r
  setStatus('joining')
  show('pad')
  join(r, setStatus)
}

// ---------- 01 Conexión ----------

const pinInputs = Array.from($('pin').querySelectorAll('input'))
const connectBtn = $<HTMLButtonElement>('connect-btn')
const connectMsg = $('connect-msg')
const DEFAULT_NOTE = connectMsg.textContent

function note(text: string, isError = false) {
  connectMsg.textContent = text
  connectMsg.classList.toggle('error', isError)
}

function pinValue() {
  return pinInputs.map((i) => i.value).join('')
}

function fillPin(digits: string, from = 0) {
  digits.split('').slice(0, 6 - from).forEach((d, k) => { pinInputs[from + k].value = d })
  for (const i of pinInputs) i.classList.toggle('filled', !!i.value)
  pinInputs[Math.min(from + digits.length, 5)].focus()
}

function toConnect(message?: string, isError = false) {
  pinInputs.forEach((i) => { i.value = ''; i.classList.remove('filled') })
  note(message ?? DEFAULT_NOTE ?? '', isError)
  show('connect')
}

async function connect(pin: string) {
  if (!/^\d{6}$/.test(pin)) {
    note('Escribe los 6 dígitos que muestra tu computadora.', true)
    return
  }
  connectBtn.disabled = true
  note('Conectando…')
  try {
    enterRoom(await claim(pin))
  } catch (err) {
    note((err as Error).message, true)
  } finally {
    connectBtn.disabled = false
  }
}

pinInputs.forEach((input, i) => {
  input.addEventListener('input', () => {
    const digits = input.value.replace(/\D/g, '')
    input.value = ''
    if (digits) fillPin(digits, i)
    else input.classList.remove('filled')
    if (pinValue().length === 6) void connect(pinValue())
  })
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Backspace' && !input.value && i > 0) {
      e.preventDefault()
      pinInputs[i - 1].value = ''
      pinInputs[i - 1].classList.remove('filled')
      pinInputs[i - 1].focus()
    }
  })
  input.addEventListener('focus', () => input.select())
})

$('pin-form').addEventListener('submit', (e) => {
  e.preventDefault()
  void connect(pinValue())
})

const viewfinder = $('scan')
const scanHint = $('scan-hint')
const SCAN_HINT = scanHint.textContent

function stopScanner() {
  stopScan?.()
  stopScan = null
  viewfinder.classList.remove('live')
  scanHint.textContent = SCAN_HINT
}

viewfinder.addEventListener('click', async () => {
  if (stopScan) {
    stopScanner()
    return
  }
  scanHint.textContent = 'Abriendo la cámara…'
  try {
    stopScan = await startScanner($<HTMLVideoElement>('scan-video'), (pin) => {
      stopScan = null
      stopScanner()
      fillPin(pin)
      void connect(pin)
    })
    viewfinder.classList.add('live')
    scanHint.textContent = 'Apunta al código que muestra tu computadora'
  } catch {
    stopScanner()
    scanHint.textContent = 'No se pudo abrir la cámara. Usa el código de 6 dígitos.'
  }
})

// ---------- 02 Trackpad y teclado ----------

setupPad($('surface'), $('ring'))
$('ring').classList.add('idle')

$('click-left').addEventListener('click', () => send({ event: 'click', payload: { button: 'left' } }))
$('click-right').addEventListener('click', () => send({ event: 'click', payload: { button: 'right' } }))

const toggleKeys = $<HTMLButtonElement>('toggle-keys')
setupKeys({
  input: typingInput,
  keybar: $('keybar'),
  ctrl: $<HTMLButtonElement>('ctrl'),
  toggle: toggleKeys,
  onTyping: (typing) => {
    // Mientras se escribe, la fila de teclas especiales reemplaza a los botones de clic
    // (tocar el trackpad sigue haciendo clic) para dejarle espacio al trackpad.
    screens.pad.classList.toggle('typing-on', typing)
    toggleKeys.setAttribute('aria-pressed', String(typing))
  },
})

// ---------- 03 Presentación ----------

setupPresent({ laserPad: $('laser-pad'), laserDot: $('laser-dot'), buttons: $('slide-buttons') })
$('open-present').addEventListener('click', () => show('present'))
$('close-present').addEventListener('click', () => show('pad'))
// El sistema suelta el "mantener encendida" al salir de la app; al volver se pide de nuevo.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && !screens.present.hidden) void keepScreenOn(true)
})

// ---------- Ajustes ----------

const settings = $<HTMLDialogElement>('settings')
const sensitivity = $<HTMLInputElement>('sensitivity')
const sensitivityOut = $('sensitivity-out')
const showSensitivity = () => { sensitivityOut.textContent = `${Number(sensitivity.value).toFixed(1)}×` }

document.querySelectorAll('[data-open-settings]').forEach((btn) => btn.addEventListener('click', () => {
  sensitivity.value = String(getSensitivity())
  showSensitivity()
  $('disconnect').hidden = !room
  settings.showModal()
}))
sensitivity.addEventListener('input', () => {
  setSensitivity(Number(sensitivity.value))
  showSensitivity()
})
$('disconnect').addEventListener('click', () => {
  disconnect()
  room = null
  settings.close()
  toConnect()
})

// ---------- Arranque ----------

function connectFromUrl(): boolean {
  const pin = /^#(\d{6})$/.exec(location.hash)?.[1]
  if (!pin) return false
  // El PIN es de un solo uso: se quita de la barra de direcciones y del historial.
  history.replaceState(null, '', location.pathname + location.search)
  // Con una sesión abierta (por ejemplo, escaneando de nuevo el mismo QR) solo se cambia de
  // sala si el código nuevo funciona; si no, se sigue en el trackpad.
  if (!room) {
    show('connect')
    fillPin(pin)
  }
  void connect(pin)
  return true
}

// Si la app ya estaba abierta en esa pestaña, escanear el QR solo cambia el "#PIN" sin recargar.
window.addEventListener('hashchange', connectFromUrl)

if (!connectFromUrl()) {
  const saved = savedRoom()
  if (saved) enterRoom(saved)
  // Con mouse y sin pantalla táctil es casi seguro una computadora: lo útil ahí es descargar el programa.
  else if (matchMedia('(hover: hover) and (pointer: fine)').matches) show('desktop')
  else show('connect')
}

$('use-as-remote').addEventListener('click', () => show('connect'))
