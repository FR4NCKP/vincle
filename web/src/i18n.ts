// Textos de la interfaz en español e inglés. El HTML lleva el español de base y estas marcas:
// data-i18n (texto), data-i18n-html (texto con <b> o <br>), data-i18n-label (aria-label) y
// data-i18n-ph (placeholder). El idioma sale de Ajustes o, si no se eligió, del navegador.

const es = {
  tagline: 'Tu celular como trackpad y teclado',
  dl_title: 'Para tu computadora',
  dl_sub: 'Tres pasos y listo',
  dl_1: 'Descarga <b>Vincle.exe</b> y ábrelo con doble clic. No se instala nada.',
  dl_2: 'Abre esta página en tu celular y escanea el código que aparece en la computadora.',
  dl_3: 'Acepta la conexión en la computadora.',
  dl_note: 'La primera vez, Windows puede mostrar «Windows protegió su PC». Toca «Más información» y luego «Ejecutar de todas formas».',
  dl_btn: 'Descargar para Windows',
  use_remote: 'Usar esta página como control',
  settings: 'Ajustes',
  scan_title: 'Escanea el código QR',
  scan_sub: 'El que muestra tu computadora',
  scan_aria: 'Activar la cámara para escanear el código QR',
  scan_hint: 'Toca para activar la cámara y apunta al código que muestra tu computadora',
  or: 'o',
  pin_title: 'Código de 6 dígitos',
  pin_sub: 'Escríbelo si no puedes escanear',
  digit: 'Dígito {n}',
  connect_note: 'Ambos aparecen al abrir Vincle en tu computadora.',
  connect_btn: 'Conectar',
  trusted_note: 'Se conectará solo a {names} en cuanto abras Vincle ahí.',
  tabs: 'Modo',
  tab_pad: 'Trackpad',
  tab_present: 'Diapositivas',
  tab_media: 'Multimedia',
  keyboard: 'Teclado',
  surface_aria: 'Superficie del trackpad',
  surface_hint: 'Un dedo mueve el cursor<br>Dos dedos desplazan o hacen zoom<br>Tres dedos cambian de ventana<br>Mantén pulsado para arrastrar',
  key_left: 'Flecha izquierda',
  key_right: 'Flecha derecha',
  key_back: 'Borrar',
  type_ph: 'Toca aquí para escribir',
  type_aria: 'Escribir en la computadora',
  dictate: 'Dictar por voz',
  listening: 'Escuchando…',
  click: 'Clic',
  click_sub: 'Botón izquierdo',
  rclick: 'Clic derecho',
  rclick_sub: 'Menú contextual',
  laser_title: 'Puntero láser',
  laser_sub: 'Mantén el dedo y muévelo para señalar',
  laser_aria: 'Zona del puntero láser',
  laser_hint: 'Toca aquí',
  prev_slide: 'Diapositiva anterior',
  prev: 'Anterior',
  next_slide: 'Diapositiva siguiente',
  next: 'Siguiente',
  start_show: 'Iniciar presentación',
  start: 'Iniciar',
  exit: 'Salir',
  media_title: 'Multimedia',
  media_sub: 'Música y videos de la computadora',
  play: 'Reproducir o pausar',
  prev_track: 'Pista anterior',
  next_track: 'Pista siguiente',
  volume: 'Volumen',
  vol_down: 'Bajar volumen',
  vol_up: 'Subir volumen',
  mute: 'Silenciar',
  set_sub: 'Se guardan en este celular',
  sensitivity: 'Sensibilidad del cursor',
  theme: 'Tema',
  theme_auto: 'Auto',
  theme_light: 'Claro',
  theme_dark: 'Oscuro',
  language: 'Idioma',
  trusted_pcs: 'Computadoras de confianza',
  forget: 'Olvidar',
  disconnect: 'Desconectar',
  done: 'Listo',
  st_direct: 'Conexión directa',
  st_connected: 'Conectado',
  st_waiting: 'Acepta en {name}',
  st_away: '{name} no está en línea',
  st_joining: 'Conectando…',
  the_pc: 'la computadora',
  rejected: 'La computadora rechazó la conexión.',
  lost: 'La sesión terminó. Vuelve a escanear el código.',
  need6: 'Escribe los 6 dígitos que muestra tu computadora.',
  cam_opening: 'Abriendo la cámara…',
  cam_found: '¡Código detectado!',
  cam_aim: 'Apunta al código que muestra tu computadora',
  cam_fail: 'No se pudo abrir la cámara. Usa el código de 6 dígitos.',
  err_session: 'No se pudo iniciar la sesión. Revisa tu conexión.',
  err_rate: 'Demasiados intentos. Espera unos minutos.',
  err_net: 'No se pudo conectar. Revisa tu conexión.',
  err_pin: 'Código incorrecto o vencido.',
  dev_phone: 'Celular {os}',
  dev_tablet: 'Tablet {os}',
}

type Key = keyof typeof es

