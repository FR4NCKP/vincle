-- Sala de emparejamiento: la PC (host) la crea con un PIN; el celular (guest) la reclama.
create table public.rooms (
  id uuid primary key default gen_random_uuid(),
  pin text not null check (pin ~ '^[0-9]{6}$'),
  host_id uuid not null references auth.users on delete cascade,
  host_name text not null check (char_length(host_name) between 1 and 64),
  guest_id uuid references auth.users on delete set null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default now() + interval '2 minutes'
);
-- Un PIN solo puede estar vigente en una sala sin reclamar.
create unique index rooms_open_pin on public.rooms (pin) where guest_id is null;
create index rooms_host on public.rooms (host_id);
create index rooms_guest on public.rooms (guest_id);

alter table public.rooms enable row level security;

create policy "miembros leen su sala" on public.rooms
  for select to authenticated
  using ((select auth.uid()) in (host_id, guest_id));

create policy "host cierra su sala" on public.rooms
  for delete to authenticated
  using ((select auth.uid()) = host_id);

-- Intentos de reclamar un PIN, para frenar la fuerza bruta. Solo lo tocan las funciones.
create table public.claim_attempts (
  user_id uuid not null references auth.users on delete cascade,
  at timestamptz not null default now()
);
create index claim_attempts_user_at on public.claim_attempts (user_id, at);
alter table public.claim_attempts enable row level security;

create function public.create_room(p_host_name text)
returns table (id uuid, pin text, expires_at timestamptz)
language plpgsql security definer set search_path = ''
as $$
declare
  v_uid uuid := auth.uid();
  v_pin text;
begin
  if v_uid is null then
    raise exception 'not authenticated' using errcode = '28000';
  end if;

  -- Una sala por PC; se limpian PIN vencidos y salas viejas.
  delete from public.rooms r where r.host_id = v_uid;
  delete from public.rooms r
    where (r.guest_id is null and r.expires_at < now())
       or r.created_at < now() - interval '1 day';
  delete from public.claim_attempts a where a.at < now() - interval '1 hour';

  loop
    v_pin := lpad(((('x' || encode(extensions.gen_random_bytes(4), 'hex'))::bit(32)::bigint) % 1000000)::text, 6, '0');
    begin
      return query
        insert into public.rooms as r (pin, host_id, host_name)
        values (v_pin, v_uid, left(btrim(p_host_name), 64))
        returning r.id, r.pin, r.expires_at;
      return;
    exception when unique_violation then
      -- PIN ya en uso; se prueba otro.
    end;
  end loop;
end;
$$;

create function public.claim_room(p_pin text)
returns table (id uuid, host_name text)
language plpgsql security definer set search_path = ''
as $$
declare
  v_uid uuid := auth.uid();
begin
  if v_uid is null then
    raise exception 'not authenticated' using errcode = '28000';
  end if;

  if (select count(*) from public.claim_attempts a
      where a.user_id = v_uid and a.at > now() - interval '10 minutes') >= 10 then
    raise exception 'too many attempts' using errcode = 'P0001', hint = 'rate_limited';
  end if;
  insert into public.claim_attempts (user_id) values (v_uid);

  return query
    update public.rooms r
       set guest_id = v_uid
     where r.pin = p_pin
       and r.guest_id is null
       and r.expires_at > now()
       and r.host_id <> v_uid
    returning r.id, r.host_name;
end;
$$;

revoke execute on function public.create_room(text) from public, anon;
revoke execute on function public.claim_room(text) from public, anon;
grant execute on function public.create_room(text) to authenticated;
grant execute on function public.claim_room(text) to authenticated;

-- Canales privados "room:<id>": solo el host y el guest de esa sala pueden unirse,
-- enviar y recibir Broadcast y Presence.
create policy "miembros de la sala reciben" on realtime.messages
  for select to authenticated
  using (
    realtime.messages.extension in ('broadcast', 'presence')
    and exists (
      select 1 from public.rooms r
      where 'room:' || r.id::text = (select realtime.topic())
        and (select auth.uid()) in (r.host_id, r.guest_id)
    )
  );

create policy "miembros de la sala envian" on realtime.messages
  for insert to authenticated
  with check (
    realtime.messages.extension in ('broadcast', 'presence')
    and exists (
      select 1 from public.rooms r
      where 'room:' || r.id::text = (select realtime.topic())
        and (select auth.uid()) in (r.host_id, r.guest_id)
    )
  );
