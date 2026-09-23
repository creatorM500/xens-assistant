-- Email OAuth tokens por usuario
create table if not exists public.email_tokens (
    uid text primary key,
    provider text not null default 'gmail',
    access_token text not null,
    refresh_token text,
    expiry timestamptz,
    email text,
    updated_at timestamptz not null default now()
);
alter table public.email_tokens enable row level security;
-- solo service_role escribe; cliente no lee directo (via edge)
