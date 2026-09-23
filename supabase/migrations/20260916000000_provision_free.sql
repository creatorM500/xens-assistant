-- Auto-provisión del plan Free: el consumidor abre XENS y funciona sin
-- serial ni API keys. Una licencia free (lifetime) por máquina/dispositivo.
-- Amplía el check de tiers con 'lite'.
ALTER TABLE public.licenses DROP CONSTRAINT IF EXISTS licenses_tier_check;
ALTER TABLE public.licenses ADD CONSTRAINT licenses_tier_check CHECK (
    tier = ANY (ARRAY['free'::text, 'lite'::text, 'pro'::text, 'premium'::text, 'trial'::text, 'lifetime'::text])
);

CREATE OR REPLACE FUNCTION public.provision_free_license(p_device_id text, p_machine_id text)
RETURNS json
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
declare
    v_license public.licenses;
    v_device public.devices;
begin
    if coalesce(p_device_id, '') = '' and coalesce(p_machine_id, '') = '' then
        return json_build_object('error', 'device required');
    end if;

    -- ¿Esta máquina ya tiene una licencia (cualquiera)? Reutilizarla.
    select d.* into v_device from public.devices d
        where (p_device_id <> '' and d.device_id = p_device_id)
           or (p_machine_id <> '' and d.machine_id = p_machine_id)
        order by d.last_seen desc nulls last limit 1;
    if found then
        select * into v_license from public.licenses where id = v_device.license_id limit 1;
        if found and not v_license.revoked
           and (v_license.expires_at is null or v_license.expires_at > now()) then
            update public.devices set last_seen = now() where id = v_device.id;
            return json_build_object('status', 'ok', 'tier', v_license.tier,
                'key', v_license.key,
                'expires_at', extract(epoch from v_license.expires_at));
        end if;
    end if;

    -- Crear licencia free lifetime atada a esta máquina (1 sola vez).
    insert into public.licenses (key, tier, expires_at, max_activations)
        values ('AUTO-FREE-' || upper(substring(md5(coalesce(p_machine_id, '') || '|' || coalesce(p_device_id, '')) from 1 for 12)),
                'free', NULL, 1)
        on conflict (key) do nothing
        returning * into v_license;
    if not found then
        select * into v_license from public.licenses
            where key = 'AUTO-FREE-' || upper(substring(md5(coalesce(p_machine_id, '') || '|' || coalesce(p_device_id, '')) from 1 for 12))
            limit 1;
    end if;

    insert into public.devices (license_id, device_id, machine_id)
        values (v_license.id, nullif(p_device_id, ''), nullif(p_machine_id, ''))
        on conflict do nothing;
    update public.licenses set used_activations =
        (select count(*)::int from public.devices where license_id = v_license.id)
        where id = v_license.id;

    return json_build_object('status', 'ok', 'tier', v_license.tier,
        'key', v_license.key, 'expires_at', null);
end;
$function$;
