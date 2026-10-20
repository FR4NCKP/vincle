import { send } from './net'

export function setupKeys(els: {
  textarea: HTMLTextAreaElement
  keybar: HTMLElement
  ctrl: HTMLButtonElement
  sendBtn: HTMLButtonElement
  sentBlock: HTMLElement
  sentText: HTMLElement
}) {
  const { textarea, keybar, ctrl, sendBtn, sentBlock, sentText } = els
  let ctrlOn = false

  function setCtrl(on: boolean) {
    ctrlOn = on
    ctrl.setAttribute('aria-pressed', String(on))
  }

  function key(name: string) {
    send({ event: 'key', payload: { key: name, ctrl: ctrlOn } })
    setCtrl(false)
  }

  // Envía lo escrito tal cual; con el campo vacío, Enviar funciona como Enter.
  function submit() {
    const text = textarea.value
    if (!text) {
      key('enter')
      return
    }
    send({ event: 'text', payload: { text } })
    sentText.textContent = text
    sentBlock.hidden = false
    textarea.value = ''
  }

  // Los botones no deben quitarle el foco al textarea: si lo pierde, se cierra el teclado.
  keybar.addEventListener('pointerdown', (e) => e.preventDefault())

  keybar.addEventListener('click', (e) => {
    const btn = (e.target as Element).closest<HTMLButtonElement>('button')
    if (!btn) return
    if (btn === ctrl) setCtrl(!ctrlOn)
    else if (btn === sendBtn) submit()
    else if (btn.dataset.key) key(btn.dataset.key)
  })

  textarea.addEventListener('beforeinput', (e) => {
    // La tecla "intro" del teclado del celular equivale a Enviar.
    if (e.inputType === 'insertLineBreak' || e.inputType === 'insertParagraph') {
      e.preventDefault()
      submit()
    }
  })

  textarea.addEventListener('input', (e) => {
    // Con ctrl activo, la siguiente letra se manda como atajo (ctrl + c, ctrl + z...).
    const data = (e as InputEvent).data
    if (ctrlOn && data && data.length === 1) {
      textarea.value = textarea.value.slice(0, -1)
      key(data.toLowerCase())
    }
  })

  textarea.addEventListener('keydown', (e) => {
    // Borrar con el campo vacío borra en la computadora.
    if (e.key === 'Backspace' && !textarea.value) key('backspace')
  })
}
