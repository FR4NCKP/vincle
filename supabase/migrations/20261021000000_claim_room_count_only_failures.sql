-- El límite de intentos solo debe frenar a quien prueba PIN al azar: los aciertos no cuentan.
create or replace function public.claim_room(p_pin text)
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

  return query
    update public.rooms r
       set guest_id = v_uid
     where r.pin = p_pin
       and r.guest_id is null
       and r.expires_at > now()
       and r.host_id <> v_uid
    returning r.id, r.host_name;

  if not found then
    insert into public.claim_attempts (user_id) values (v_uid);
  end if;
end;
$$;
