import { createClient, type RealtimeChannel } from '@supabase/supabase-js'
import { t } from './i18n'

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
  | { event: 'click'; payload: { button: 'left' | 'right' | 'middle' } }
  | { event: 'drag'; payload: { down: boolean } }
  | { event: 'text'; payload: { text: string } }
  | { event: 'key'; payload: { key: string; ctrl: boolean } }
  | { event: 'laser'; payload: { on: boolean } }
  | { event: 'laser_move'; payload: { x: number; y: number } }
  | { event: 'zoom'; payload: { steps: number } }
  | { event: 'gesture'; payload: { name: 'left' | 'right' | 'up' | 'down' } }

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
  if (error) throw new Error(t('err_session'))
}

export async function claim(pin: string): Promise<Room> {
  await ensureSession()
  const { data, error } = await supabase.rpc('claim_room', { p_pin: pin })
  if (error) {
    throw new Error(error.hint === 'rate_limited' ? t('err_rate') : t('err_net'))
  }
  const row = (data as { id: string; host_name: string }[] | null)?.[0]
  if (!row) throw new Error(t('err_pin'))
  const room = { id: row.id, name: row.host_name }
  saveRoom(room)
  return room
}

// ---------- Dispositivos de confianza ----------
// Si una PC "recuerda" este celular, el celular puede tomar su sala sin código, y la PC lo
// acepta sin preguntar. Lo decide la base de datos (tabla trusted_devices y sus funciones).

export type TrustedHost = { host_id: string; host_name: string }

async function currentUserId() {
  // Sin sesión guardada no puede haber confianza: no se crea un usuario solo para preguntar.
  const { data } = await supabase.auth.getSession()
  return data.session?.user.id ?? null
}

export async function trustedHosts(): Promise<TrustedHost[]> {
  const uid = await currentUserId()
  if (!uid) return []
  const { data, error } = await supabase.from('trusted_devices')
    .select('host_id, host_name').eq('guest_id', uid).order('created_at')
  return error ? [] : data ?? []
}

/** Toma la sala libre más reciente de una PC que confía en este celular, si la hay. */
export async function claimTrusted(): Promise<Room | null> {
  const { data, error } = await supabase.rpc('claim_trusted')
  const row = (data as { id: string; host_name: string }[] | null)?.[0]
  if (error || !row) return null
  const room = { id: row.id, name: row.host_name }
  saveRoom(room)
  return room
}

export async function forgetHost(hostId: string) {
  const uid = await currentUserId()
  if (uid) await supabase.from('trusted_devices').delete().eq('host_id', hostId).eq('guest_id', uid)
}

/** Nombre con el que la PC ve a este dispositivo, por ejemplo "Celular Android (SM-A515F)". */
async function describeDevice(): Promise<string> {
  const ua = navigator.userAgent
  const ipad = /iPad/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)
  if (ipad) return 'iPad'
  if (/iPhone|iPod/.test(ua)) return 'iPhone'
  const tablet = /Tablet/i.test(ua) || (/Android/i.test(ua) && !/Mobile/i.test(ua))
  const os = /Android/i.test(ua) ? 'Android' : /Windows/.test(ua) ? 'Windows' : /Mac/.test(ua) ? 'Mac' : /Linux/.test(ua) ? 'Linux' : ''
  let name = t(tablet ? 'dev_tablet' : 'dev_phone', { os }).trim()
  const uad = (navigator as Navigator & { userAgentData?: { getHighEntropyValues(h: string[]): Promise<{ model?: string }> } }).userAgentData
  try {
    const model = (await uad?.getHighEntropyValues(['model']))?.model
    if (model) name += ` (${model})`
  } catch {
    // Sin el modelo queda el nombre genérico.
  }
  return name
}

const deviceName = describeDevice()

// ---------- Latencia ----------
// Cada tanto se manda la hora a la PC y ella la devuelve: la diferencia es la ida y vuelta.
// Por Supabase se mide con menos frecuencia, porque cada mensaje cuenta para la cuota mensual.
//
// Lo que interesa es cuánto tarda el cursor, así que la cifra se toma mientras se usa el
// control: en reposo el celular apaga la antena Wi-Fi entre envíos para ahorrar batería y la
// ida y vuelta sale más alta de lo que se siente al mover el dedo. En reposo solo se mide
// para saber que la PC sigue respondiendo.

const PING_ACTIVE_MS = 500 // conexión directa, mientras se usa
const PING_IDLE_MS = 2000 // conexión directa, en reposo
const PING_CLOUD_MS = 5000
const ACTIVE_WINDOW_MS = 1500 // se considera "en uso" hasta 1,5 s después del último envío

