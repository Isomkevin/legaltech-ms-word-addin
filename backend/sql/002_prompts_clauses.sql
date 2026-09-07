-- Additive prompt and clause libraries for the hosted Word add-in.
-- Apply after 001_init.sql in the same Supabase project.

create table if not exists public.prompts (
  id text primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  organization_id uuid not null references public.organizations (id) on delete cascade,
  title text not null,
  body text not null default '',
  scope text not null default 'private' check (scope in ('private', 'org')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists prompts_org_idx on public.prompts (organization_id, updated_at desc);

create table if not exists public.clauses (
  id text primary key,
  organization_id uuid not null references public.organizations (id) on delete cascade,
  user_id uuid references auth.users (id) on delete set null,
  name text not null,
  clause_type text not null default 'custom',
  content text not null default '',
  jurisdiction text not null default 'US',
  tone text not null default 'balanced',
  applicable_acts jsonb not null default '[]'::jsonb,
  tags jsonb not null default '[]'::jsonb,
  applicable_categories jsonb,
  source text not null default 'user',
  is_system boolean not null default false,
  created_at timestamptz not null default now()
);

create index if not exists clauses_org_idx on public.clauses (organization_id, created_at desc);

alter table public.prompts enable row level security;
alter table public.clauses enable row level security;

drop policy if exists prompts_member_select on public.prompts;
create policy prompts_member_select on public.prompts
  for select to authenticated
  using (
    organization_id in (select public.user_organization_ids())
    and (scope = 'org' or user_id = auth.uid())
  );

drop policy if exists clauses_member_select on public.clauses;
create policy clauses_member_select on public.clauses
  for select to authenticated
  using (organization_id in (select public.user_organization_ids()));
