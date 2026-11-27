-- Dental Desk: the cloud of the stock (Supabase, project «dental-desk-stock»). The final schema: the migration
-- «dd_stock_cloud» with the corrected dd.set_staff (migration «dd_set_staff_pin_change» and its fix).
-- Laptops push their stock rows (JSON with versions, as replica.py makes them); phones read them and do stock operations
-- through the edge function «stock» (functions/stock/index.ts), which checks every right.
-- Everything lives in the schema dd, which the Data API does not expose; only the edge function (its database role) reads it.
create schema if not exists dd;
revoke all on schema dd from public, anon, authenticated;

create table if not exists dd.tenants(
  id text primary key,
  name text not null default '',
  join_hash text unique,
  phone_code text unique,
  tz_offset int not null default 180,
  seq bigint not null default 0,
  status text not null default 'active',
  created_at timestamptz not null default now());

create table if not exists dd.devices(
  id text primary key,
  tenant_id text not null references dd.tenants(id) on delete cascade,
  kind text not null check (kind in ('laptop', 'phone')),
  name text not null default '',
  token_hash text unique,
  version text not null default '',
  created_at timestamptz not null default now(),
  last_seen timestamptz,
  revoked boolean not null default false,
  fails int not null default 0,
  locked_until timestamptz);
create index if not exists devices_tenant on dd.devices(tenant_id);

create table if not exists dd.rows(
  tenant_id text not null references dd.tenants(id) on delete cascade,
  tbl text not null,
  k text not null,
  ver text not null,
  vv jsonb,
  data jsonb,
  pbase jsonb,
  pvv jsonb,
  origin text not null default '',
  device text not null default '',
  seq bigint not null,
  primary key(tenant_id, tbl, k));
create index if not exists rows_seq on dd.rows(tenant_id, seq);
create index if not exists rows_moves_mat on dd.rows(tenant_id, (data->>'material_id')) where tbl in ('stock_moves', 'stock_lots');

create table if not exists dd.staff(
  tenant_id text not null references dd.tenants(id) on delete cascade,
  login text not null,
  name text not null default '',
  role text not null default '',
  role_title text not null default '',
  perms jsonb not null default '[]',
  pin_hash text,
  pin_at text,
  fails int not null default 0,
  locked_until timestamptz,
  updated_at timestamptz not null default now(),
  primary key(tenant_id, login));

create table if not exists dd.sessions(
  token_hash text primary key,
  tenant_id text not null references dd.tenants(id) on delete cascade,
  device_id text not null,
  login text not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  last_seen timestamptz);
create index if not exists sessions_tenant on dd.sessions(tenant_id, login);

create table if not exists dd.ops(
  tenant_id text not null references dd.tenants(id) on delete cascade,
  id text not null,
  login text not null,
  kind text not null,
  at timestamptz not null default now(),
  result jsonb,
  primary key(tenant_id, id));

create table if not exists dd.ip_fails(
  ip text primary key,
  n int not null default 0,
  since timestamptz not null default now());

alter table dd.tenants enable row level security;
alter table dd.devices enable row level security;
alter table dd.rows enable row level security;
alter table dd.staff enable row level security;
alter table dd.sessions enable row level security;
alter table dd.ops enable row level security;
alter table dd.ip_fails enable row level security;
revoke all on all tables in schema dd from public, anon, authenticated;

-- A code people type: 32 letters and digits without the look-alikes (I, O, 0, 1); 256 % 32 = 0, so every one is equally likely.
create or replace function dd.rand_code(n int) returns text language plpgsql volatile set search_path = '' as $$
declare a text := 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; b bytea := extensions.gen_random_bytes(n); r text := ''; i int;
begin
  for i in 0..n - 1 loop r := r || substr(a, (get_byte(b, i) % 32) + 1, 1); end loop;
  return r;
end $$;