let pingTimer = 0
let smoothRtt: number | null = null
let lastPong = 0
let lastActivity = -Infinity
let onLatency: (ms: number | null) => void = () => {}

const inUse = () => performance.now() - lastActivity < ACTIVE_WINDOW_MS

function gotPong(sent: unknown) {
  if (typeof sent !== 'number') return
  const rtt = performance.now() - sent
  if (rtt < 0 || rtt > 10_000) return
  lastPong = performance.now()
  // Una medición en reposo solo cuenta si todavía no hay ninguna.
  const tookInUse = lastActivity > sent - ACTIVE_WINDOW_MS
  if (!tookInUse && smoothRtt !== null) return
  smoothRtt = smoothRtt === null ? rtt : smoothRtt * 0.7 + rtt * 0.3
  onLatency(Math.round(smoothRtt))
}

function ping(ch: RealtimeChannel) {
  clearTimeout(pingTimer)
  const direct = isDirect()
  const every = !direct ? PING_CLOUD_MS : inUse() ? PING_ACTIVE_MS : PING_IDLE_MS
  pingTimer = window.setTimeout(() => ping(ch), every)
  if (ch !== channel || !live || !accepted || document.visibilityState !== 'visible') return
  // Sin respuesta (la PC no está o es una versión sin medición): no se muestra ningún valor.
  // Se mide contra el intervalo de reposo, porque por el canal rápido alguna puede perderse.
  if (performance.now() - lastPong > (direct ? PING_IDLE_MS : PING_CLOUD_MS) * 2.5) {
    smoothRtt = null
    onLatency(null)
  }
  const payload = { t: performance.now() }
  // Por el canal rápido: si se pierde un paquete no se espera su reenvío (como el cursor),
  // así la cifra no marca picos que el cursor no tiene.
  if (direct) fast!.send(JSON.stringify({ event: 'ping', payload }))
  else void ch.send({ type: 'broadcast', event: 'ping', payload })
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
  f.onmessage = s.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data)
      if (msg?.event === 'pong') gotPong(msg.payload?.t)
    } catch {
      // Mensaje que no se entiende: se ignora.
    }
  }
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

export function join(room: Room, onState: (s: LinkState) => void, latency: (ms: number | null) => void) {
  leave()
  onLatency = latency
  const ch = supabase.channel(`room:${room.id}`, {
    config: { private: true, presence: { key: 'guest' } },
  })
  channel = ch
  accepted = false
  seq = 0
  let hostHere = false
  let wasDirect = false
  const report = () => {
    // Al pasar de Supabase a directa (o al revés) la medición vieja ya no sirve.
    if (isDirect() !== wasDirect) {
      wasDirect = isDirect()
      smoothRtt = null
      lastPong = performance.now()
      ping(ch)
    }
    onState(!accepted ? 'waiting' : !hostHere ? 'host-away' : isDirect() ? 'direct' : 'connected')
  }

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
      lastPong = performance.now()
      ping(ch)
    }
    report()
  })
  ch.on('broadcast', { event: 'rtc-answer' }, ({ payload }) => {
    const pc = peer
    if (pc?.signalingState === 'have-local-offer' && typeof payload?.sdp === 'string') {
      pc.setRemoteDescription({ type: 'answer', sdp: payload.sdp }).catch(() => pc.close())
    }
  })
  ch.on('broadcast', { event: 'pong' }, ({ payload }) => gotPong(payload?.t))
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
    const ch = channel
    void deviceName.then((name) => ch.send({ type: 'broadcast', event: 'hello', payload: { name } }))
    return
  }
  // Sin permiso de la PC no se envía nada: la PC lo descartaría y gastaría cuota.
  if (!accepted) return
  // Al empezar a usar el control tras un rato quieto, se mide enseguida (con la antena ya
  // despierta) en vez de esperar al próximo turno de reposo.
  const wasIdle = !inUse()
  lastActivity = performance.now()
  if (wasIdle && isDirect()) {
    const ch = channel
    clearTimeout(pingTimer)
    pingTimer = window.setTimeout(() => ping(ch), 50)
  }
  if (isDirect()) {
    const continuous = msg.event === 'move' || msg.event === 'scroll' || msg.event === 'laser_move'
    const dc = continuous ? fast! : sure!
    dc.send(JSON.stringify(msg))
    return
  }
  void channel.send({ type: 'broadcast', event: msg.event, payload: { ...msg.payload, n: ++seq } })
}

function leave() {
  closeDirect()
  clearTimeout(pingTimer)
  smoothRtt = null
  onLatency(null)
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
