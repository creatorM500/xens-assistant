-- Fix: recreate activate_license con SET search_path='' y UTF-8 correcto;
-- usado_activations ahora se recalcula del conteo real de devices (auto-consistente).
CREATE OR REPLACE FUNCTION public.activate_license(p_key text, p_device_id text, p_machine_id text)
 RETURNS json
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path = ''
AS $function$
declare
    v_license public.licenses;
    v_device public.devices;
begin
    select * into v_license from public.licenses where key = p_key limit 1;
    if not found then
        return json_build_object('error', 'Clave no encontrada');
    end if;
    if v_license.revoked then
        return json_build_object('error', 'Clave revocada');
    end if;
    if v_license.expires_at is not null and v_license.expires_at < now() then
        return json_build_object('error', 'Clave expirada');
    end if;

    select * into v_device from public.devices
        where license_id = v_license.id
          and (device_id = p_device_id or machine_id = p_machine_id)
        limit 1;

    if found then
        update public.devices set last_seen = now() where id = v_device.id;
        return json_build_object('status', 'ok', 'tier', v_license.tier,
            'expires_at', extract(epoch from v_license.expires_at));
    end if;

    if v_license.used_activations >= v_license.max_activations then
        return json_build_object('error', 'Máximo de activaciones alcanzado');
    end if;

    insert into public.devices (license_id, device_id, machine_id)
        values (v_license.id, p_device_id, p_machine_id);
    update public.licenses set used_activations =
        (select count(*)::int from public.devices where license_id = v_license.id)
        where id = v_license.id;

    return json_build_object('status', 'ok', 'tier', v_license.tier,
        'expires_at', extract(epoch from v_license.expires_at),
        'days_remaining', case when v_license.expires_at is not null
            then greatest(0, (extract(epoch from v_license.expires_at - now()) / 86400)::int)
            else 36500 end);
end;
$function$;