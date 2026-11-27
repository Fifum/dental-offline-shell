// Dental Desk — the cloud of the stock (Supabase edge function «stock»).
//
// Laptops of a clinic push their stock and equipment rows here (JSON with the same versions as between the computers of the
// clinic, see app/replica.py) and pull what others changed. Rows of patients never come here: the laptops leave `patient_id`
// out, and this function drops it again if one slips through. Phones of the staff sign in with the clinic code (once) and a
// personal 6-digit PIN (its hash comes from the laptops), read the rows their position may see and do stock operations,
// which this function checks against the rights of the position and writes as new versions of the rows.
//
// Laptop:  POST /v1/join {code, name, version, tz} · /v1/status · /v1/push {changes} · /v1/pull {since} · /v1/staff · /v1/leave
//          (header X-DD-Token: the laptop's token)
// Phone:   POST /p/hello {code, name} → device token · /p/login {login, pin} (X-DD-Device) → session ·
//          /p/me · /p/pull {since} · /p/op {id, kind, …} · /p/logout (X-DD-Session)
import postgres from "npm:postgres@3.4.5";

const sql = postgres(Deno.env.get("SUPABASE_DB_URL")!, { prepare: false, max: 3, idle_timeout: 20, connect_timeout: 10 });

const API = 1;
const TABLES = ["materials", "suppliers", "stock_locations", "stock_docs", "stock_moves", "stock_lots", "stock_settings",
  "equipment", "equipment_events", "equipment_docs", "stock_requests", "stock_approvals"];
const STOCK_T = new Set(["materials", "suppliers", "stock_locations", "stock_docs", "stock_moves", "stock_lots", "stock_settings",
  "stock_requests", "stock_approvals"]);
const EQUIP_T = new Set(["equipment", "equipment_events", "equipment_docs", "stock_locations", "stock_settings"]);
const EQ_MONEY = ["price", "salvage", "market_value", "replace_cost", "reserve_monthly", "disposal_amount", "residual"];
const PHONE_PERMS = ["stock_view", "stock_ops", "stock_edit", "stock_approve", "equipment", "accounting"];
const MAX_PUSH = 500;
const PIN_FAILS = 5;
const LOCK_MIN = 15;
const SESSION_H = 12;
const MAIN = "Основной склад";

// ------------------------------------------------------------------------------------------------------------- helpers --
class E extends Error {
  constructor(msg: string, public code = 400) { super(msg); }
}

const ORIGINS = [/^https:\/\/dental-desk-stock(-[a-z0-9-]+)?\.vercel\.app$/, /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/];

function cors(req: Request): Record<string, string> {
  const o = req.headers.get("origin") || "";
  const h: Record<string, string> = { "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "content-type, x-dd-token, x-dd-device, x-dd-session", "Access-Control-Max-Age": "86400",
    "Vary": "Origin" };
  if (ORIGINS.some((r) => r.test(o))) h["Access-Control-Allow-Origin"] = o;
  return h;
}

function json(req: Request, obj: unknown, code = 200) {
  return new Response(JSON.stringify(obj), { status: code,
    headers: { ...cors(req), "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });
}

const hex = (b: ArrayBuffer | Uint8Array) => [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("");
const sha = async (s: string) => hex(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s)));
const rnd = (n: number) => { const b = new Uint8Array(n); crypto.getRandomValues(b); return b; };
const token = () => btoa(String.fromCharCode(...rnd(32))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const hid = (n: number) => hex(rnd(n));
const norm = (code: unknown) => String(code ?? "").toUpperCase().replace(/[^A-Z0-9]/g, "");
const clean = (v: unknown, n = 300) => String(v ?? "").trim().slice(0, n);
const r3 = (x: number) => Math.round(x * 1000) / 1000;
const r2 = (x: number) => Math.round(x * 100) / 100;
const ks = (key: unknown[]) => JSON.stringify(key);

function num(v: unknown, name = "Количество"): number {
  if (v === null || v === undefined || v === "") return 0;
  const x = Number(String(v).replace(",", ".").replace(/\s/g, ""));
  if (!Number.isFinite(x)) throw new E(`${name}: введите число`);
  return r3(x);
}

function day(v: unknown, name = "Дата"): string {
  const s = String(v ?? "").trim();
  if (!s) return "";
  let m, y = 0, mo = 0, d = 0;
  if ((m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/))) [y, mo, d] = [+m[1], +m[2], +m[3]];
  else if ((m = s.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/))) [y, mo, d] = [+m[3], +m[2], +m[1]];
  else if ((m = s.match(/^(\d{4})-(\d{1,2})$/))) { [y, mo] = [+m[1], +m[2]]; d = new Date(Date.UTC(y, mo, 0)).getUTCDate(); }
  else if ((m = s.match(/^(\d{1,2})\.(\d{4})$/))) { [y, mo] = [+m[2], +m[1]]; d = new Date(Date.UTC(y, mo, 0)).getUTCDate(); }
  else throw new E(`${name}: укажите дату, например 31.12.2027`);
  const t = new Date(Date.UTC(y, mo - 1, d));
  if (mo < 1 || mo > 12 || t.getUTCDate() !== d) throw new E(`${name}: такой даты нет`);
  return t.toISOString().slice(0, 10);
}

async function checkPin(pin: string, stored: string | null): Promise<boolean> {
  const p = String(stored || "").split("$");
  if (p.length !== 4 || p[0] !== "pbkdf2") return false;
  const salt = new Uint8Array(p[2].match(/../g)!.map((x) => parseInt(x, 16)));
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(pin), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt, iterations: Number(p[1]) }, key, 256);
  const got = hex(bits);
  let diff = got.length ^ p[3].length;
  for (let i = 0; i < got.length && i < p[3].length; i++) diff |= got.charCodeAt(i) ^ p[3].charCodeAt(i);
  return diff === 0;
}

// Rows of patients never stay here: `patient_id`/`patient_name` are dropped (in stock_approvals.payload they are emptied —
// the laptops read the keys).
function hide(t: string, row: any): any {
  if (!row || typeof row !== "object") return row ?? null;
  const r = { ...row };
  delete r.patient_id;
  delete r.patient_name;
  if (t === "stock_approvals" && typeof r.payload === "string") {
    try {
      const p = JSON.parse(r.payload);
      if (p && typeof p === "object" && (p.patient_id || p.patient_name)) {
        p.patient_id = ""; p.patient_name = "";
        r.payload = JSON.stringify(p);
      }
    } catch { /* not JSON: left as it is */ }
  }
  return r;
}

function ip(req: Request) {
  return (req.headers.get("x-forwarded-for") || "").split(",")[0].trim() || "?";
}

