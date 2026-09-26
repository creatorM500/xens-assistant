-- Base: tablas licenses/devices (faltaba en el historial; prod ya las tiene).
-- Reconstruido desde el esquema real de producción.
create extension if not exists pgcrypto;

create table if not exists public.licenses (
    id uuid primary key default gen_random_uuid(),
    key text not null,
    tier text not null default 'pro',
    email text default '',
    user_id uuid,
    created_at timestamptz default now(),
    expires_at timestamptz,
    max_activations int default 3,
    used_activations int default 0,
    revoked boolean default false,
    stripe_subscription_id text default '',
    stripe_customer_id text default ''
);

do $$
begin
    if not exists (select 1 from pg_constraint where conname = 'licenses_key_unique') then
        alter table public.licenses add constraint licenses_key_unique unique (key);
    end if;
    if not exists (select 1 from pg_constraint where conname = 'licenses_tier_check') then
        alter table public.licenses add constraint licenses_tier_check check (
            tier = any (array['free'::text, 'lite'::text, 'pro'::text, 'premium'::text, 'trial'::text, 'lifetime'::text])
        );
    end if;
end $$;

alter table public.licenses enable row level security;

create table if not exists public.devices (
    id uuid primary key default gen_random_uuid(),
    license_id uuid references public.licenses(id) on delete cascade,
    device_id text not null,
    machine_id text not null,
    activated_at timestamptz default now(),
    last_seen timestamptz default now()
);

alter table public.devices enable row level security;

create index if not exists idx_devices_license_id on public.devices(license_id);
create index if not exists idx_licenses_key on public.licenses(key);
