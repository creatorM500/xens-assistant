alter table public.conversations add column if not exists pinned boolean not null default false;
alter table public.conversations add column if not exists archived boolean not null default false;
create index if not exists conversations_uid_pinned_updated_idx on public.conversations (uid, pinned desc, updated_at desc);
