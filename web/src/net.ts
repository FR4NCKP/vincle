import { createClient, type RealtimeChannel } from '@supabase/supabase-js'

// Valores públicos: la seguridad la dan las políticas RLS, no el secreto de esta clave.
const SUPABASE_URL = 'https://rmhuktsftptgrrzmqcon.supabase.co'
const SUPABASE_KEY = 'sb_publishable_2adm7NJ_11XgwuWZglo01A_7C5TI56i'

export const supabase = createClient(SUPABASE_URL, SUPABASE_KEY)

export type Room = { id: string; name: string }

/** waiting: unido, la PC aún no aprueba. host-away: aprobado, pero la PC no está en línea.
 *  connected: por Supabase. direct: por la conexión directa con la PC. */
export type LinkState = 'joining' | 'waiting' | 'connected' | 'direct' | 'host-away' | 'rejected' | 'lost'

/** Eventos que el celular envía a la PC (ver README, "Protocolo"). */
export type Outgoing =
  | { event: 'hello'; payload: Record<string, never> }
  | { event: 'move'; payload: { x: number; y: number } }
  | { event: 'scroll'; payload: { x: number; y: number } }
  | { event: 'click'; payload: { button: 'left' | 'right' } }
  | { event: 'drag'; payload: { down: boolean } }
  | { event: 'text'; payload: { text: string } }
  | { event: 'key'; payload: { key: string; ctrl: boolean } }

const ROOM_KEY = 'vincle.room'

export function savedRoom(): Room | null {
  try {
    return JSON.parse(localStorage.getItem(ROOM_KEY) ?? 'null')
  } catch {
    return null
  }
}

function saveRoom(room: Room | null) {
  try {
    if (room) localStorage.setItem(ROOM_KEY, JSON.stringify(room))
    else localStorage.removeItem(ROOM_KEY)
  } catch {
    // Sin almacenamiento: solo se pierde la reconexión automática.
  }
}

async function ensureSession() {
  const { data } = await supabase.auth.getSession()
  if (data.session) return
  const { error } = await supabase.auth.signInAnonymously()
  if (error) throw new Error('No se pudo iniciar la sesión. Revisa tu conexión.')
}

export async function claim(pin: string): Promise<Room> {
  await ensureSession()
  const { data, error } = await supabase.rpc('claim_room', { p_pin: pin })
  if (error) {
    throw new Error(error.hint === 'rate_limited'
      ? 'Demasiados intentos. Espera unos minutos.'
      : 'No se pudo conectar. Revisa tu conexión.')
  }
  const row = (data as { id: string; host_name: string }[] | null)?.[0]
  if (!row) throw new Error('Código incorrecto o vencido.')
  const room = { id: row.id, name: row.host_name }
  saveRoom(room)
  return room
}

let channel: RealtimeChannel | null = null
let live = false
let accepted = false
// Realtime puede entregar desordenados dos mensajes enviados casi juntos; con este número
// la PC los vuelve a poner en orden.
let seq = 0

// ---------- Conexión directa (WebRTC) ----------
// Por Supabase cada movimiento tarda ~100 ms (va a São Paulo y vuelve). Una vez aceptada la
// conexión, el celular propone hablar directo con la PC: en la misma red Wi-Fi tarda unos pocos
// ms. Si la red no lo permite, o la PC tiene una versión sin soporte, se sigue por Supabase.

// Servidor STUN público y gratuito: solo le dice a cada lado su dirección vista desde internet.
const STUN_URL = 'stun:stun.l.google.com:19302'
const DIRECT_TIMEOUT_MS = 8000
const DIRECT_RETRY_MS = 5000
const DIRECT_MAX_FAILURES = 3

let peer: RTCPeerConnection | null = null
let fast: RTCDataChannel | null = null // movimientos: sin orden ni reenvíos, el más rápido
let sure: RTCDataChannel | null = null // clics y teclas: en orden y sin pérdidas
let directFailures = 0
let retryTimer = 0

export function isDirect() {
  return fast?.readyState === 'open' && sure?.readyState === 'open'
}

function iceGathered(pc: RTCPeerConnection, maxMs: number) {
  return new Promise<void>((resolve) => {
    if (pc.iceGatheringState === 'complete') return resolve()
    const timer = setTimeout(resolve, maxMs)
    pc.addEventListener('icegatheringstatechange', () => {
      if (pc.iceGatheringState === 'complete') {
        clearTimeout(timer)
        resolve()
      }
    })
  })
}