-- The provider makes a clinic: the code for its laptops (typed once in the program) and the clinic code for phones.
create or replace function dd.create_tenant(p_name text) returns jsonb language plpgsql volatile set search_path = '' as $$
declare t text := encode(extensions.gen_random_bytes(12), 'hex'); raw text := dd.rand_code(16); phone text := dd.rand_code(8);
begin
  insert into dd.tenants(id, name, join_hash, phone_code)
  values (t, coalesce(p_name, ''), encode(extensions.digest('DDS' || raw, 'sha256'), 'hex'), phone);
  return jsonb_build_object('tenant', t, 'laptop_code',
    'DDS-' || substr(raw, 1, 4) || '-' || substr(raw, 5, 4) || '-' || substr(raw, 9, 4) || '-' || substr(raw, 13, 4),
    'phone_code', substr(phone, 1, 4) || '-' || substr(phone, 5, 4));
end $$;

-- A laptop's versions: each is taken only when the cloud still has the version it was made from (otherwise the laptop
-- pulls, merges and sends again); one the cloud already has counts as taken. One growing number per clinic, given under
-- the clinic's row lock, so a pull never skips a row committed later with a smaller number.
create or replace function dd.push(p_tenant text, p_device text, p_changes jsonb) returns jsonb
language plpgsql volatile set search_path = '' as $$
declare ch jsonb; s bigint; cur text; had boolean; acc jsonb := '[]'; rej jsonb := '[]';
begin
  select seq into s from dd.tenants where id = p_tenant and status = 'active' for update;
  if not found then raise exception 'tenant'; end if;
  for ch in select value from jsonb_array_elements(p_changes) loop
    select ver into cur from dd.rows where tenant_id = p_tenant and tbl = ch->>'t' and k = ch->>'k';
    had := found;
    if had and cur = ch->>'ver' then
      acc := acc || jsonb_build_array(jsonb_build_array(ch->>'t', ch->>'k'));
      continue;
    end if;
    if (case when had then cur end) is distinct from (ch->>'base') then
      rej := rej || jsonb_build_array(jsonb_build_object('t', ch->>'t', 'k', ch->>'k', 'reason', 'conflict'));
      continue;
    end if;
    s := s + 1;
    insert into dd.rows(tenant_id, tbl, k, ver, vv, data, pbase, pvv, origin, device, seq)
    values (p_tenant, ch->>'t', ch->>'k', ch->>'ver', ch->'vv', nullif(ch->'row', 'null'::jsonb), nullif(ch->'pbase', 'null'::jsonb),
            nullif(ch->'pvv', 'null'::jsonb), coalesce(ch->>'origin', ''), p_device, s)
    on conflict (tenant_id, tbl, k) do update set ver = excluded.ver, vv = excluded.vv, data = excluded.data,
      pbase = excluded.pbase, pvv = excluded.pvv, origin = coalesce(nullif(dd.rows.origin, ''), excluded.origin),
      device = excluded.device, seq = excluded.seq;
    acc := acc || jsonb_build_array(jsonb_build_array(ch->>'t', ch->>'k'));
  end loop;
  update dd.tenants set seq = s where id = p_tenant;
  return jsonb_build_object('accepted', acc, 'rejected', rej, 'seq', s);
end $$;

-- Rows changed after `since`, oldest first.
create or replace function dd.pull(p_tenant text, p_since bigint, p_limit int) returns jsonb
language sql stable set search_path = '' as $$
  select jsonb_build_object(
    'rows', coalesce((select jsonb_agg(jsonb_build_object('t', x.tbl, 'k', x.k, 'ver', x.ver, 'vv', x.vv, 'row', x.data,
                                                         'pbase', x.pbase, 'pvv', x.pvv, 'origin', x.origin, 'seq', x.seq) order by x.seq)
                      from (select * from dd.rows where tenant_id = p_tenant and seq > p_since order by seq
                            limit greatest(1, least(p_limit, 1000))) x), '[]'::jsonb),
    'seq', (select seq from dd.tenants where id = p_tenant));
$$;

-- What a phone's operation writes: new versions made here, on behalf of the phone (`p_node`). Each item: {t, k, row (the
-- whole new row, or null to delete), expect (optional: the version the operation read — another change meanwhile refuses
-- the whole operation)}. The version vector goes on from the cloud's one, so the laptops see it as newer (or, if one of
-- them changed the same row meanwhile, as a change to merge field by field).
create or replace function dd.write(p_tenant text, p_node text, p_device text, p_items jsonb) returns jsonb
language plpgsql volatile set search_path = '' as $$
declare it jsonb; s bigint; cur record; had boolean; ms bigint := (extract(epoch from clock_timestamp()) * 1000)::bigint;
        vv jsonb; n bigint; ver text; out jsonb := '[]';
