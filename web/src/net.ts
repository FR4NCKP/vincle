import { createClient, type RealtimeChannel } from '@supabase/supabase-js'

// Valores públicos: la seguridad la dan las políticas RLS, no el secreto de esta clave.
const SUPABASE_URL = 'https://rmhuktsftptgrrzmqcon.supabase.co'
const SUPABASE_KEY = 'sb_publishable_2adm7NJ_11XgwuWZglo01A_7C5TI56i'

export const supabase = createClient(SUPABASE_URL, SUPABASE_KEY)

export type Room = { id: string; name: string }

/** waiting: unido, la PC aún no aprueba. host-away: aprobado, pero la PC no está en línea. */
export type LinkState = 'joining' | 'waiting' | 'connected' | 'host-away' | 'rejected' | 'lost'

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

export function join(room: Room, onState: (s: LinkState) => void) {
  leave()
  const ch = supabase.channel(`room:${room.id}`, {
    config: { private: true, presence: { key: 'guest' } },
  })
  channel = ch
  let accepted = false
  let hostHere = false
  const report = () => onState(!accepted ? 'waiting' : hostHere ? 'connected' : 'host-away')

  ch.on('broadcast', { event: 'status' }, ({ payload }) => {
    // rejected: quien está en la PC no dio permiso. closed: la PC cerró la sala.
    if (payload?.state === 'rejected' || payload?.state === 'closed') {
      forget()
      onState(payload.state === 'rejected' ? 'rejected' : 'lost')
      return
    }
    accepted = payload?.state === 'accepted'
    report()
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
  void channel.send({ type: 'broadcast', event: msg.event, payload: msg.payload })
}

function leave() {
  if (channel) void supabase.removeChannel(channel)
  channel = null
  live = false
}

function forget() {
  leave()
  saveRoom(null)
}

export const disconnect = forget