// --------------------------------------------------------------------------------------------------------- the clinic --
type Ctx = { tenant: any; device: any; user?: any; perms: Set<string>; node: string };

async function laptop(req: Request): Promise<Ctx> {
  const t = req.headers.get("x-dd-token") || "";
  if (!t) throw new E("Компьютер не подключён к облаку склада", 401);
  const [d] = await sql`select d.*, row_to_json(t.*) as tenant from dd.devices d join dd.tenants t on t.id = d.tenant_id
                        where d.token_hash = ${await sha(t)} and d.kind = 'laptop' and not d.revoked`;
  if (!d) throw new E("Этот компьютер отключён от облака склада. Подключите его заново.", 401);
  if (d.tenant.status !== "active") throw new E("Облако склада клиники отключено. Свяжитесь с поддержкой.", 403);
  sql`update dd.devices set last_seen = now() where id = ${d.id}`.catch(() => {});
  return { tenant: d.tenant, device: d, perms: new Set(), node: "" };
}

async function phoneDevice(req: Request) {
  const t = req.headers.get("x-dd-device") || "";
  if (!t) throw new E("Телефон не подключён к клинике", 401);
  const [d] = await sql`select d.*, row_to_json(t.*) as tenant from dd.devices d join dd.tenants t on t.id = d.tenant_id
                        where d.token_hash = ${await sha(t)} and d.kind = 'phone' and not d.revoked`;
  if (!d || d.tenant.status !== "active") throw new E("Телефон отключён от клиники. Введите код клиники заново.", 401);
  return d;
}

async function phone(req: Request): Promise<Ctx> {
  const s = req.headers.get("x-dd-session") || "";
  if (!s) throw new E("Войдите по ПИН-коду", 401);
  const [r] = await sql`select s.*, row_to_json(st.*) as staff, row_to_json(t.*) as tenant, row_to_json(d.*) as device
                        from dd.sessions s join dd.staff st on st.tenant_id = s.tenant_id and st.login = s.login
                        join dd.tenants t on t.id = s.tenant_id join dd.devices d on d.id = s.device_id
                        where s.token_hash = ${await sha(s)} and s.expires_at > now()`;
  if (!r || !r.staff.pin_hash || r.device.revoked || r.tenant.status !== "active") throw new E("Войдите по ПИН-коду заново", 401);
  sql`update dd.sessions set last_seen = now() where token_hash = ${r.token_hash}`.catch(() => {});
  return { tenant: r.tenant, device: r.device, user: r.staff, perms: new Set(r.staff.perms || []), node: "p" + r.device.id };
}

function localNow(ctx: Ctx) {
  const t = new Date(Date.now() + Number(ctx.tenant.tz_offset ?? 180) * 60000).toISOString();
  return t.slice(0, 10) + " " + t.slice(11, 19);
}

function need(ctx: Ctx, ...any: string[]) {
  if (!any.some((p) => ctx.perms.has(p))) throw new E("У вашей должности нет на это права", 403);
}

// ---------------------------------------------------------------------------------------------------- laptop routes --
async function join(req: Request, f: any) {
  const code = norm(f.code);
  const bad = await sql`select n, since from dd.ip_fails where ip = ${"j:" + ip(req)}`;
  if (bad[0] && bad[0].n >= 10 && Date.now() - new Date(bad[0].since).getTime() < LOCK_MIN * 60000)
    throw new E(`Слишком много неверных кодов. Подождите ${LOCK_MIN} минут.`, 429);
  const [t] = code.length >= 19 ? await sql`select * from dd.tenants where join_hash = ${await sha(code)}` : [];
  if (!t) {
    await sql`insert into dd.ip_fails(ip, n, since) values (${"j:" + ip(req)}, 1, now()) on conflict (ip) do update set
              n = case when dd.ip_fails.since < now() - interval '15 minutes' then 1 else dd.ip_fails.n + 1 end,
              since = case when dd.ip_fails.since < now() - interval '15 minutes' then now() else dd.ip_fails.since end`;
    throw new E("Код подключения не подходит. Проверьте его.", 403);
  }
  if (t.status !== "active") throw new E("Облако склада клиники отключено. Свяжитесь с поддержкой.", 403);
  const id = hid(8), tok = token();
  await sql`insert into dd.devices(id, tenant_id, kind, name, token_hash, version, last_seen)
            values (${id}, ${t.id}, 'laptop', ${clean(f.name, 80) || "Компьютер"}, ${await sha(tok)}, ${clean(f.version, 20)}, now())`;
  if (Number.isFinite(Number(f.tz))) await sql`update dd.tenants set tz_offset = ${Math.round(Number(f.tz))} where id = ${t.id}`;
  return { device: id, token: tok, tenant: t.id, name: t.name, api: API };
}

async function status(ctx: Ctx, f: any) {
  const t = ctx.tenant;
  if (f.version) await sql`update dd.devices set version = ${clean(f.version, 20)} where id = ${ctx.device.id}`;
  if (Number.isFinite(Number(f.tz))) await sql`update dd.tenants set tz_offset = ${Math.round(Number(f.tz))} where id = ${t.id}`;
  if (clean(f.clinic, 120)) await sql`update dd.tenants set name = ${clean(f.clinic, 120)} where id = ${t.id} and name = ''`;
  const devices = await sql`select id, kind, name, version, created_at, last_seen from dd.devices
                            where tenant_id = ${t.id} and not revoked order by kind, created_at`;
  const pc = String(t.phone_code || "");
  return { tenant: t.id, name: t.name, seq: Number(t.seq), phone_code: pc ? pc.slice(0, 4) + "-" + pc.slice(4) : "",
    device: ctx.device.id, devices, api: API };
}

function checkKey(k: unknown) {
  if (typeof k !== "string" || k.length > 300 || !k.startsWith("[")) throw new E("Неверная строка");
  try { if (!Array.isArray(JSON.parse(k))) throw 0; } catch { throw new E("Неверная строка"); }
}

async function push(ctx: Ctx, f: any) {
  const ch = f.changes;
  if (!Array.isArray(ch) || ch.length > MAX_PUSH) throw new E("Слишком много изменений за раз");
  const out = [];
  const skipped = [];
  for (const c of ch) {
    if (!TABLES.includes(c?.t) || typeof c.ver !== "string" || !c.ver || c.ver.length > 80) { skipped.push([c?.t, c?.k]); continue; }
    checkKey(c.k);
    if (c.row !== null && typeof c.row !== "object") { skipped.push([c.t, c.k]); continue; }
    out.push({ t: c.t, k: c.k, ver: c.ver, base: c.base ?? null, vv: c.vv ?? null, row: hide(c.t, c.row), pbase: hide(c.t, c.pbase),
      pvv: c.pvv ?? null, origin: clean(c.origin, 40) });
  }
  const [r] = await sql`select dd.push(${ctx.tenant.id}, ${ctx.device.id}, ${JSON.stringify(out)}::jsonb) as r`;
  return { ...r.r, skipped };
}

