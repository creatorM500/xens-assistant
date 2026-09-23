-- Créditos por usuario (SaaS): fuente server-side anti-manipulación.
-- Cada fila es el gasto mensual de un uid (Firebase) o licencia online.
-- El local queda como cache; el servidor es la verdad.
create table if not exists public.user_credits (
    uid text not null,
    period text not null, -- YYYY-MM
    spent int not null default 0,
    updated_at timestamptz not null default now(),
    primary key (uid, period)
);

alter table public.user_credits enable row level security;

-- Lectura/escritura solo vía service_role (edge function); no policy para anon.
-- Si en el futuro se quiere acceso directo con JWT, añadir:
-- create policy "users read own credits" on public.user_credits for select to authenticated using (uid = auth.uid()::text);

-- Función atómica para gastar créditos (similar a bump_usage pero por uid)
create or replace function public.spend_user_credits(p_uid text, p_period text, p_amount int)
returns int
language plpgsql
security definer
set search_path = ''
as $$
declare
    new_spent int;
begin
    insert into public.user_credits (uid, period, spent)
    values (p_uid, p_period, p_amount)
    on conflict (uid, period) do update set
        spent = public.user_credits.spent + p_amount,
        updated_at = now()
    returning spent into new_spent;
    return new_spent;
end;
$$;

-- Función para consultar gasto actual
create or replace function public.get_user_credits(p_uid text, p_period text)
returns int
language sql
security definer
set search_path = ''
as $$
    select coalesce((select spent from public.user_credits where uid = p_uid and period = p_period), 0);
$$;
