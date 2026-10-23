import './style.css'
import './motion.css'
import {
  claim, claimTrusted, disconnect, forgetHost, join, savedRoom, send, trustedHosts, type LinkState, type Room,
} from './net'
import { getSensitivity, setSensitivity, setupPad } from './pad'
import { setupKeys } from './keys'
import { keepScreenOn, setupPresent } from './present'
import { setupMedia } from './media'
import { setupDictation } from './dictation'
import { startScanner } from './scanner'
import { playEnter, replay, setupPressFeedback, wait } from './motion'
import { applyTexts, getLang, setLang, t, type Lang } from './i18n'

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T

const screens = { desktop: $('desktop'), connect: $('connect'), remote: $('remote') }
type ScreenName = keyof typeof screens
const panels = { pad: $('pad'), present: $('present'), media: $('media') }
type PanelName = keyof typeof panels

const typingInput = $<HTMLInputElement>('texto')

let room: Room | null = null
let stopScan: (() => void) | null = null
let panel: PanelName = 'pad'

function show(name: ScreenName) {
  const wasHidden = screens[name].hidden
  for (const [key, el] of Object.entries(screens)) el.hidden = key !== name
  if (wasHidden) playEnter(screens[name])
  if (name !== 'connect') {
    stopScanner()
    stopWatchingTrusted()
  } else if (wasHidden) {
    void watchTrusted()
  }
  if (name !== 'remote') {
    typingInput.blur()
    stopDictation?.()
  }
  void keepScreenOn(name === 'remote' && panel === 'present')
}

// ---------- Pestañas del control: trackpad, diapositivas y multimedia ----------

const tabButtons = Array.from($('tabs').querySelectorAll<HTMLButtonElement>('[data-tab]'))

function showPanel(name: PanelName) {
  if (name === panel) return
  panel = name
  for (const [key, el] of Object.entries(panels)) el.hidden = key !== name
  tabButtons.forEach((btn, i) => {
    const on = btn.dataset.tab === name
    btn.setAttribute('aria-selected', String(on))
    if (on) $('tabs').style.setProperty('--tab', String(i)) // la "pastilla" se desliza hasta aquí
  })
  screens.remote.dataset.panel = name
  playEnter(panels[name])
  if (name !== 'pad') {
    typingInput.blur()
    stopDictation?.()
  }
  void keepScreenOn(name === 'present')
}

tabButtons.forEach((btn) => btn.addEventListener('click', () => showPanel(btn.dataset.tab as PanelName)))

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

// ---------- Estado de la conexión y latencia ----------

const statusEls = document.querySelectorAll<HTMLElement>('[data-status]')
let linkState: LinkState = 'joining'
let latency: number | null = null

function setStatus(state: LinkState) {
  if (state === 'rejected' || state === 'lost') {
    room = null
    toConnect(state === 'rejected' ? t('rejected') : t('lost'), true)
    return
  }
  linkState = state
  renderStatus()
}

function renderStatus() {
  const state = linkState
  const name = room?.name ?? t('the_pc')
  const live = state === 'connected' || state === 'direct'
  let text =
    state === 'direct' ? t('st_direct')
    : state === 'connected' ? t('st_connected')
    : state === 'waiting' ? t('st_waiting', { name })
    : state === 'host-away' ? t('st_away', { name })
    : t('st_joining')
  // Ida y vuelta de un mensaje hasta la PC: lo que tarda el cursor en reaccionar, más o menos.
  if (live && latency !== null) text += ` · ${latency} ms`
  for (const el of statusEls) {
    const label = el.querySelector<HTMLElement>('[data-status-text]')!
    if (label.textContent !== text) {
      // La animación solo al cambiar de estado, no cada vez que cambia la cifra.
      const sameState = label.dataset.state === state
      label.textContent = text
      label.dataset.state = state
      if (!sameState) replay(label, 'swap')
    }
    el.classList.toggle('ok', live)
    el.classList.toggle('slow', live && latency !== null && latency > 150)
  }
}

