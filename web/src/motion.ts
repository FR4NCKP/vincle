// Animaciones de la interfaz. Las curvas y duraciones viven en style.css (--ease-*, --dur-*);
// aquí solo se disparan. Todo se omite si el sistema pide "reducir movimiento".

export const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches

export const wait = (ms: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, reducedMotion() ? 0 : ms))

/** Reinicia una animación CSS ligada a una clase (para poder repetirla). */
export function replay(el: Element, cls: string) {
  el.classList.remove(cls)
  void (el as HTMLElement).offsetWidth
  el.classList.add(cls)
  // Solo cuenta el fin de la animación del propio elemento, no las de sus hijos (que suben).
  const done = (e: Event) => {
    if (e.target !== el) return
    el.classList.remove(cls)
    el.removeEventListener('animationend', done)
  }
  el.addEventListener('animationend', done)
}

/** Onda suave que nace en el punto tocado, dentro de `container`. */
export function rippleAt(container: HTMLElement, clientX: number, clientY: number, cls = 'ripple') {
  if (reducedMotion()) return
  const r = container.getBoundingClientRect()
  const size = Math.max(r.width, r.height) * (cls === 'ripple' ? 2 : 0.5)
  const wave = document.createElement('span')
  wave.className = cls
  wave.setAttribute('aria-hidden', 'true')
  wave.style.width = wave.style.height = `${size}px`
  wave.style.left = `${clientX - r.left - size / 2}px`
  wave.style.top = `${clientY - r.top - size / 2}px`
  container.append(wave)
  wave.addEventListener('animationend', () => wave.remove(), { once: true })
  // Si la pestaña está oculta la animación no avanza y no avisa que terminó: no se acumulan.
  setTimeout(() => wave.remove(), 1000)
}

/** Botones: además del hundido (CSS), una onda de luz desde donde se tocó. */
export function setupPressFeedback() {
  document.addEventListener('pointerdown', (e) => {
    const btn = (e.target as Element).closest<HTMLElement>('button, a.pill-btn')
    if (!btn || (btn as HTMLButtonElement).disabled || btn.classList.contains('viewfinder')) return
    rippleAt(btn, e.clientX, e.clientY)
  }, { passive: true })
}

/** Entrada de pantalla: los bloques suben y aparecen uno tras otro. */
export function playEnter(screen: HTMLElement) {
  if (reducedMotion()) return
  const groups = [screen.children, screen.querySelectorAll('.scroll > *, .rows > *')]
  for (const list of groups) {
    Array.from(list).forEach((el, i) => (el as HTMLElement).style.setProperty('--i', String(i)))
  }
  replay(screen, 'entering')
}
