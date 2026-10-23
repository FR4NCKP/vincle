import { send } from './net'
import { t } from './i18n'

// Dictado por voz con el reconocimiento del propio navegador (en Android, el de Google; en
// iPhone, el de Apple). Es gratis y no pasa por Supabase: a la PC solo llega el texto final.

type Recognition = {
  lang: string
  continuous: boolean
  interimResults: boolean
  onresult: ((e: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null
  onend: (() => void) | null
  onerror: (() => void) | null
  start(): void
  stop(): void
}

export function setupDictation(button: HTMLButtonElement, input: HTMLInputElement) {
  const w = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition }
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition
  if (!Ctor) return // sin soporte, el botón queda oculto
  button.hidden = false

  let rec: Recognition | null = null
  let sentSomething = false

  function setListening(on: boolean) {
    button.setAttribute('aria-pressed', String(on))
    input.placeholder = on ? t('listening') : t('type_ph')
  }

  function stop() {
    rec?.stop()
  }

  function start() {
    const r = new Ctor!()
    rec = r
    sentSomething = false
    // Se dicta en el idioma del celular, no en el de la interfaz.
    r.lang = navigator.language
    r.continuous = true
    r.interimResults = false
    r.onresult = (e) => {
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const result = e.results[i]
        const text = result[0].transcript.trim()
        if (!result.isFinal || !text) continue
        // Entre frases dictadas seguidas va un espacio.
        send({ event: 'text', payload: { text: (sentSomething ? ' ' : '') + text } })
        sentSomething = true
      }
    }
    r.onend = r.onerror = () => {
      if (rec === r) rec = null
      setListening(false)
    }
    try {
      r.start()
      setListening(true)
      navigator.vibrate?.(15)
    } catch {
      rec = null
      setListening(false)
    }
  }

  // Tocar el micrófono no debe quitarle el foco al campo (ni abrir o cerrar el teclado).
  button.addEventListener('pointerdown', (e) => e.preventDefault())
  button.addEventListener('click', () => (rec ? stop() : start()))

  return stop
}