function setLatency(ms: number | null) {
  latency = ms
  renderStatus()
}

function enterRoom(r: Room) {
  room = r
  $('host-name').textContent = r.name
  linkState = 'joining'
  latency = null
  renderStatus()
  show('remote')
  join(r, setStatus, setLatency)
}

// ---------- 01 Conexión ----------

const pinInputs = Array.from($('pin').querySelectorAll('input'))
const connectBtn = $<HTMLButtonElement>('connect-btn')
const connectMsg = $('connect-msg')
let connecting = false

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
  note(message ?? t('connect_note'), isError)
  show('connect')
}

async function connect(pin: string) {
  if (!/^\d{6}$/.test(pin)) {
    note(t('need6'), true)
    return
  }
  connecting = true
  connectBtn.disabled = true
  connectBtn.classList.add('loading')
  note(t('st_joining'))
  const pinRow = $('pin')
  try {
    const r = await claim(pin)
    pinRow.classList.add('ok') // ola verde en los dígitos antes de pasar al trackpad
    await wait(520)
    enterRoom(r)
  } catch (err) {
    note((err as Error).message, true)
    replay(pinRow, 'shake')
    navigator.vibrate?.(60)
  } finally {
    connecting = false
    pinRow.classList.remove('ok')
    connectBtn.disabled = false
    connectBtn.classList.remove('loading')
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

function stopScanner() {
  stopScan?.()
  stopScan = null
  viewfinder.classList.remove('live', 'found')
  scanHint.textContent = t('scan_hint')
}

viewfinder.addEventListener('click', async () => {
  if (stopScan) {
    stopScanner()
    return
  }
  scanHint.textContent = t('cam_opening')
  try {
    stopScan = await startScanner($<HTMLVideoElement>('scan-video'), async (pin) => {
      // Detectado: las esquinas se ajustan en verde y se dibuja un ✓; luego se conecta.
      viewfinder.classList.add('found')
      scanHint.textContent = t('cam_found')
      navigator.vibrate?.([15, 40, 15])
      await wait(800)
      stopScanner()
      fillPin(pin)
      void connect(pin)
    })
    viewfinder.classList.add('live')
    scanHint.textContent = t('cam_aim')
  } catch {
    stopScanner()
    scanHint.textContent = t('cam_fail')
  }
})

// ---------- Computadoras de confianza: conexión sin código ----------
// Mientras se está en la pantalla de conexión, si alguna PC recuerda este celular, se
// pregunta cada pocos segundos si abrió una sala; en cuanto la abre, se entra solo.

const TRUST_POLL_MS = 3000
const trustedNote = $('trusted-note')
let trustTimer = 0
let trustRun = 0

function stopWatchingTrusted() {
  clearTimeout(trustTimer)
  trustRun++
}

async function watchTrusted() {
  stopWatchingTrusted()
  const run = trustRun
  const hosts = await trustedHosts()
  if (run !== trustRun) return
  trustedNote.hidden = !hosts.length
  if (!hosts.length) return
  $('trusted-note-text').textContent = t('trusted_note', { names: hosts.map((h) => h.host_name).join(', ') })
  const tick = async () => {
    if (run !== trustRun) return
    if (document.visibilityState === 'visible' && !connecting && !room) {
      const r = await claimTrusted()
      if (run !== trustRun) return
      if (r) {
        navigator.vibrate?.([15, 40, 15])
        enterRoom(r)
        return
      }
    }
    trustTimer = window.setTimeout(tick, TRUST_POLL_MS)
  }
  void tick()
}

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
    screens.remote.classList.toggle('typing-on', typing)
    toggleKeys.setAttribute('aria-pressed', String(typing))
  },
})
const stopDictation = setupDictation($<HTMLButtonElement>('mic'), typingInput)

// ---------- Diapositivas y multimedia ----------

