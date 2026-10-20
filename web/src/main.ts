import './style.css'
import { claim, disconnect, join, savedRoom, send, type LinkState, type Room } from './net'
import { getSensitivity, setSensitivity, setupPad } from './pad'
import { setupKeys } from './keys'
import { startScanner } from './scanner'

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T

const screens = { connect: $('connect'), pad: $('pad'), keys: $('keys') }
type ScreenName = keyof typeof screens

let room: Room | null = null
let stopScan: (() => void) | null = null

function show(name: ScreenName) {
  for (const [key, el] of Object.entries(screens)) el.hidden = key !== name
  if (name !== 'connect') stopScanner()
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
  for (const el of statusEls) {
    const onKeys = screens.keys.contains(el)
    const text =
      state === 'connected' ? (onKeys ? `Enviando a ${name}` : 'Conectado')
      : state === 'waiting' ? `Acepta en ${name}`
      : state === 'host-away' ? `${name} no está en línea`
      : 'Conectando…'
    el.querySelector('[data-status-text]')!.textContent = text
    el.classList.toggle('ok', state === 'connected')
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

// ---------- 02 Trackpad y 03 Teclado ----------

setupPad($('surface'), $('ring'))
$('ring').classList.add('idle')

$('click-left').addEventListener('click', () => send({ event: 'click', payload: { button: 'left' } }))
$('click-right').addEventListener('click', () => send({ event: 'click', payload: { button: 'right' } }))

const textarea = $<HTMLTextAreaElement>('texto')
setupKeys({
  textarea,
  keybar: $('keybar'),
  ctrl: $<HTMLButtonElement>('ctrl'),
  sendBtn: $<HTMLButtonElement>('send'),
  sentBlock: $('sent-block'),
  sentText: $('sent-text'),
})

$('open-keys').addEventListener('click', () => {
  show('keys')
  textarea.focus() // dentro del mismo toque, para que el sistema abra su teclado
})
$('close-keys').addEventListener('click', () => {
  textarea.blur()
  show('pad')
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

const pinInUrl = /^#(\d{6})$/.exec(location.hash)?.[1]
if (pinInUrl) {
  // El PIN es de un solo uso: se quita de la barra de direcciones y del historial.
  history.replaceState(null, '', location.pathname + location.search)
  show('connect')
  fillPin(pinInUrl)
  void connect(pinInUrl)
} else {
  const saved = savedRoom()
  if (saved) enterRoom(saved)
  else show('connect')
}