async function pullRows(tenant: string, since: number, limit: number) {
  const [r] = await sql`select dd.pull(${tenant}, ${since}, ${limit}) as r`;
  return r.r as { rows: any[]; seq: number };
}

async function lpull(ctx: Ctx, f: any) {
  const lim = Math.max(1, Math.min(Number(f.limit) || 500, 1000));
  const r = await pullRows(ctx.tenant.id, Number(f.since) || 0, lim);
  return { rows: r.rows, seq: r.seq, more: r.rows.length >= lim };
}

async function staff(ctx: Ctx, f: any) {
  const list = (Array.isArray(f.staff) ? f.staff : []).slice(0, 500).map((u: any) => ({
    login: clean(u.login, 60).toLowerCase(), name: clean(u.name, 120), role: clean(u.role, 40), role_title: clean(u.role_title, 80),
    perms: (Array.isArray(u.perms) ? u.perms : []).filter((p: string) => PHONE_PERMS.includes(p)),
    pin_hash: /^pbkdf2\$\d+\$[0-9a-f]+\$[0-9a-f]+$/.test(String(u.pin_hash || "")) ? u.pin_hash : null, pin_at: clean(u.pin_at, 20) || null,
  })).filter((u: any) => u.login);
  const [r] = await sql`select dd.set_staff(${ctx.tenant.id}, ${JSON.stringify(list)}::jsonb) as n`;
  return { ok: true, staff: r.n };
}

// ----------------------------------------------------------------------------------------------------- phone routes --
async function hello(req: Request, f: any) {
  const key = "p:" + ip(req);
  const bad = await sql`select n, since from dd.ip_fails where ip = ${key}`;
  if (bad[0] && bad[0].n >= 10 && Date.now() - new Date(bad[0].since).getTime() < LOCK_MIN * 60000)
    throw new E(`Слишком много неверных кодов. Подождите ${LOCK_MIN} минут.`, 429);
  const code = norm(f.code);
  const [t] = code.length === 8 ? await sql`select * from dd.tenants where phone_code = ${code} and status = 'active'` : [];
  if (!t) {
    await sql`insert into dd.ip_fails(ip, n, since) values (${key}, 1, now()) on conflict (ip) do update set
              n = case when dd.ip_fails.since < now() - interval '15 minutes' then 1 else dd.ip_fails.n + 1 end,
              since = case when dd.ip_fails.since < now() - interval '15 minutes' then now() else dd.ip_fails.since end`;
    throw new E("Код клиники не подходит. Он есть в программе: Склад → Телефон.", 403);
  }
  const id = hid(8), tok = token();
  await sql`insert into dd.devices(id, tenant_id, kind, name, token_hash, last_seen)
            values (${id}, ${t.id}, 'phone', ${clean(f.name, 80) || "Телефон"}, ${await sha(tok)}, now())`;
  return { device: id, token: tok, clinic: t.name, staff: await staffList(t.id) };
}

async function staffList(tenant: string) {
  return (await sql`select login, name, role_title from dd.staff where tenant_id = ${tenant} and pin_hash is not null order by name`)
    .map((r: any) => ({ login: r.login, name: r.name, role_title: r.role_title }));
}

async function login(req: Request, f: any) {
  const d = await phoneDevice(req);
  const wait = (u: string | null) => u && new Date(u).getTime() > Date.now() ? Math.ceil((new Date(u).getTime() - Date.now()) / 60000) : 0;
  let w = wait(d.locked_until);
  if (w) throw new E(`Слишком много неверных ПИН-кодов. Подождите ${w} мин.`, 429);
  const [u] = await sql`select * from dd.staff where tenant_id = ${d.tenant_id} and login = ${clean(f.login, 60).toLowerCase()}`;
  if (u && (w = wait(u.locked_until))) throw new E(`Слишком много неверных ПИН-кодов. Подождите ${w} мин.`, 429);
  const pin = String(f.pin ?? "");
  const ok = !!u && /^\d{6}$/.test(pin) && await checkPin(pin, u.pin_hash);
  if (!ok) {
    // 5 wrong PINs — on this phone (whoever was tried) or for this person (on any phone) — and a pause of 15 minutes
    await sql`update dd.devices set fails = case when fails + 1 >= ${PIN_FAILS} then 0 else fails + 1 end,
              locked_until = case when fails + 1 >= ${PIN_FAILS} then now() + interval '15 minutes' else locked_until end
              where id = ${d.id}`;
    if (u) await sql`update dd.staff set fails = case when fails + 1 >= ${PIN_FAILS} then 0 else fails + 1 end,
                     locked_until = case when fails + 1 >= ${PIN_FAILS} then now() + interval '15 minutes' else locked_until end
                     where tenant_id = ${u.tenant_id} and login = ${u.login}`;
    throw new E("Неверный ПИН-код", 403);
  }
  await sql`update dd.devices set fails = 0, locked_until = null, last_seen = now() where id = ${d.id}`;
  await sql`update dd.staff set fails = 0, locked_until = null where tenant_id = ${u.tenant_id} and login = ${u.login}`;
  const tok = token();
  await sql`insert into dd.sessions(token_hash, tenant_id, device_id, login, expires_at, last_seen)
            values (${await sha(tok)}, ${d.tenant_id}, ${d.id}, ${u.login}, now() + ${SESSION_H + " hours"}::interval, now())`;
  return { session: tok, hours: SESSION_H, user: me({ user: u, perms: new Set(u.perms), tenant: d.tenant } as Ctx) };
}

function me(ctx: Ctx) {
  const p = ctx.perms;
  return { login: ctx.user.login, name: ctx.user.name, role_title: ctx.user.role_title, perms: [...p], clinic: ctx.tenant.name,
    can: { stock: ["stock_view", "stock_ops", "stock_edit", "stock_approve"].some((x) => p.has(x)),
      equipment: p.has("equipment") || p.has("stock_view"), equipment_edit: p.has("equipment"), money: p.has("accounting"),
      receive: p.has("stock_edit") || p.has("stock_ops"), use: p.has("stock_edit") || p.has("stock_ops"),
      direct: p.has("stock_edit") || p.has("stock_approve"), approve: p.has("stock_approve"),
      request: p.has("stock_edit") || p.has("stock_ops"), handle_requests: p.has("stock_edit") || p.has("stock_approve"),
      transfer: p.has("stock_edit") || p.has("stock_ops"), barcode: p.has("stock_edit") } };
}

