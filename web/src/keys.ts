import { send } from './net'

// El campo solo muestra lo último escrito; cuando crece mucho se recorta (fuera de una
// composición del teclado, para no romper la palabra que se está escribiendo).
const MAX_FIELD = 48
const KEEP_AFTER_TRIM = 16

/**
 * Escritura en vivo: cada cambio del campo se compara con el anterior y a la PC se le manda
 * la diferencia (borrados + texto nuevo). Así funcionan igual las letras sueltas, el
 * autocorrector, las sugerencias y el pegado, que cambian varias letras de una vez.
 */
export function setupKeys(els: {
  input: HTMLInputElement
  keybar: HTMLElement
  ctrl: HTMLButtonElement
  toggle: HTMLButtonElement
  onTyping: (typing: boolean) => void
}) {
  const { input, keybar, ctrl, toggle, onTyping } = els
  let last = ''
  let ctrlOn = false

  function setCtrl(on: boolean) {
    ctrlOn = on
    ctrl.setAttribute('aria-pressed', String(on))
  }

  function key(name: string) {
    send({ event: 'key', payload: { key: name, ctrl: ctrlOn } })
    setCtrl(false)
  }

  input.addEventListener('input', (e) => {
    const now = input.value
    // Con ctrl activo, la siguiente letra es un atajo (ctrl + c, ctrl + z...) y no se escribe.
    if (ctrlOn && now.length === last.length + 1 && now.startsWith(last)) {
      input.value = last
      key(now.slice(-1).toLowerCase())
      return
    }
    let same = 0
    while (same < last.length && same < now.length && last[same] === now[same]) same++
    for (let i = same; i < last.length; i++) key('backspace')
    const added = now.slice(same)
    if (added) send({ event: 'text', payload: { text: added } })
    last = now
    if (now.length > MAX_FIELD && !(e as InputEvent).isComposing) {
      input.value = last = now.slice(-KEEP_AFTER_TRIM)
    }
  })

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      key('enter')
      input.value = last = ''
    } else if (e.key === 'Backspace' && !input.value) {
      // Con el campo vacío el navegador no avisa del borrado: se manda igual a la PC.
      key('backspace')
    }
  })

  // Estos botones no deben quitarle el foco al campo: si lo pierde, se cierra el teclado.
  for (const el of [keybar, toggle]) el.addEventListener('pointerdown', (e) => e.preventDefault())

  keybar.addEventListener('click', (e) => {
    const btn = (e.target as Element).closest<HTMLButtonElement>('button')
    if (!btn) return
    if (btn === ctrl) setCtrl(!ctrlOn)
    else if (btn.dataset.key) {
      key(btn.dataset.key)
      if (btn.dataset.key === 'enter') input.value = last = ''
    }
  })

  toggle.addEventListener('click', () => {
    if (document.activeElement === input) input.blur()
    else input.focus() // dentro del mismo toque, para que el sistema abra su teclado
  })

  input.addEventListener('focus', () => onTyping(true))
  input.addEventListener('blur', () => {
    setCtrl(false)
    onTyping(false)
  })

  // En Android, bajar el teclado con "atrás" no quita el foco del campo. Se detecta porque
  // el alto visible vuelve a ser el de la pantalla completa, y entonces se suelta el foco.
  const vv = window.visualViewport
  if (vv) {
    let fullHeight = vv.height
    let keyboardShown = false
    vv.addEventListener('resize', () => {
      fullHeight = Math.max(fullHeight, vv.height)
      if (vv.height < fullHeight * 0.8) keyboardShown = true
      else if (keyboardShown) {
        keyboardShown = false
        if (document.activeElement === input) input.blur()
      }
    })
  }
}