async function startDirect(ch: RealtimeChannel, report: () => void) {
  closeDirect()
  const pc = new RTCPeerConnection({ iceServers: [{ urls: STUN_URL }] })
  peer = pc
  const f = pc.createDataChannel('fast', { ordered: false, maxRetransmits: 0 })
  const s = pc.createDataChannel('sure')

  const down = () => {
    if (peer !== pc) return
    closeDirect()
    report()
    if (++directFailures < DIRECT_MAX_FAILURES && ch === channel && accepted) {
      retryTimer = window.setTimeout(() => void startDirect(ch, report), DIRECT_RETRY_MS)
    }
  }
  const timeout = setTimeout(down, DIRECT_TIMEOUT_MS)
  const opened = () => {
    if (peer !== pc || f.readyState !== 'open' || s.readyState !== 'open') return
    clearTimeout(timeout)
    directFailures = 0
    fast = f
    sure = s
    report()
  }
  f.onopen = s.onopen = opened
  f.onclose = s.onclose = down
  pc.onconnectionstatechange = () => {
    if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') down()
  }

  // La oferta se manda con todos los candidatos ya reunidos (la PC no los recibe de a uno).
  await pc.setLocalDescription(await pc.createOffer())
  await iceGathered(pc, 2000)
  if (peer !== pc || ch !== channel) return
  void ch.send({ type: 'broadcast', event: 'rtc-offer', payload: { sdp: pc.localDescription!.sdp } })
}

function closeDirect() {
  clearTimeout(retryTimer)
  const pc = peer
  peer = fast = sure = null
  pc?.close()
}

export function join(room: Room, onState: (s: LinkState) => void) {
  leave()
  const ch = supabase.channel(`room:${room.id}`, {
    config: { private: true, presence: { key: 'guest' } },
  })
  channel = ch
  accepted = false
  seq = 0
  let hostHere = false
  const report = () =>
    onState(!accepted ? 'waiting' : !hostHere ? 'host-away' : isDirect() ? 'direct' : 'connected')

  ch.on('broadcast', { event: 'status' }, ({ payload }) => {
    // rejected: quien está en la PC no dio permiso. closed: la PC cerró la sala.
    if (payload?.state === 'rejected' || payload?.state === 'closed') {
      forget()
      onState(payload.state === 'rejected' ? 'rejected' : 'lost')
      return
    }
    const wasAccepted = accepted
    accepted = payload?.state === 'accepted'
    if (accepted && !wasAccepted) {
      directFailures = 0
      void startDirect(ch, report)
    }
    report()
  })
  ch.on('broadcast', { event: 'rtc-answer' }, ({ payload }) => {
    const pc = peer
    if (pc?.signalingState === 'have-local-offer' && typeof payload?.sdp === 'string') {
      pc.setRemoteDescription({ type: 'answer', sdp: payload.sdp }).catch(() => pc.close())
    }
  })
  ch.on('presence', { event: 'sync' }, () => {
    hostHere = 'host' in ch.presenceState()
    report()
  })

  ch.subscribe(async (status) => {
    if (ch !== channel) return
    if (status === 'SUBSCRIBED') {
      live = true
      await ch.track({ role: 'guest' })
      send({ event: 'hello', payload: {} })
      report()
      return
    }
    live = false
    onState('joining')
    if (status === 'CHANNEL_ERROR') {
      // Un error al unirse puede ser la red (supabase-js reintenta solo) o que la sala ya no
      // exista o no sea nuestra: en ese caso no hay nada a qué volver.
      const { data, error } = await supabase.from('rooms').select('id').eq('id', room.id).maybeSingle()
      if (ch === channel && !error && !data) {
        forget()
        onState('lost')
      }
    }
  })
}

export function send(msg: Outgoing) {
  if (!live || !channel) return
  if (msg.event === 'hello') {
    void channel.send({ type: 'broadcast', event: 'hello', payload: {} })
    return
  }
  // Sin permiso de la PC no se envía nada: la PC lo descartaría y gastaría cuota.
  if (!accepted) return
  if (isDirect()) {
    const dc = msg.event === 'move' || msg.event === 'scroll' ? fast! : sure!
    dc.send(JSON.stringify(msg))
    return
  }
  void channel.send({ type: 'broadcast', event: msg.event, payload: { ...msg.payload, n: ++seq } })
}

function leave() {
  closeDirect()
  if (channel) void supabase.removeChannel(channel)
  channel = null
  live = false
  accepted = false
}

function forget() {
  leave()
  saveRoom(null)
}

export const disconnect = forget