async function ppull(ctx: Ctx, f: any) {
  const m = me(ctx);
  if (!m.can.stock && !m.can.equipment) throw new E("У вашей должности нет доступа к складу", 403);
  const lim = 1000;
  const r = await pullRows(ctx.tenant.id, Number(f.since) || 0, lim);
  const all = ctx.perms.has("stock_edit") || ctx.perms.has("stock_approve");
  const rows = [];
  for (const x of r.rows) {
    const ok = (m.can.stock && STOCK_T.has(x.t)) || (m.can.equipment && EQUIP_T.has(x.t));
    if (!ok) continue;
    if ((x.t === "stock_requests" || x.t === "stock_approvals") && !all && x.row && x.row.created_by !== ctx.user.login) continue;
    let row = x.row;
    if (x.t === "equipment" && row && !m.can.money) { row = { ...row }; for (const c of EQ_MONEY) delete row[c]; }
    rows.push({ t: x.t, k: x.k, row, seq: x.seq });
  }
  const last = r.rows.length ? r.rows[r.rows.length - 1].seq : Number(f.since) || 0;
  return { rows, next: last, seq: r.seq, more: r.rows.length >= lim, user: m };
}

// --------------------------------------------------------------------------------------------------- stock operations --
type Row = { k: string; ver: string; data: any };

async function rowsOf(ctx: Ctx, t: string, ids: string[]): Promise<Map<string, Row>> {
  const keys = ids.map((i) => ks([i]));
  const out = new Map<string, Row>();
  if (!keys.length) return out;
  for (const r of await sql`select k, ver, data from dd.rows where tenant_id = ${ctx.tenant.id} and tbl = ${t} and k = any(${sql.array(keys)}::text[])`)
    if (r.data) out.set(JSON.parse(r.k)[0], r as Row);
  return out;
}

async function one(ctx: Ctx, t: string, id: string): Promise<Row | null> {
  return (await rowsOf(ctx, t, [id])).get(id) || null;
}

async function count(ctx: Ctx, t: string, where: (d: any) => boolean) {
  const rows = await sql`select data from dd.rows where tenant_id = ${ctx.tenant.id} and tbl = ${t} and data is not null`;
  return rows.filter((r: any) => where(r.data)).length;
}

async function balances(ctx: Ctx, mids: string[]): Promise<Map<string, Map<string, number>>> {
  const out = new Map<string, Map<string, number>>();
  if (!mids.length) return out;
  for (const r of await sql`select data->>'material_id' as m, coalesce(data->>'location_id', '') as loc,
                                   sum((data->>'qty')::numeric) as q from dd.rows
                            where tenant_id = ${ctx.tenant.id} and tbl = 'stock_moves' and data is not null
                              and data->>'material_id' = any(${sql.array(mids)}::text[]) group by 1, 2`) {
    if (!out.has(r.m)) out.set(r.m, new Map());
    out.get(r.m)!.set(r.loc, Number(r.q));
  }
  return out;
}

async function place(ctx: Ctx, lid: unknown): Promise<{ id: string | null; name: string }> {
  const id = clean(lid, 60);
  if (!id) return { id: null, name: MAIN };
  const p = await one(ctx, "stock_locations", id);
  if (!p || !Number(p.data.active ?? 1)) throw new E("Место хранения не найдено");
  return { id, name: p.data.name || MAIN };
}

async function lines(ctx: Ctx, raw: unknown, positive = true) {
  const want = new Map<string, number>();
  const list = Array.isArray(raw) ? raw : [];
  for (const ln of list) {
    const mid = clean(ln?.material_id, 60);
    if (!mid) continue;
    const q = num(ln.qty);
    if (q <= 0 && positive) throw new E("Укажите количество больше нуля");
    if (q > 0) want.set(mid, r3((want.get(mid) || 0) + q));
  }
  if (!want.size) throw new E("Добавьте хотя бы один материал");
  const mats = await rowsOf(ctx, "materials", [...want.keys()]);
  for (const mid of want.keys()) if (!mats.has(mid)) throw new E("В списке есть материал, которого нет в справочнике");
  return { want, mats };
}

type W = { t: string; k: string; row: any; expect?: string | null };

async function write(ctx: Ctx, items: W[]) {
  try {
    const [r] = await sql`select dd.write(${ctx.tenant.id}, ${ctx.node}, ${ctx.device.id}, ${JSON.stringify(items)}::jsonb) as r`;
    return r.r;
  } catch (e) {
    if (String((e as Error).message || "").includes("changed:")) throw new E("Пока вы заполняли, это изменили на другом устройстве. Обновите и повторите.", 409);
    throw e;
  }
}

const who = (ctx: Ctx) => ctx.user.name || ctx.user.login;

function moveRow(o: any) {
  return { material_id: o.material_id, qty: o.qty, price: o.price ?? 0, kind: o.kind, doc_id: o.doc_id ?? null, invoice_id: null,
    reason: o.reason ?? null, user_name: o.user_name, at: o.at, location_id: o.location_id ?? null, uid: o.uid };
}

function docRow(o: any) {
  return { id: o.id, kind: o.kind, number: o.number ?? "", date: o.date, supplier_id: o.supplier_id ?? null, reason: o.reason ?? "",
    comment: o.comment ?? "", total: o.total ?? 0, user_name: o.user_name, created_at: o.created_at, nodoc: o.nodoc ?? 0,
    location_id: o.location_id ?? null, to_location_id: o.to_location_id ?? null };
}

async function nextNumber(ctx: Ctx, kind: string) {
  return String(await count(ctx, "stock_docs", (d) => d.kind === kind && !Number(d.nodoc || 0)) + 1);
}