begin
  select seq into s from dd.tenants where id = p_tenant and status = 'active' for update;
  if not found then raise exception 'tenant'; end if;
  for it in select value from jsonb_array_elements(p_items) loop
    select r.ver, r.vv, r.data, r.origin into cur from dd.rows r where r.tenant_id = p_tenant and r.tbl = it->>'t' and r.k = it->>'k';
    had := found;
    if it ? 'expect' and (case when had then cur.ver end) is distinct from (it->>'expect') then
      raise exception 'changed:%:%', it->>'t', it->>'k';
    end if;
    vv := coalesce(case when had then cur.vv end, '{}'::jsonb);
    n := greatest(coalesce((vv->>p_node)::bigint, 0) + 1, ms);
    vv := vv || jsonb_build_object(p_node, n);
    ver := lpad(n::text, 15, '0') || '.' || p_node || '.' || substr(md5(random()::text), 1, 6);
    s := s + 1;
    insert into dd.rows(tenant_id, tbl, k, ver, vv, data, pbase, pvv, origin, device, seq)
    values (p_tenant, it->>'t', it->>'k', ver, vv, nullif(it->'row', 'null'::jsonb),
            case when had then cur.data end, case when had then cur.vv end, case when had then cur.origin else p_node end, p_device, s)
    on conflict (tenant_id, tbl, k) do update set ver = excluded.ver, vv = excluded.vv, data = excluded.data,
      pbase = excluded.pbase, pvv = excluded.pvv, device = excluded.device, seq = excluded.seq;
    out := out || jsonb_build_array(jsonb_build_object('t', it->>'t', 'k', it->>'k', 'ver', ver));
  end loop;
  update dd.tenants set seq = s where id = p_tenant;
  return jsonb_build_object('written', out, 'seq', s);
end $$;

-- The staff a phone may sign in as (sent by the laptops: who has a phone PIN and a right of the stock). A PIN changed or
-- taken away ends that person's sessions on every phone; people no longer in the list go, with their sessions.
create or replace function dd.set_staff(p_tenant text, p_staff jsonb) returns int
language plpgsql volatile set search_path = '' as $$
declare u jsonb; n int := 0; old text; had boolean;
begin
  for u in select value from jsonb_array_elements(p_staff) loop
    select pin_hash into old from dd.staff where tenant_id = p_tenant and login = u->>'login';
    had := found;
    if had and old is distinct from (u->>'pin_hash') then
      delete from dd.sessions where tenant_id = p_tenant and login = u->>'login';
    end if;
    insert into dd.staff(tenant_id, login, name, role, role_title, perms, pin_hash, pin_at, updated_at)
    values (p_tenant, u->>'login', coalesce(u->>'name', ''), coalesce(u->>'role', ''), coalesce(u->>'role_title', ''),
            coalesce(u->'perms', '[]'::jsonb), u->>'pin_hash', u->>'pin_at', now())
    on conflict (tenant_id, login) do update set name = excluded.name, role = excluded.role, role_title = excluded.role_title,
      perms = excluded.perms, updated_at = now(),
      fails = case when dd.staff.pin_hash is distinct from excluded.pin_hash then 0 else dd.staff.fails end,
      locked_until = case when dd.staff.pin_hash is distinct from excluded.pin_hash then null else dd.staff.locked_until end,
      pin_hash = excluded.pin_hash, pin_at = excluded.pin_at;
    n := n + 1;
  end loop;
  delete from dd.staff where tenant_id = p_tenant
    and login not in (select value->>'login' from jsonb_array_elements(p_staff));
  delete from dd.sessions s where s.tenant_id = p_tenant
    and not exists (select 1 from dd.staff st where st.tenant_id = s.tenant_id and st.login = s.login and st.pin_hash is not null);
  return n;
end $$;

revoke all on all functions in schema dd from public, anon, authenticated;
