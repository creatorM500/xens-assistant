-- Conversaciones por cuenta (SaaS): cada fila es una conversación del usuario.
-- El motor local sincroniza por uid usando el token de Firebase del usuario
-- (RLS: solo se accede a las propias filas).
create table if not exists public.conversations (
    id text not null,
    uid text not null,
    title text not null default 'Sin título',
    data jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (uid, id)
);

alter table public.conversations enable row level security;

create policy "users read own conversations"
    on public.conversations for select
    to authenticated
    using (uid = auth.uid()::text);

create policy "users insert own conversations"
    on public.conversations for insert
    to authenticated
    with check (uid = auth.uid()::text);

create policy "users update own conversations"
    on public.conversations for update
    to authenticated
    using (uid = auth.uid()::text);

create policy "users delete own conversations"
    on public.conversations for delete
    to authenticated
    using (uid = auth.uid()::text);

create index if not exists conversations_uid_updated_idx
    on public.conversations (uid, updated_at desc);