setupPresent({ laserPad: $('laser-pad'), laserDot: $('laser-dot'), buttons: $('slide-buttons') })
setupMedia($('media-buttons'))
// El sistema suelta el "mantener encendida" al salir de la app; al volver se pide de nuevo.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && !screens.remote.hidden && panel === 'present') void keepScreenOn(true)
})

// ---------- Tema (claro, oscuro o el del sistema) ----------

const THEME_KEY = 'vincle.theme'
type Theme = 'auto' | 'light' | 'dark'
const themeMeta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')!

function getTheme(): Theme {
  try {
    const v = localStorage.getItem(THEME_KEY)
    return v === 'light' || v === 'dark' ? v : 'auto'
  } catch {
    return 'auto'
  }
}

function applyTheme(theme: Theme) {
  const root = document.documentElement
  if (theme === 'auto') delete root.dataset.theme
  else root.dataset.theme = theme
  // La barra del navegador toma el color del fondo.
  themeMeta.content = getComputedStyle(root).getPropertyValue('--bg').trim()
}

applyTheme(getTheme())
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => applyTheme(getTheme()))

// ---------- Ajustes ----------

const settings = $<HTMLDialogElement>('settings')
const sensitivity = $<HTMLInputElement>('sensitivity')
const sensitivityOut = $('sensitivity-out')
const showSensitivity = () => { sensitivityOut.textContent = `${Number(sensitivity.value).toFixed(1)}×` }
const trustedList = $('trusted-list')
const trustedRows = $('trusted-rows')

function check(group: string, value: string) {
  const input = settings.querySelector<HTMLInputElement>(`input[name="${group}"][value="${value}"]`)
  if (input) input.checked = true
}

async function renderTrusted() {
  const hosts = await trustedHosts()
  trustedList.hidden = !hosts.length
  trustedRows.replaceChildren(...hosts.map((h) => {
    const li = document.createElement('li')
    li.className = 'raised-sm'
    const name = document.createElement('span')
    name.textContent = h.host_name // viene de la PC: siempre como texto
    const forget = document.createElement('button')
    forget.type = 'button'
    forget.className = 'chip raised-sm'
    forget.textContent = t('forget')
    forget.addEventListener('click', async () => {
      forget.disabled = true
      await forgetHost(h.host_id)
      await renderTrusted()
      if (!screens.connect.hidden) void watchTrusted()
    })
    li.append(name, forget)
    return li
  }))
}

document.querySelectorAll('[data-open-settings]').forEach((btn) => btn.addEventListener('click', () => {
  sensitivity.value = String(getSensitivity())
  showSensitivity()
  check('theme', getTheme())
  check('lang', getLang())
  $('disconnect').hidden = !room
  void renderTrusted()
  settings.showModal()
}))
sensitivity.addEventListener('input', () => {
  setSensitivity(Number(sensitivity.value))
  showSensitivity()
})
$('theme-choice').addEventListener('change', (e) => {
  const theme = (e.target as HTMLInputElement).value as Theme
  try { localStorage.setItem(THEME_KEY, theme) } catch { /* solo esta sesión */ }
  applyTheme(theme)
})
$('lang-choice').addEventListener('change', (e) => {
  setLang((e.target as HTMLInputElement).value as Lang)
  localizeDynamic()
})
$('disconnect').addEventListener('click', () => {
  disconnect()
  room = null
  settings.close()
  toConnect()
})

// ---------- Idioma ----------

/** Textos que arma el código (no están marcados en el HTML). */
function localizeDynamic() {
  pinInputs.forEach((input, i) => input.setAttribute('aria-label', t('digit', { n: i + 1 })))
  if (!stopScan) scanHint.textContent = t('scan_hint')
  if (!connectMsg.classList.contains('error')) note(t('connect_note'))
  renderStatus()
  if (!screens.connect.hidden) void watchTrusted()
  if (settings.open) void renderTrusted()
}

applyTexts()
localizeDynamic()

// ---------- Arranque ----------

setupPressFeedback()

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