async function opReceive(ctx: Ctx, f: any) {
  need(ctx, "stock_edit", "stock_ops");
  const { want: _w, mats } = await lines(ctx, f.lines);
  const at = localNow(ctx);
  const d = f.date ? day(f.date) : at.slice(0, 10);
  const loc = await place(ctx, f.location_id);
  const sup = clean(f.supplier_id, 60);
  if (sup && !(await one(ctx, "suppliers", sup))) throw new E("Поставщик не найден");
  const did = "R-" + hid(5);
  const items: W[] = [];
  let total = 0;
  const price = new Map<string, number>();
  for (const ln of f.lines || []) {
    const mid = clean(ln?.material_id, 60);
    if (!mid) continue;
    const q = num(ln.qty), p = Math.max(0, num(ln.price, "Цена"));
    if (q <= 0) throw new E("Количество в приходе должно быть больше нуля");
    const lot = clean(ln.lot, 60), exp = day(ln.expires, "Годен до");
    const uid = hid(12);
    total += q * p;
    items.push({ t: "stock_moves", k: ks([uid]), row: moveRow({ material_id: mid, qty: q, price: p, kind: "receipt", doc_id: did,
      user_name: who(ctx), at: `${d} ${at.slice(11)}`, location_id: loc.id, uid }) });
    if (lot || exp) {
      const lu = hid(12);
      items.push({ t: "stock_lots", k: ks([lu]), row: { material_id: mid, move_id: { $ref: [uid] }, lot, expires: exp, qty: q,
        created_at: at, uid: lu } });
    }
    if (p > 0) price.set(mid, p);
  }
  items.unshift({ t: "stock_docs", k: ks([did]), row: docRow({ id: did, kind: "receipt", number: clean(f.number, 50), date: d,
    supplier_id: sup || null, comment: clean(f.comment, 500), total: r2(total), user_name: who(ctx), created_at: at,
    nodoc: f.nodoc ? 1 : 0, location_id: loc.id }) });
  for (const [mid, p] of price) {
    const m = mats.get(mid)!;
    if (Number(m.data.price || 0) !== p) items.push({ t: "materials", k: m.k, row: { ...m.data, price: p }, expect: m.ver });
  }
  await write(ctx, items);
  return { doc_id: did, message: "Поставка принята" };
}

// A write-off now: the document A-<id> (or W-…) with moves of fixed ids, as the laptops make it (stock.write_off).
async function writeOffItems(ctx: Ctx, form: any, user: string, did: string, uid: string, mats: Map<string, Row>) {
  const at = localNow(ctx);
  const tm = /^\d{2}:\d{2}$/.test(form.time || "") ? form.time + ":00" : at.slice(11);
  let total = 0;
  const items: W[] = [];
  form.lines.forEach((ln: any, i: number) => {
    const p = Number(mats.get(ln.material_id)?.data.price || 0);
    total += ln.qty * p;
    const u = `${uid}-${i}`.slice(0, 120);
    items.push({ t: "stock_moves", k: ks([u]), row: moveRow({ material_id: ln.material_id, qty: -ln.qty, price: p, kind: "writeoff",
      doc_id: did, reason: form.reason.slice(0, 300), user_name: user, at: `${form.date} ${tm}`, location_id: form.location_id || null, uid: u }) });
  });
  items.unshift({ t: "stock_docs", k: ks([did]), row: docRow({ id: did, kind: "writeoff", number: await nextNumber(ctx, "writeoff"),
    date: form.date, reason: form.reason, comment: form.comment || "", total: r2(total), user_name: user, created_at: at,
    location_id: form.location_id || null }) });
  return items;
}

async function checkBalances(ctx: Ctx, form: any, mats: Map<string, Row>, placeName: string) {
  const bal = await balances(ctx, form.lines.map((l: any) => l.material_id));
  for (const ln of form.lines) {
    const have = r3(bal.get(ln.material_id)?.get(form.location_id || "") || 0);
    if (ln.qty > have + 1e-9) throw new E(`«${mats.get(ln.material_id)?.data.name}»: в месте «${placeName}» ${have}, списать ${ln.qty} нельзя`);
  }
}

async function opUse(ctx: Ctx, f: any) {
  need(ctx, "stock_edit", "stock_ops");
  const kind = f.kind === "writeoff" ? "writeoff" : "consume";
  const { want, mats } = await lines(ctx, f.lines);
  const loc = await place(ctx, f.location_id);
  const at = localNow(ctx);
  const reason = kind === "consume" ? "Расход в лечении" : clean(f.reason, 300);
  if (!reason) throw new E("Укажите причину списания");
  const form = { kind, date: f.date ? day(f.date) : at.slice(0, 10), time: clean(f.time, 5), location_id: loc.id || "",
    patient_id: "", patient_name: "", service_id: "", service_title: "", reason, comment: clean(f.comment, 500),
    lines: [...want].map(([material_id, qty]) => ({ material_id, qty })) };
  await checkBalances(ctx, form, mats, loc.name);
  const direct = ctx.perms.has("stock_edit") || ctx.perms.has("stock_approve");
  const aid = "AP-" + hid(5);
  const parts = form.lines.slice(0, 6).map((l) => `${mats.get(l.material_id)?.data.name || "?"} — ${l.qty}`);
  const summary = (parts.join("; ") + (form.lines.length > 6 ? ` и ещё ${form.lines.length - 6}` : "")).slice(0, 500);
  const total = r2(form.lines.reduce((s, l) => s + l.qty * Number(mats.get(l.material_id)?.data.price || 0), 0));
  const items: W[] = direct ? await writeOffItems(ctx, form, who(ctx), `A-${aid}`, `a-${aid}`, mats) : [];
  items.push({ t: "stock_approvals", k: ks([aid]), row: { id: aid, kind, status: direct ? "done" : "pending",
    payload: JSON.stringify(form), total, location_id: form.location_id, summary, created_by: ctx.user.login, created_name: who(ctx),
    created_at: at, sent_at: at, updated_at: at, decided_by: direct ? ctx.user.login : null, decided_name: direct ? who(ctx) : null,
    decided_at: direct ? at : null, answer: null, doc_id: direct ? `A-${aid}` : "" } });
  await write(ctx, items);
  return { id: aid, status: direct ? "done" : "pending",
    message: direct ? "Списано" : "Отправлено на согласование — со склада спишется после проверки менеджера" };
}

