-- Uso mensual por licencia: chats y tokens acumulados (PK license_id+period).
create table if not exists public.usage (
    license_id uuid not null references public.licenses(id) on delete cascade,
    period text not null,
    chats int not null default 0,
    tokens_in bigint not null default 0,
    tokens_out bigint not null default 0,
    updated_at timestamptz not null default now(),
    primary key (license_id, period)
);

alter table public.usage enable row level security;

-- Incremento atómico (service_role la llama desde la Edge Function).
create or replace function public.bump_usage(p_license_id uuid, p_period text, p_tokens_in bigint, p_tokens_out bigint)
returns void
language sql
security definer
set search_path = ''
as $$
    insert into public.usage (license_id, period, chats, tokens_in, tokens_out)
    values (p_license_id, p_period, 1, p_tokens_in, p_tokens_out)
    on conflict (license_id, period) do update set
        chats = public.usage.chats + 1,
        tokens_in = public.usage.tokens_in + excluded.tokens_in,
        tokens_out = public.usage.tokens_out + excluded.tokens_out,
        updated_at = now();
$$;