const en: Record<Key, string> = {
  tagline: 'Your phone as a trackpad and keyboard',
  dl_title: 'For your computer',
  dl_sub: 'Three steps and you’re done',
  dl_1: 'Download <b>Vincle.exe</b> and double-click it. Nothing to install.',
  dl_2: 'Open this page on your phone and scan the code shown on the computer.',
  dl_3: 'Accept the connection on the computer.',
  dl_note: 'The first time, Windows may show “Windows protected your PC”. Click “More info” and then “Run anyway”.',
  dl_btn: 'Download for Windows',
  use_remote: 'Use this page as a remote',
  settings: 'Settings',
  scan_title: 'Scan the QR code',
  scan_sub: 'The one on your computer',
  scan_aria: 'Turn on the camera to scan the QR code',
  scan_hint: 'Tap to turn on the camera and point it at the code on your computer',
  or: 'or',
  pin_title: '6-digit code',
  pin_sub: 'Type it if you can’t scan',
  digit: 'Digit {n}',
  connect_note: 'Both appear when you open Vincle on your computer.',
  connect_btn: 'Connect',
  trusted_note: 'It will connect to {names} on its own as soon as you open Vincle there.',
  tabs: 'Mode',
  tab_pad: 'Trackpad',
  tab_present: 'Slides',
  tab_media: 'Media',
  keyboard: 'Keyboard',
  surface_aria: 'Trackpad surface',
  surface_hint: 'One finger moves the cursor<br>Two fingers scroll or zoom<br>Three fingers switch windows<br>Press and hold to drag',
  key_left: 'Left arrow',
  key_right: 'Right arrow',
  key_back: 'Backspace',
  type_ph: 'Tap here to type',
  type_aria: 'Type on the computer',
  dictate: 'Voice typing',
  listening: 'Listening…',
  click: 'Click',
  click_sub: 'Left button',
  rclick: 'Right click',
  rclick_sub: 'Context menu',
  laser_title: 'Laser pointer',
  laser_sub: 'Hold your finger and move it to point',
  laser_aria: 'Laser pointer area',
  laser_hint: 'Touch here',
  prev_slide: 'Previous slide',
  prev: 'Previous',
  next_slide: 'Next slide',
  next: 'Next',
  start_show: 'Start slideshow',
  start: 'Start',
  exit: 'Exit',
  media_title: 'Media',
  media_sub: 'Music and videos on the computer',
  play: 'Play or pause',
  prev_track: 'Previous track',
  next_track: 'Next track',
  volume: 'Volume',
  vol_down: 'Volume down',
  vol_up: 'Volume up',
  mute: 'Mute',
  set_sub: 'Saved on this phone',
  sensitivity: 'Cursor sensitivity',
  theme: 'Theme',
  theme_auto: 'Auto',
  theme_light: 'Light',
  theme_dark: 'Dark',
  language: 'Language',
  trusted_pcs: 'Trusted computers',
  forget: 'Forget',
  disconnect: 'Disconnect',
  done: 'Done',
  st_direct: 'Direct connection',
  st_connected: 'Connected',
  st_waiting: 'Accept on {name}',
  st_away: '{name} is offline',
  st_joining: 'Connecting…',
  the_pc: 'the computer',
  rejected: 'The computer rejected the connection.',
  lost: 'The session ended. Scan the code again.',
  need6: 'Type the 6 digits shown on your computer.',
  cam_opening: 'Opening the camera…',
  cam_found: 'Code found!',
  cam_aim: 'Point at the code on your computer',
  cam_fail: 'Couldn’t open the camera. Use the 6-digit code.',
  err_session: 'Couldn’t start the session. Check your connection.',
  err_rate: 'Too many attempts. Wait a few minutes.',
  err_net: 'Couldn’t connect. Check your connection.',
  err_pin: 'Wrong or expired code.',
  dev_phone: '{os} phone',
  dev_tablet: '{os} tablet',
}

export type Lang = 'es' | 'en'
const LANG_KEY = 'vincle.lang'

function initialLang(): Lang {
  try {
    const saved = localStorage.getItem(LANG_KEY)
    if (saved === 'es' || saved === 'en') return saved
  } catch { /* sin almacenamiento */ }
  return navigator.language.toLowerCase().startsWith('es') ? 'es' : 'en'
}

let lang: Lang = initialLang()

export const getLang = () => lang

export function t(key: Key, vars: Record<string, string | number> = {}) {
  const text = (lang === 'es' ? es : en)[key]
  return text.replace(/\{(\w+)\}/g, (_, k: string) => String(vars[k] ?? ''))
}

/** Pone los textos del idioma actual en todo lo marcado del HTML. */
export function applyTexts(root: ParentNode = document) {
  document.documentElement.lang = lang
  root.querySelectorAll<HTMLElement>('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n as Key) })
  // Solo textos propios de este archivo, nunca datos de afuera.
  root.querySelectorAll<HTMLElement>('[data-i18n-html]').forEach((el) => { el.innerHTML = t(el.dataset.i18nHtml as Key) })
  root.querySelectorAll<HTMLElement>('[data-i18n-label]').forEach((el) => el.setAttribute('aria-label', t(el.dataset.i18nLabel as Key)))
  root.querySelectorAll<HTMLInputElement>('[data-i18n-ph]').forEach((el) => { el.placeholder = t(el.dataset.i18nPh as Key) })
}

export function setLang(next: Lang) {
  lang = next
  try { localStorage.setItem(LANG_KEY, next) } catch { /* solo esta sesión */ }
  applyTexts()
}