async function opDecide(ctx: Ctx, f: any) {
  need(ctx, "stock_approve");
  const a = await one(ctx, "stock_approvals", clean(f.id, 60));
  if (!a) throw new E("Запись не найдена", 404);
  if (a.data.status !== "pending") throw new E("Уже решено на другом устройстве");
  const at = localNow(ctx);
  const items: W[] = [];
  let answer = clean(f.answer, 300);
  if (f.action === "reject") {
    if (!answer) throw new E("Напишите причину отказа — сотрудник увидит её");
    items.push({ t: "stock_approvals", k: a.k, expect: a.ver, row: { ...a.data, status: "rejected", decided_by: ctx.user.login,
      decided_name: who(ctx), decided_at: at, answer, updated_at: at } });
  } else if (f.action === "approve") {
    let form: any = {};
    try { form = JSON.parse(a.data.payload || "{}"); } catch { /* empty */ }
    form.lines = (form.lines || []).map((l: any) => ({ material_id: l.material_id, qty: Number(l.qty) }));
    const did = `A-${a.data.id}`;
    if (!(await one(ctx, "stock_docs", did))) {
      const mats = await rowsOf(ctx, "materials", form.lines.map((l: any) => l.material_id));
      const loc = await place(ctx, form.location_id).catch(() => ({ id: form.location_id || null, name: MAIN }));
      await checkBalances(ctx, form, mats, loc.name);
      const user = `${a.data.created_name || a.data.created_by} (согласовал(а) ${who(ctx)})`.slice(0, 100);
      items.push(...await writeOffItems(ctx, form, user, did, `a-${a.data.id}`, mats));
    }
    items.push({ t: "stock_approvals", k: a.k, expect: a.ver, row: { ...a.data, status: "approved", decided_by: ctx.user.login,
      decided_name: who(ctx), decided_at: at, answer, doc_id: did, updated_at: at } });
  } else throw new E("Неизвестное действие");
  await write(ctx, items);
  return { id: a.data.id, message: f.action === "reject" ? "Отклонено" : "Согласовано и списано" };
}

async function opApprovalCancel(ctx: Ctx, f: any) {
  need(ctx, "stock_edit", "stock_ops", "stock_approve");
  const a = await one(ctx, "stock_approvals", clean(f.id, 60));
  if (!a) throw new E("Запись не найдена", 404);
  if (a.data.created_by !== ctx.user.login && !(ctx.perms.has("stock_edit") || ctx.perms.has("stock_approve")))
    throw new E("Отменить можно только своё");
  if (!["draft", "pending"].includes(a.data.status)) throw new E("Уже решено — отменить нельзя");
  await write(ctx, [{ t: "stock_approvals", k: a.k, expect: a.ver, row: { ...a.data, status: "cancelled", updated_at: localNow(ctx) } }]);
  return { id: a.data.id, message: "Отменено" };
}

async function opRequest(ctx: Ctx, f: any) {
  need(ctx, "stock_edit", "stock_ops");
  const { want } = await lines(ctx, f.lines);
  const loc = await place(ctx, f.location_id);
  const at = localNow(ctx);
  const pr = ["normal", "urgent", "critical"].includes(f.priority) ? f.priority : "normal";
  const number = String(await count(ctx, "stock_requests", (d) => !!d.number) + 1);
  const id = "RQ-" + hid(5);
  await write(ctx, [{ t: "stock_requests", k: ks([id]), row: { id, number, location_id: loc.id || "",
    need_date: f.need_date ? day(f.need_date, "Дата потребности") : "", priority: pr, comment: clean(f.comment, 500),
    lines: JSON.stringify([...want].map(([material_id, qty]) => ({ material_id, qty }))), issued: "{}", status: "new",
    created_by: ctx.user.login, created_name: who(ctx), created_at: at, sent_at: at, updated_at: at, decided_by: null,
    decided_name: null, decided_at: null, answer: null, doc_ids: null, accepted_by: null, accepted_name: null, accepted_at: null } }]);
  return { id, number, message: `Заявка № ${number} отправлена` };
}

async function opRequestStatus(ctx: Ctx, f: any) {
  const r = await one(ctx, "stock_requests", clean(f.id, 60));
  if (!r) throw new E("Заявка не найдена", 404);
  const at = localNow(ctx);
  const s = r.data.status;
  const manager = ctx.perms.has("stock_edit") || ctx.perms.has("stock_approve");
  let row: any;
  if (f.kind === "request_accept") {
    need(ctx, "stock_edit", "stock_approve");
    if (s === "accepted") return { id: r.data.id, message: "Заявка уже принята" };
    if (s !== "new") throw new E("Заявку уже нельзя принять");
    row = { ...r.data, status: "accepted", accepted_by: ctx.user.login, accepted_name: who(ctx), accepted_at: at, updated_at: at };
  } else if (f.kind === "request_reject") {
    need(ctx, "stock_edit", "stock_approve");
    if (!["new", "accepted", "partial"].includes(s)) throw new E("Отклонить можно только заявку, которая ещё не выдана");
    const answer = clean(f.answer, 300);
    if (!answer) throw new E("Напишите причину — медсестра увидит её в своих заявках");
    row = { ...r.data, status: "rejected", decided_by: ctx.user.login, decided_name: who(ctx), decided_at: at, answer, updated_at: at };
  } else {
    need(ctx, "stock_edit", "stock_ops", "stock_approve");
    if (r.data.created_by !== ctx.user.login && !manager) throw new E("Отменить можно только свою заявку");
    if (!(manager ? ["draft", "new", "accepted"] : ["draft", "new"]).includes(s))
      throw new E(s === "accepted" ? "Заявка уже принята — попросите менеджера склада" : "Эту заявку уже нельзя отменить");
    row = { ...r.data, status: "cancelled", updated_at: at };
  }
  await write(ctx, [{ t: "stock_requests", k: r.k, expect: r.ver, row }]);
  return { id: r.data.id, message: { request_accept: "Заявка принята", request_reject: "Заявка отклонена" }[f.kind as string] || "Заявка отменена" };
}

