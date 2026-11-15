-- Restrict privileged SECURITY DEFINER RPCs to the Edge Function service role.
revoke all on function public.bump_usage(uuid, text, bigint, bigint) from public, anon, authenticated;
grant execute on function public.bump_usage(uuid, text, bigint, bigint) to service_role;

-- Reserve a free chat atomically, so concurrent requests cannot bypass the cap.
create or replace function public.try_reserve_free_chat(
    p_license_id uuid,
    p_period text,
    p_max_chats integer
)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
    reserved_chats integer;
begin
    if p_license_id is null
       or p_period is null or p_period !~ '^[0-9]{4}-(0[1-9]|1[0-2])$'
       or p_max_chats is null or p_max_chats < 1 or p_max_chats > 1000000 then
        raise exception 'invalid free chat reservation';
    end if;

    insert into public.usage (license_id, period, chats)
    values (p_license_id, p_period, 1)
    on conflict (license_id, period) do update set
        chats = public.usage.chats + 1,
        updated_at = now()
    where public.usage.chats < p_max_chats
    returning chats into reserved_chats;
    return reserved_chats;
end;
$$;

revoke all on function public.try_reserve_free_chat(uuid, text, integer) from public, anon, authenticated;
grant execute on function public.try_reserve_free_chat(uuid, text, integer) to service_role;

-- Record upstream token usage without incrementing the chat counter a second time.
create or replace function public.record_usage_tokens(
    p_license_id uuid,
    p_period text,
    p_tokens_in bigint,
    p_tokens_out bigint
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
    if p_license_id is null
       or p_period is null or p_period !~ '^[0-9]{4}-(0[1-9]|1[0-2])$'
       or p_tokens_in is null or p_tokens_in < 0 or p_tokens_in > 1000000000
       or p_tokens_out is null or p_tokens_out < 0 or p_tokens_out > 1000000000 then
        raise exception 'invalid usage record';
    end if;

    insert into public.usage (license_id, period, chats, tokens_in, tokens_out)
    values (p_license_id, p_period, 0, p_tokens_in, p_tokens_out)
    on conflict (license_id, period) do update set
        tokens_in = public.usage.tokens_in + excluded.tokens_in,
        tokens_out = public.usage.tokens_out + excluded.tokens_out,
        updated_at = now();
end;
$$;

revoke all on function public.record_usage_tokens(uuid, text, bigint, bigint) from public, anon, authenticated;
grant execute on function public.record_usage_tokens(uuid, text, bigint, bigint) to service_role;

revoke all on function public.spend_user_credits(text, text, integer) from public, anon, authenticated;
grant execute on function public.spend_user_credits(text, text, integer) to service_role;

revoke all on function public.get_user_credits(text, text) from public, anon, authenticated;
grant execute on function public.get_user_credits(text, text) to service_role;

revoke all on function public.activate_license(text, text, text) from public, anon, authenticated;
grant execute on function public.activate_license(text, text, text) to service_role;

revoke all on function public.deactivate_license(text, text, text) from public, anon, authenticated;
grant execute on function public.deactivate_license(text, text, text) to service_role;

revoke all on function public.provision_free_license(text, text) from public, anon, authenticated;
grant execute on function public.provision_free_license(text, text) to service_role;

-- Atomically charge only when the account remains within its server-derived plan limit.
create or replace function public.try_spend_user_credits(
    p_uid text,
    p_period text,
    p_amount integer,
    p_limit integer
)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
    new_spent integer;
begin
    if p_uid is null or length(trim(p_uid)) = 0
       or p_period is null or p_period !~ '^[0-9]{4}-(0[1-9]|1[0-2])$'
       or p_amount is null or p_amount < 1 or p_amount > 1000000
       or p_limit is null or p_limit < 1 or p_limit > 10000000 then
        raise exception 'invalid credit charge';
    end if;
    if p_amount > p_limit then
        return null;
    end if;

    insert into public.user_credits (uid, period, spent)
    values (p_uid, p_period, p_amount)
    on conflict (uid, period) do update set
        spent = public.user_credits.spent + excluded.spent,
        updated_at = now()
    where public.user_credits.spent + excluded.spent <= p_limit
    returning spent into new_spent;

    return new_spent;
end;
$$;

revoke all on function public.try_spend_user_credits(text, text, integer, integer) from public, anon, authenticated;
grant execute on function public.try_spend_user_credits(text, text, integer, integer) to service_role;

-- Validate server-provided credit mutations even if a privileged caller is misused.
create or replace function public.spend_user_credits(p_uid text, p_period text, p_amount int)
returns int
language plpgsql
security definer
set search_path = ''
as $$
declare
    new_spent int;
begin
    if p_uid is null or length(trim(p_uid)) = 0 then
        raise exception 'uid required';
    end if;
    if p_period is null or p_period !~ '^[0-9]{4}-(0[1-9]|1[0-2])$' then
        raise exception 'invalid period';
    end if;
    if p_amount is null or p_amount < 1 or p_amount > 1000000 then
        raise exception 'invalid credit amount';
    end if;

    insert into public.user_credits (uid, period, spent)
    values (p_uid, p_period, p_amount)
    on conflict (uid, period) do update set
        spent = public.user_credits.spent + excluded.spent,
        updated_at = now()
    returning spent into new_spent;
    return new_spent;
end;
$$;

-- Reapply the restricted ACL after CREATE OR REPLACE.
revoke all on function public.spend_user_credits(text, text, integer) from public, anon, authenticated;
grant execute on function public.spend_user_credits(text, text, integer) to service_role;

create table if not exists public.provision_rate_limits (
    ip_hash text primary key check (ip_hash ~ '^[0-9a-f]{64}$'),
    window_started_at timestamptz not null default now(),
    attempts integer not null default 0 check (attempts >= 0)
);

alter table public.provision_rate_limits enable row level security;
revoke all on table public.provision_rate_limits from public, anon, authenticated;
grant all on table public.provision_rate_limits to service_role;

create or replace function public.take_provision_slot(
    p_ip_hash text,
    p_max_attempts integer,
    p_window_seconds integer
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
    current_attempts integer;
    current_window timestamptz;
begin
    if p_ip_hash is null or p_ip_hash !~ '^[0-9a-f]{64}$' then
        raise exception 'invalid IP fingerprint';
    end if;
    if p_max_attempts < 1 or p_max_attempts > 100 then
        raise exception 'invalid attempt limit';
    end if;
    if p_window_seconds < 60 or p_window_seconds > 604800 then
        raise exception 'invalid rate-limit window';
    end if;

    insert into public.provision_rate_limits (ip_hash, window_started_at, attempts)
    values (p_ip_hash, now(), 1)
    on conflict (ip_hash) do update set
        attempts = case
            when public.provision_rate_limits.window_started_at <= now() - (p_window_seconds * interval '1 second') then 1
            else public.provision_rate_limits.attempts + 1
        end,
        window_started_at = case
            when public.provision_rate_limits.window_started_at <= now() - (p_window_seconds * interval '1 second') then now()
            else public.provision_rate_limits.window_started_at
        end
    returning attempts, window_started_at into current_attempts, current_window;

    return current_attempts <= p_max_attempts;
end;
$$;

revoke all on function public.take_provision_slot(text, integer, integer) from public, anon, authenticated;
grant execute on function public.take_provision_slot(text, integer, integer) to service_role;
