-- HakiChain AI (Word add-in MVP)
-- Apply in the Supabase SQL editor of the SAME project the add-in uses.
-- The add-in lists orgs by reading organization_members + organizations under RLS.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- Profiles
-- ---------------------------------------------------------------------------
create table if not exists public.profiles (
  user_id uuid primary key references auth.users (id) on delete cascade,
  email text,
  full_name text,
  initialized boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

drop policy if exists profiles_self_select on public.profiles;
create policy profiles_self_select on public.profiles
  for select to authenticated
  using (user_id = auth.uid());

-- ---------------------------------------------------------------------------
-- Organizations + memberships
-- ---------------------------------------------------------------------------
create table if not exists public.organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  created_at timestamptz not null default now()
);

create table if not exists public.organization_members (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  role text not null check (role in ('owner', 'member')),
  status text not null default 'active' check (status in ('active', 'invited', 'removed')),
  created_at timestamptz not null default now(),
  unique (organization_id, user_id)
);

create index if not exists organization_members_user_idx
  on public.organization_members (user_id, status);

-- SECURITY DEFINER helper so org SELECT does not recurse into the members policy.
create or replace function public.user_organization_ids()
returns setof uuid
language sql
security definer
set search_path = public
stable
as $$
  select organization_id
  from public.organization_members
  where user_id = auth.uid()
    and status = 'active';
$$;

grant execute on function public.user_organization_ids() to authenticated;

alter table public.organizations enable row level security;
alter table public.organization_members enable row level security;

-- Members can read their own membership rows (no self-subquery, so no 42P17).
drop policy if exists org_members_self_select on public.organization_members;
create policy org_members_self_select on public.organization_members
  for select to authenticated
  using (user_id = auth.uid());

-- Members can read the org name of any org they belong to.
drop policy if exists orgs_member_select on public.organizations;
create policy orgs_member_select on public.organizations
  for select to authenticated
  using (id in (select public.user_organization_ids()));

-- ---------------------------------------------------------------------------
-- Playbooks, drafts, analyses, references (backend uses the service role)
-- ---------------------------------------------------------------------------
create table if not exists public.playbooks (
  id text primary key,
  organization_id uuid not null references public.organizations (id) on delete cascade,
  user_id uuid references auth.users (id) on delete set null,
  name text not null,
  contract_type text not null default 'custom',
  is_default boolean not null default false,
  positions jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists playbooks_org_idx on public.playbooks (organization_id, updated_at desc);

create table if not exists public.drafts (
  id text primary key,
  organization_id uuid not null references public.organizations (id) on delete cascade,
  user_id uuid references auth.users (id) on delete set null,
  title text not null,
  category text not null default 'custom',
  content jsonb,
  metadata jsonb not null default '{}'::jsonb,
  status text not null default 'draft',
  version integer not null default 1,
  source text,
  generation_status text,
  generation_progress jsonb,
  generation_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists drafts_org_idx on public.drafts (organization_id, updated_at desc);

create table if not exists public.analyses (
  id text primary key,
  organization_id uuid not null references public.organizations (id) on delete cascade,
  user_id uuid references auth.users (id) on delete set null,
  result jsonb,
  created_at timestamptz not null default now()
);

create index if not exists analyses_org_idx on public.analyses (organization_id);

create table if not exists public.draft_references (
  id text primary key,
  organization_id uuid not null references public.organizations (id) on delete cascade,
  user_id uuid references auth.users (id) on delete set null,
  file_name text not null,
  text text not null default '',
  word_count integer not null default 0,
  created_at timestamptz not null default now()
);

alter table public.playbooks enable row level security;
alter table public.drafts enable row level security;
alter table public.analyses enable row level security;
alter table public.draft_references enable row level security;

-- Authenticated users may read org-scoped rows. Writes go through the backend
-- (service role), which bypasses RLS.
drop policy if exists playbooks_member_select on public.playbooks;
create policy playbooks_member_select on public.playbooks
  for select to authenticated
  using (organization_id in (select public.user_organization_ids()));

drop policy if exists drafts_member_select on public.drafts;
create policy drafts_member_select on public.drafts
  for select to authenticated
  using (organization_id in (select public.user_organization_ids()));

drop policy if exists analyses_member_select on public.analyses;
create policy analyses_member_select on public.analyses
  for select to authenticated
  using (organization_id in (select public.user_organization_ids()));