async function opTransfer(ctx: Ctx, f: any) {
  need(ctx, "stock_edit", "stock_ops");
  const src = await place(ctx, f.from_id), dst = await place(ctx, f.to_id);
  if ((src.id || "") === (dst.id || "")) throw new E("Выберите разные места: откуда и куда");
  const { want, mats } = await lines(ctx, f.lines);
  const bal = await balances(ctx, [...want.keys()]);
  for (const [mid, q] of want) {
    const have = r3(bal.get(mid)?.get(src.id || "") || 0);
    if (q > have + 1e-9) throw new E(`«${mats.get(mid)?.data.name}»: в месте «${src.name}» ${have}, переместить ${q} нельзя`);
  }
  const at = localNow(ctx);
  const d = f.date ? day(f.date) : at.slice(0, 10);
  const did = "T-" + hid(5);
  const why = `${src.name} → ${dst.name}`;
  let total = 0;
  const items: W[] = [];
  for (const [mid, q] of want) {
    const p = Number(mats.get(mid)!.data.price || 0);
    total += q * p;
    for (const [qty, loc] of [[-q, src.id], [q, dst.id]] as [number, string | null][]) {
      const uid = hid(12);
      items.push({ t: "stock_moves", k: ks([uid]), row: moveRow({ material_id: mid, qty, price: p, kind: "transfer", doc_id: did,
        reason: why, user_name: who(ctx), at: `${d} ${at.slice(11)}`, location_id: loc, uid }) });
    }
  }
  items.unshift({ t: "stock_docs", k: ks([did]), row: docRow({ id: did, kind: "transfer", number: await nextNumber(ctx, "transfer"),
    date: d, reason: why, comment: clean(f.comment, 500), total: r2(total), user_name: who(ctx), created_at: at,
    location_id: src.id, to_location_id: dst.id }) });
  // what was issued counts against the requests (in their order) — «выдана» when all is
  const left = new Map(want);
  const reqs = await rowsOf(ctx, "stock_requests", (Array.isArray(f.request_ids) ? f.request_ids : []).map((x: unknown) => clean(x, 60)).filter(Boolean));
  for (const r of reqs.values()) {
    if (!["new", "accepted", "partial"].includes(r.data.status)) continue;
    let issued: any = {}, docs: any[] = [], rl: any[] = [];
    try { issued = JSON.parse(r.data.issued || "{}") || {}; } catch { /* empty */ }
    try { docs = JSON.parse(r.data.doc_ids || "[]") || []; } catch { /* empty */ }
    try { rl = JSON.parse(r.data.lines || "[]") || []; } catch { /* empty */ }
    for (const ln of rl) {
      const give = Math.min(Math.max(0, Number(ln.qty) - Number(issued[ln.material_id] || 0)), left.get(ln.material_id) || 0);
      if (give > 0) { issued[ln.material_id] = r3(Number(issued[ln.material_id] || 0) + give); left.set(ln.material_id, r3(left.get(ln.material_id)! - give)); }
    }
    const full = rl.every((ln) => Number(issued[ln.material_id] || 0) + 1e-9 >= Number(ln.qty));
    const some = Object.values(issued).some((v) => Number(v) > 0);
    items.push({ t: "stock_requests", k: r.k, expect: r.ver, row: { ...r.data, issued: JSON.stringify(issued),
      doc_ids: JSON.stringify([...docs, did]), status: full ? "done" : some ? "partial" : r.data.status, updated_at: at } });
  }
  await write(ctx, items);
  return { doc_id: did, message: "Перемещено" };
}

const EQ_STATUS: Record<string, string> = { in_use: "В работе", repair: "В ремонте", storage: "На складе", written_off: "Списано" };
const EQ_CONDITION: Record<string, string> = { ok: "Исправно", service: "Требует обслуживания", faulty: "Неисправно" };

async function liveEq(ctx: Ctx, id: unknown) {
  const e = await one(ctx, "equipment", clean(id, 60));
  if (!e) throw new E("Оборудование не найдено", 404);
  if (e.data.status === "written_off") throw new E("Оборудование выбыло — изменить его нельзя");
  return e;
}

function evRow(ctx: Ctx, eid: string, kind: string, text: string, d?: string, cost = 0, data: any = null) {
  const uid = hid(12);
  return { t: "equipment_events", k: ks([uid]), row: { equipment_id: eid, kind, date: d || localNow(ctx).slice(0, 10), text, cost,
    user_name: who(ctx), created_at: localNow(ctx), data: data === null ? null : JSON.stringify(data), uid } };
}

async function eqPlace(ctx: Ctx, f: any, e: any): Promise<[string, string]> {
  if (clean(f.location_id, 60)) {
    const p = await one(ctx, "stock_locations", clean(f.location_id, 60));
    if (!p) throw new E("Такого места нет в «Местах хранения»");
    return [p.data.id, p.data.name || ""];
  }
  if ("location" in f) return ["", clean(f.location, 100)];
  return [e.location_id || "", e.location || ""];
}

async function opEquipmentSet(ctx: Ctx, f: any) {
  need(ctx, "equipment");
  const e = await liveEq(ctx, f.id);
  const d = e.data, sets: any = {}, evs: [string, string][] = [];
  if ("location_id" in f || "location" in f) {
    const [lid, loc] = await eqPlace(ctx, f, d);
    if (loc !== (d.location || "") || lid !== (d.location_id || "")) {
      Object.assign(sets, { location_id: lid, location: loc });
      evs.push(["move", `${d.location || "—"} → ${loc || "—"}`]);
    }
  }
  if ("condition" in f) {
    if (!EQ_CONDITION[f.condition]) throw new E("Выберите техническое состояние");
    if (f.condition !== (d.condition || "ok")) {
      sets.condition = f.condition;
      evs.push(["condition", `${EQ_CONDITION[d.condition || "ok"]} → ${EQ_CONDITION[f.condition]}`]);
    }
  }
  if ("status" in f) {
    if (!EQ_STATUS[f.status] || f.status === "written_off") throw new E("Выбытие оформляется в программе на компьютере");
    if (f.status !== d.status) {
      sets.status = f.status;
      if (f.status === "repair") {
        if (!("condition" in sets) && (d.condition || "ok") === "ok") sets.condition = "faulty";
        evs.push(["repair", "Отправлено на ремонт"]);
      } else evs.push(["status", `${EQ_STATUS[d.status] || d.status} → ${EQ_STATUS[f.status]}`]);
    }
  }
  const note = clean(f.text, 500);
  if (note && evs.length) evs[evs.length - 1][1] += `. ${note}`;
  if (!Object.keys(sets).length) return { id: d.id, message: "Без изменений" };
  await write(ctx, [{ t: "equipment", k: e.k, expect: e.ver, row: { ...d, ...sets } }, ...evs.map(([k, t]) => evRow(ctx, d.id, k, t))]);
  return { id: d.id, message: "Сохранено" };
}

async function opEquipmentInventory(ctx: Ctx, f: any) {
  need(ctx, "equipment");
  const e = await liveEq(ctx, f.id);
  const d = e.data;
  const found = ![false, 0, "0", "false", "no"].includes(f.found);
  const comment = clean(f.comment, 500);
  const data: any = { found }, diffs: string[] = [], sets: any = {};
  if (found) {
    const [lid, loc] = ("location_id" in f || "location" in f) ? await eqPlace(ctx, f, d) : [d.location_id || "", d.location || ""];
    if (loc !== (d.location || "")) { diffs.push(`место: ${d.location || "—"} → ${loc || "—"}`); Object.assign(sets, { location_id: lid, location: loc }); }
    const cond = f.condition || d.condition || "ok";
    if (!EQ_CONDITION[cond]) throw new E("Выберите техническое состояние");
    if (cond !== (d.condition || "ok")) { diffs.push(`состояние: ${EQ_CONDITION[d.condition || "ok"]} → ${EQ_CONDITION[cond]}`); sets.condition = cond; }
    Object.assign(data, { location: loc, condition: cond });
  } else diffs.push("не найдено на месте");
  data.diffs = diffs;
  const text = (found ? "Найдено" : "Не найдено") + (found && diffs.length ? "; расхождения: " + diffs.join("; ") : found ? "; расхождений нет" : "") +
    (comment ? `. ${comment}` : "");
  const items: W[] = [];
  if (Object.keys(sets).length) items.push({ t: "equipment", k: e.k, expect: e.ver, row: { ...d, ...sets } });
  items.push(evRow(ctx, d.id, "inventory", text, f.date ? day(f.date) : undefined, 0, data));
  await write(ctx, items);
  return { id: d.id, message: diffs.length ? "Инвентаризация: есть расхождения" : "Инвентаризация: всё на месте" };
}

