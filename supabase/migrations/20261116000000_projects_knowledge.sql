-- Per-user project spaces and extracted document text for AINSLUP Web.
-- Files are parsed in the browser; only bounded plain text is stored here.
create table if not exists public.ainslup_projects (
    id uuid primary key default gen_random_uuid(),
    uid text not null,
    name text not null check (char_length(name) between 1 and 80),
    created_at timestamptz not null default now(),
    unique (uid, id)
);

create table if not exists public.ainslup_project_documents (
    id uuid primary key default gen_random_uuid(),
    uid text not null,
    project_id uuid not null,
    filename text not null check (char_length(filename) between 1 and 255),
    mime_type text not null default 'text/plain',
    content text not null check (char_length(content) between 1 and 300000),
    search_vector tsvector generated always as (
        to_tsvector('pg_catalog.simple'::regconfig, content)
    ) stored,
    created_at timestamptz not null default now(),
    constraint ainslup_project_documents_owner_project_fk
        foreign key (uid, project_id)
        references public.ainslup_projects (uid, id)
        on delete cascade
);

create index if not exists ainslup_projects_uid_created_idx
    on public.ainslup_projects (uid, created_at desc);
create index if not exists ainslup_project_documents_uid_project_idx
    on public.ainslup_project_documents (uid, project_id, created_at desc);
create index if not exists ainslup_project_documents_search_idx
    on public.ainslup_project_documents using gin (search_vector);

create or replace function public.enforce_ainslup_project_document_limit()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
declare
    document_count integer;
begin
    perform 1
      from public.ainslup_projects p
     where p.id = new.project_id
       and p.uid = (select auth.uid()::text)
     for update;
    if not found then
        raise exception 'project not found or access denied';
    end if;

    select count(*) into document_count
      from public.ainslup_project_documents d
     where d.uid = (select auth.uid()::text)
       and d.project_id = new.project_id;
    if document_count >= 20 then
        raise exception 'project document limit reached';
    end if;
    return new;
end;
$$;

revoke all on function public.enforce_ainslup_project_document_limit() from public, anon;
create trigger ainslup_project_document_limit
    before insert on public.ainslup_project_documents
    for each row execute function public.enforce_ainslup_project_document_limit();

alter table public.ainslup_projects enable row level security;
alter table public.ainslup_project_documents enable row level security;

revoke all on table public.ainslup_projects from public, anon;
revoke all on table public.ainslup_project_documents from public, anon;
grant select, insert, update, delete on table public.ainslup_projects to authenticated;
grant select, insert, update, delete on table public.ainslup_project_documents to authenticated;

drop policy if exists "users manage own ainslup projects" on public.ainslup_projects;
create policy "users manage own ainslup projects"
    on public.ainslup_projects
    for all
    to authenticated
    using (uid = (select auth.uid()::text))
    with check (uid = (select auth.uid()::text));

drop policy if exists "users manage own ainslup project documents" on public.ainslup_project_documents;
create policy "users manage own ainslup project documents"
    on public.ainslup_project_documents
    for all
    to authenticated
    using (
        uid = (select auth.uid()::text)
        and exists (
            select 1
            from public.ainslup_projects p
            where p.id = project_id and p.uid = (select auth.uid()::text)
        )
    )
    with check (
        uid = (select auth.uid()::text)
        and exists (
            select 1
            from public.ainslup_projects p
            where p.id = project_id and p.uid = (select auth.uid()::text)
        )
    );

-- Search only within the authenticated user's own project and return short
-- snippets, not entire documents. RLS remains active (SECURITY INVOKER).
create or replace function public.search_ainslup_project_documents(
    p_project_id uuid,
    p_query text,
    p_limit integer default 5
)
returns table (filename text, excerpt text)
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
    query_terms tsquery;
    query_text text;
begin
    if auth.uid() is null or p_project_id is null
       or p_query is null or char_length(p_query) > 500 then
        return;
    end if;

    select pg_catalog.string_agg(term, ' | ')
      into query_text
      from unnest(
          pg_catalog.regexp_split_to_array(
              pg_catalog.regexp_replace(pg_catalog.lower(p_query), '[^[:alnum:]_]+', ' ', 'g'),
              ' +'
          )
      ) as tokens(term)
     where term <> '';

    if query_text is null then
        return;
    end if;
    query_terms := pg_catalog.to_tsquery('pg_catalog.simple'::regconfig, query_text);

    return query
    select
        d.filename,
        pg_catalog.ts_headline(
            'pg_catalog.simple'::regconfig,
            d.content,
            query_terms,
            'MaxFragments=2,MaxWords=55,MinWords=18,FragmentDelimiter= … '
        ) as excerpt
    from public.ainslup_project_documents d
    where d.uid = (select auth.uid()::text)
      and d.project_id = p_project_id
      and d.search_vector @@ query_terms
    order by pg_catalog.ts_rank_cd(d.search_vector, query_terms) desc,
             d.created_at desc
    limit greatest(1, least(coalesce(p_limit, 5), 8));
end;
$$;

revoke all on function public.search_ainslup_project_documents(uuid, text, integer)
    from public, anon;
grant execute on function public.search_ainslup_project_documents(uuid, text, integer)
    to authenticated;
