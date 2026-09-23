-- Suscripciones por cuenta (SaaS): plan activo del usuario.
-- La Edge Function paypal-webhook hace upsert; el motor local lee la
-- fila del usuario autenticado para asignar el tier.
create table if not exists public.subscriptions (
    uid text primary key,
    plan text not null default 'free',
    status text not null default 'active',
    current_period_end timestamptz,
    updated_at timestamptz not null default now()
);

alter table public.subscriptions enable row level security;

create policy "users read own subscription"
    on public.subscriptions for select
    to authenticated
    using (uid = auth.uid()::text);

-- El upsert del webhook lo hace la Edge Function con service_role (bypassa RLS).