async function opEquipmentEvent(ctx: Ctx, f: any) {
  need(ctx, "equipment");
  const e = await one(ctx, "equipment", clean(f.id, 60));
  if (!e) throw new E("Оборудование не найдено", 404);
  const kind = ["service", "repair", "note"].includes(f.kind) ? f.kind : "note";
  const text = clean(f.text, 1000);
  if (!text) throw new E("Опишите, что сделано");
  const d = f.date ? day(f.date) : localNow(ctx).slice(0, 10);
  const items: W[] = [evRow(ctx, e.data.id, kind, text, d, Math.max(0, num(f.cost, "Стоимость")))];
  const sets: any = {};
  if (f.next_service !== undefined && f.next_service !== null) sets.next_service = f.next_service ? day(f.next_service, "Следующее ТО") : "";
  if (f.back_in_use && e.data.status === "repair") {
    Object.assign(sets, { status: "in_use", condition: "ok" });
    items.push(evRow(ctx, e.data.id, "status", `${EQ_STATUS.repair} → ${EQ_STATUS.in_use}`, d));
  }
  if (Object.keys(sets).length) items.unshift({ t: "equipment", k: e.k, expect: e.ver, row: { ...e.data, ...sets } });
  await write(ctx, items);
  return { id: e.data.id, message: "Записано" };
}

async function opBarcode(ctx: Ctx, f: any) {
  need(ctx, "stock_edit");
  const m = await one(ctx, "materials", clean(f.id, 60));
  if (!m) throw new E("Материал не найден", 404);
  const bar = clean(f.barcode, 60);
  if (!bar) throw new E("Отсканируйте штрихкод");
  const dup = await sql`select data->>'name' as name from dd.rows where tenant_id = ${ctx.tenant.id} and tbl = 'materials'
                        and data->>'barcode' = ${bar} and k <> ${m.k} and coalesce((data->>'active')::int, 1) = 1 limit 1`;
  if (dup[0]) throw new E(`Штрихкод ${bar} уже указан у материала «${dup[0].name}»`);
  await write(ctx, [{ t: "materials", k: m.k, expect: m.ver, row: { ...m.data, barcode: bar } }]);
  return { id: m.data.id, message: "Штрихкод привязан" };
}

const OPS: Record<string, (ctx: Ctx, f: any) => Promise<any>> = {
  receive: opReceive, use: opUse, decide: opDecide, approval_cancel: opApprovalCancel, request: opRequest,
  request_accept: opRequestStatus, request_reject: opRequestStatus, request_cancel: opRequestStatus, transfer: opTransfer,
  equipment_set: opEquipmentSet, equipment_inventory: opEquipmentInventory, equipment_event: opEquipmentEvent, barcode: opBarcode,
};

async function op(ctx: Ctx, f: any) {
  const id = clean(f.id, 80);
  if (!/^[A-Za-z0-9_-]{8,80}$/.test(id)) throw new E("Неверная операция");
  const fn = OPS[f.kind];
  if (!fn) throw new E("Неизвестная операция");
  const [done] = await sql`select result from dd.ops where tenant_id = ${ctx.tenant.id} and id = ${id}`;
  if (done) return { ...done.result, repeated: true };   // the phone sent it again after a lost answer
  const res = await fn(ctx, f);
  await sql`insert into dd.ops(tenant_id, id, login, kind, result) values (${ctx.tenant.id}, ${id}, ${ctx.user.login}, ${f.kind},
            ${JSON.stringify(res)}::jsonb) on conflict do nothing`;
  return res;
}

// ------------------------------------------------------------------------------------------------------------- router --
Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(req) });
  const path = new URL(req.url).pathname.replace(/^.*?\/stock(?=\/|$)/, "").replace(/\/+$/, "");
  try {
    if (req.method === "GET" && (path === "" || path === "/v1/ping")) return json(req, { app: "dentaldesk-stock", api: API });
    if (req.method !== "POST") throw new E("Не найдено", 404);
    const len = Number(req.headers.get("content-length") || 0);
    if (len > 8_000_000) throw new E("Слишком большой запрос", 413);
    let f: any = {};
    try { f = await req.json(); } catch { throw new E("Неверный запрос"); }
    if (!f || typeof f !== "object" || Array.isArray(f)) throw new E("Неверный запрос");
    switch (path) {
      case "/v1/join": return json(req, await join(req, f));
      case "/v1/status": return json(req, await status(await laptop(req), f));
      case "/v1/push": return json(req, await push(await laptop(req), f));
      case "/v1/pull": return json(req, await lpull(await laptop(req), f));
      case "/v1/staff": return json(req, await staff(await laptop(req), f));
      case "/v1/leave": {
        const c = await laptop(req);
        await sql`update dd.devices set revoked = true, token_hash = null where id = ${c.device.id}`;
        return json(req, { ok: true });
      }
      case "/p/hello": return json(req, await hello(req, f));
      case "/p/staff": {
        const d = await phoneDevice(req);
        return json(req, { clinic: d.tenant.name, staff: await staffList(d.tenant_id) });
      }
      case "/p/login": return json(req, await login(req, f));
      case "/p/me": return json(req, { user: me(await phone(req)) });
      case "/p/pull": return json(req, await ppull(await phone(req), f));
      case "/p/op": return json(req, await op(await phone(req), f));
      case "/p/logout": {
        const s = req.headers.get("x-dd-session") || "";
        if (s) await sql`delete from dd.sessions where token_hash = ${await sha(s)}`;
        return json(req, { ok: true });
      }
      case "/p/leave": {
        const d = await phoneDevice(req);
        await sql`delete from dd.sessions where device_id = ${d.id}`;
        await sql`update dd.devices set revoked = true, token_hash = null where id = ${d.id}`;
        return json(req, { ok: true });
      }
    }
    throw new E("Не найдено", 404);
  } catch (e) {
    if (e instanceof E) return json(req, { error: e.message }, e.code);
    console.error("stock", path, e);
    return json(req, { error: "Ошибка сервера. Попробуйте ещё раз." }, 500);
  }
});
