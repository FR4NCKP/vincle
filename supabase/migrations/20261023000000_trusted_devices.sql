-- Dispositivos de confianza: la PC puede "recordar" un celular o tablet para que la próxima vez
-- se conecte sin código y sin pedir permiso.
create table public.trusted_devices (
  host_id uuid not null references auth.users on delete cascade,
  guest_id uuid not null references auth.users on delete cascade,
  host_name text not null check (char_length(host_name) between 1 and 64),
  guest_name text not null default 'Dispositivo' check (char_length(guest_name) between 1 and 64),
  created_at timestamptz not null default now(),
  primary key (host_id, guest_id)
);
create index trusted_devices_guest on public.trusted_devices (guest_id);

alter table public.trusted_devices enable row level security;

-- Cada lado ve y puede borrar (dejar de recordar) solo las relaciones en las que participa.
create policy "partes ven su confianza" on public.trusted_devices
  for select to authenticated
  using ((select auth.uid()) in (host_id, guest_id));

create policy "partes olvidan su confianza" on public.trusted_devices
  for delete to authenticated
  using ((select auth.uid()) in (host_id, guest_id));

-- La PC recuerda al dispositivo que está en su sala ahora mismo (solo el dueño de la sala).
create function public.trust_guest(p_room uuid, p_guest_name text)
returns void
language plpgsql security definer set search_path = ''
as $$
begin
  insert into public.trusted_devices (host_id, guest_id, host_name, guest_name)
  select r.host_id, r.guest_id, r.host_name, coalesce(nullif(left(btrim(p_guest_name), 64), ''), 'Dispositivo')
    from public.rooms r
   where r.id = p_room and r.host_id = (select auth.uid()) and r.guest_id is not null
  on conflict (host_id, guest_id) do update
    set host_name = excluded.host_name, guest_name = excluded.guest_name;
end;
$$;

-- El dispositivo de confianza toma, sin PIN, la sala libre más reciente de una PC que confía en él.
create function public.claim_trusted()
returns table (id uuid, host_name text)
language plpgsql security definer set search_path = ''
as $$
declare
  v_uid uuid := auth.uid();
begin
  if v_uid is null then
    raise exception 'not authenticated' using errcode = '28000';
  end if;
  return query
    update public.rooms r
       set guest_id = v_uid
     where r.id = (
       select r2.id
         from public.rooms r2
         join public.trusted_devices t on t.host_id = r2.host_id and t.guest_id = v_uid
        where r2.guest_id is null
        order by r2.created_at desc
        limit 1
     )
       and r.guest_id is null
    returning r.id, r.host_name;
end;
$$;

-- Para la PC: ¿el dispositivo que está en mi sala es de confianza?
create function public.room_guest_trusted(p_room uuid)
returns boolean
language sql stable security invoker set search_path = ''
as $$
  select exists (
    select 1
      from public.rooms r
      join public.trusted_devices t on t.host_id = r.host_id and t.guest_id = r.guest_id
     where r.id = p_room and r.host_id = (select auth.uid())
  );
$$;

revoke execute on function public.trust_guest(uuid, text) from public, anon;
revoke execute on function public.claim_trusted() from public, anon;
revoke execute on function public.room_guest_trusted(uuid) from public, anon;
grant execute on function public.trust_guest(uuid, text) to authenticated;
grant execute on function public.claim_trusted() to authenticated;
grant execute on function public.room_guest_trusted(uuid) to authenticated;
