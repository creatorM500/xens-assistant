-- Nuevo: deactivate_license libera un slot de dispositivo (por device_id o machine_id)
-- y recalcula used_activations.
CREATE OR REPLACE FUNCTION public.deactivate_license(
    p_key text,
    p_device_id text default '',
    p_machine_id text default ''
)
 RETURNS json
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path = ''
AS $function$
declare
    v_license public.licenses;
    v_target_id uuid;
begin
    select * into v_license from public.licenses where key = p_key limit 1;
    if not found then
        return json_build_object('error', 'Clave no encontrada');
    end if;

    if p_device_id <> '' then
        select id into v_target_id from public.devices
            where license_id = v_license.id and device_id = p_device_id limit 1;
    else
        select id into v_target_id from public.devices
            where license_id = v_license.id and machine_id = p_machine_id limit 1;
    end if;

    if v_target_id is null then
        return json_build_object('error', 'Dispositivo no encontrado');
    end if;

    delete from public.devices where id = v_target_id;
    update public.licenses set used_activations =
        (select count(*)::int from public.devices where license_id = v_license.id)
        where id = v_license.id;

    return json_build_object('status', 'ok', 'device_removed', v_target_id,
        'used_activations', (select used_activations from public.licenses where id = v_license.id));
end;
$function$;

-- Índice para búsquedas por machine_id en reactivaciones.
CREATE INDEX IF NOT EXISTS idx_devices_machine_id ON public.devices(machine_id);