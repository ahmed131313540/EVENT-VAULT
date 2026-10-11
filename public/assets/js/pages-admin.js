/* Event Vault: admin pages — platform-wide overview, users, events, orders, scans, requests, messages, settings.
   Mirrors the patterns in pages-account.js / pages-organizer.js: EV.page returns a skeleton synchronously,
   setTimeout(fn, 0) fetches and fills it in (queueMicrotask fires before the HTML is in the DOM — don't use it,
   see core.js's render() for why). Every route here requires role admin; a non-admin sees EV.accessDenied(). */
(function (EV) {
"use strict";
const { $, $$, esc, money, qs, fmtDate, fmtTime, fmtWhen, debounce } = EV.util;
const icon = EV.icon;

function requireAdminPage(fn) { return EV.requireRolePage(["admin"], fn); }
function alertHtml(msg) { return `<div class="alert err">${icon("alert", 18)}${esc(msg)}</div>`; }
function loading() { return `<div style="text-align:center;padding:60px 0"><span class="spinner lg"></span></div>`; }

const NAV = [
  ["overview", "chart", "Overview", "#/admin"],
  ["users", "user", "Users", "#/admin/users"],
  ["events", "calendar", "Events", "#/admin/events"],
  ["orders", "ticket", "Orders", "#/admin/orders"],
  ["scans", "camera", "Scans", "#/admin/scans"],
  ["requests", "spark", "Requests", "#/admin/requests"],
  ["messages", "mail", "Messages", "#/admin/messages"],
  ["settings", "tool", "Settings", "#/admin/settings"],
];
function shell(active, content) { return EV.dashShell(active, content, NAV); }

/* ===================================================================== OVERVIEW */
EV.page("/admin", requireAdminPage(async () => {
  const html = shell("overview", `<div id="admin-ov">${loading()}</div>`);
  setTimeout(loadAdminOverview);
  return html;
}));

async function loadAdminOverview() {
  const box = $("#admin-ov");
  let data, breakdown;
  try { [data, breakdown] = await Promise.all([EV.api.get("/admin/overview"), EV.api.get("/admin/breakdown")]); }
  catch (e) { box.innerHTML = alertHtml(e.message); return; }
  const s = data.stats;
  box.innerHTML = `
    <div class="dash-head"><h1>Platform overview</h1></div>
    <div class="stats">
      ${EV.statCard("user", "Total users", s.total_users)}
      ${EV.statCard("calendar", "Total events", s.total_events)}
      ${EV.statCard("ticket", "Tickets sold", s.tickets_sold)}
      ${EV.statCard("check", "Checked in", s.checked_in)}
      ${EV.statCard("spark", "Total revenue", null, { cents: s.revenue_cents, gold: true })}
      ${EV.statCard("ban", "Refunded", null, { cents: s.refunded_cents })}
    </div>
    ${s.pending_requests ? `<div class="alert warn" style="margin-top:16px">${icon("alert", 18)}<span>${s.pending_requests} organiser request${s.pending_requests === 1 ? "" : "s"} waiting for review. <a href="#/admin/requests" style="color:inherit;text-decoration:underline">Review now</a></span></div>` : ""}
    <div class="cols" style="margin-top:20px">
      <div class="panel"><h2>Ticket sales, last 14 days</h2><p class="sub">Across every event on the platform.</p>${EV.barChart(data.sales_by_day)}</div>
      <div class="panel"><h2>By category</h2><p class="sub">Events and revenue per category.</p>
        <div class="list">${breakdown.by_category.map((c) => `<div class="row-item"><div class="grow"><b>${esc(c.category)}</b><small>${c.events} event${c.events === 1 ? "" : "s"}</small></div><b class="gold" style="font-family:var(--head)">${money(c.revenue_cents)}</b></div>`).join("") || "<p>No events yet.</p>"}</div>
      </div>
    </div>
    <div class="panel" style="margin-top:20px"><h2>By city</h2><p class="sub">Events and revenue per city.</p>
      <div class="list">${breakdown.by_city.map((c) => `<div class="row-item"><div class="grow"><b>${esc(c.city)}</b><small>${c.events} event${c.events === 1 ? "" : "s"}</small></div><b class="gold" style="font-family:var(--head)">${money(c.revenue_cents)}</b></div>`).join("") || "<p>No events yet.</p>"}</div>
    </div>`;
  EV.armReveal(box);
  EV.animateCounts(box);
}

/* ===================================================================== USERS */
EV.page("/admin/users", requireAdminPage(async () => {
  const html = shell("users", `
    <div class="dash-head"><h1>Users</h1></div>
    <div class="filters" style="grid-template-columns:1fr 200px">
      <input id="u-q" placeholder="Search name or email…">
      <select id="u-role"><option value="">Any role</option><option value="user">User</option><option value="organizer">Organizer</option><option value="admin">Admin</option></select>
    </div>
    <div id="u-list" style="margin-top:18px">${loading()}</div>
    <div style="text-align:center;margin-top:20px" id="u-more"></div>`);
  setTimeout(() => wireUsers());
  return html;
}));

async function wireUsers() {
  const list = $("#u-list"), more = $("#u-more");
  const state = { q: "", role: "", offset: 0 };
  const LIMIT = 20;
  async function load(reset) {
    if (reset) { state.offset = 0; list.innerHTML = loading(); }
    let data;
    try { data = await EV.api.get("/admin/users" + qs({ q: state.q, role: state.role, limit: LIMIT, offset: state.offset })); }
    catch (e) { list.innerHTML = alertHtml(e.message); return; }
    const rows = data.users.map(userRow).join("");
    list.innerHTML = (state.offset === 0 ? rows : list.innerHTML + rows) || EV.emptyState("No users match that search.");
    state.offset += data.users.length;
    more.innerHTML = state.offset < data.total ? `<button class="btn btn-secondary" id="u-more-btn">Load more</button>` : "";
    const btn = $("#u-more-btn"); if (btn) btn.onclick = () => load(false);
    wireUserActions();
  }
  const run = debounce(() => load(true), 300);
  $("#u-q").addEventListener("input", (e) => { state.q = e.target.value; run(); });
  $("#u-role").addEventListener("change", (e) => { state.role = e.target.value; load(true); });

  function wireUserActions() {
    $$("[data-role-btn]", list).forEach((btn) => btn.addEventListener("click", async () => {
      const id = btn.dataset.id, role = btn.dataset.roleBtn;
      try { await EV.api.post(`/admin/users/${id}/role`, { role }); EV.toast(`Role set to ${role}.`, "ok"); load(true); }
      catch (e) { EV.toast(e.message, "err"); }
    }));
    $$("[data-suspend]", list).forEach((btn) => btn.addEventListener("click", async () => {
      const id = btn.dataset.id, suspended = btn.dataset.suspend === "true";
      try { await EV.api.post(`/admin/users/${id}/suspend`, { suspended }); EV.toast(suspended ? "User suspended." : "User unsuspended.", "ok"); load(true); }
      catch (e) { EV.toast(e.message, "err"); }
    }));
    $$("[data-delete-user]", list).forEach((btn) => btn.addEventListener("click", () => {
      const id = btn.dataset.deleteUser, name = btn.dataset.name;
      EV.confirm({ title: "Delete this user?", body: `<b style="color:var(--text)">${esc(name)}</b> will be permanently removed. This can't be undone.`, confirmText: "Delete User", danger: true,
        onConfirm: async () => { await EV.api.del(`/admin/users/${id}`); EV.toast("User deleted.", "ok"); load(true); } });
    }));
  }
  load(true);
}

function userRow(u) {
  const roleBadge = { user: "", organizer: "gold", admin: "gold" }[u.role];
  return `<div class="row-item" style="align-items:flex-start;flex-wrap:wrap;gap:14px;padding:16px 12px;border-bottom:1px solid var(--border)">
    <div class="grow" style="min-width:220px">
      <b>${esc(u.name)}</b><small style="display:block">${esc(u.email)}</small>
      <small>Joined ${fmtDate(u.created_at, { month: "short", day: "numeric", year: "numeric" })}${u.events_count ? ` · ${u.events_count} event${u.events_count === 1 ? "" : "s"}` : ""}</small>
      ${u.suspended_at ? `<span class="badge soldout" style="margin-top:6px;display:inline-flex">Suspended</span>` : ""}
    </div>
    <span class="status-pill valid ${roleBadge}" style="align-self:center">${esc(u.role)}</span>
    <div class="actions" style="align-self:center">
      ${u.role !== "admin" ? `<button class="btn btn-secondary btn-sm" data-role-btn="admin" data-id="${u.id}">Make admin</button>` : ""}
      ${u.role !== "organizer" ? `<button class="btn btn-secondary btn-sm" data-role-btn="organizer" data-id="${u.id}">Make organizer</button>` : ""}
      ${u.role !== "user" ? `<button class="btn btn-secondary btn-sm" data-role-btn="user" data-id="${u.id}">Make user</button>` : ""}
      <button class="btn btn-secondary btn-sm" data-suspend="${u.suspended_at ? "false" : "true"}" data-id="${u.id}">${u.suspended_at ? "Unsuspend" : "Suspend"}</button>
      <button class="btn icon-btn" data-delete-user="${u.id}" data-name="${esc(u.name)}" aria-label="Delete" style="color:var(--bad)">${icon("trash", 17)}</button>
    </div></div>`;
}

/* ===================================================================== EVENTS (platform-wide) */
EV.page("/admin/events", requireAdminPage(async () => {
  const html = shell("events", `
    <div class="dash-head"><h1>All events</h1></div>
    <div class="filters" style="grid-template-columns:1fr 160px">
      <input id="e-q" placeholder="Search title, venue, city…">
      <select id="e-status"><option value="">Any status</option><option value="active">Active</option><option value="cancelled">Cancelled</option></select>
    </div>
    <div id="e-list" class="mine" style="margin-top:18px">${loading()}</div>
    <div style="text-align:center;margin-top:20px" id="e-more"></div>`);
  setTimeout(() => wireAdminEvents());
  return html;
}));

async function wireAdminEvents() {
  const list = $("#e-list"), more = $("#e-more");
  const state = { q: "", status: "", offset: 0 };
  const LIMIT = 15;
  async function load(reset) {
    if (reset) { state.offset = 0; list.innerHTML = loading(); }
    let data;
    try { data = await EV.api.get("/admin/events" + qs({ q: state.q, status: state.status, limit: LIMIT, offset: state.offset })); }
    catch (e) { list.innerHTML = alertHtml(e.message); return; }
    const rows = data.events.map(adminEventCard).join("");
    list.innerHTML = (state.offset === 0 ? rows : list.innerHTML + rows) || EV.emptyState("No events match that search.");
    state.offset += data.events.length;
    more.innerHTML = state.offset < data.total ? `<button class="btn btn-secondary" id="e-more-btn">Load more</button>` : "";
    const btn = $("#e-more-btn"); if (btn) btn.onclick = () => load(false);
    wireEventActions(load);
  }
  const run = debounce(() => load(true), 300);
  $("#e-q").addEventListener("input", (e) => { state.q = e.target.value; run(); });
  $("#e-status").addEventListener("change", (e) => { state.status = e.target.value; load(true); });
  load(true);
}

function adminEventCard(e) {
  return `<div class="card mine-card">
    ${EV.eventThumb(e, 96)}
    <div>
      <a href="#/events/${e.id}"><h3>${esc(e.title)}</h3></a>
      <ul class="meta"><li class="date">${icon("calendar", 15)}${fmtDate(e.starts_at, { month: "short", day: "numeric", year: "numeric" })}</li><li>${icon("location", 15)}${esc(e.city)}</li></ul>
      <div class="kpis">
        <div><b>${esc(e.organizer_name)}</b>organiser</div>
        <div><span class="badge ${e.status === "cancelled" ? "soldout" : ""}">${esc(e.status)}</span>${e.featured ? ` <span class="badge gold">${icon("spark", 12)}Featured</span>` : ""}</div>
      </div>
    </div>
    <div class="actions">
      <button class="btn btn-secondary btn-sm" data-feature="${e.id}" data-on="${!e.featured}">${e.featured ? "Unfeature" : "Feature"}</button>
      ${e.status === "active" ? `<button class="btn btn-secondary btn-sm" data-cancel="${e.id}" data-title="${esc(e.title)}">Cancel</button>` : ""}
      <button class="btn icon-btn" data-delete-event="${e.id}" data-title="${esc(e.title)}" aria-label="Delete" style="color:var(--bad)">${icon("trash", 17)}</button>
    </div></div>`;
}
function wireEventActions(reload) {
  $$("[data-feature]").forEach((btn) => btn.onclick = async () => {
    try { await EV.api.post(`/admin/events/${btn.dataset.feature}/feature`, { featured: btn.dataset.on === "true" }); reload(true); }
    catch (e) { EV.toast(e.message, "err"); }
  });
  $$("[data-cancel]").forEach((btn) => btn.onclick = () => {
    EV.confirm({ title: "Cancel this event?", body: `<b style="color:var(--text)">${esc(btn.dataset.title)}</b> will be marked cancelled and every outstanding ticket voided. Buyers with a paid order will be emailed.`, confirmText: "Cancel Event", danger: true,
      onConfirm: async () => { await EV.api.post(`/admin/events/${btn.dataset.cancel}/cancel`, {}); EV.toast("Event cancelled.", "ok"); reload(true); } });
  });
  $$("[data-delete-event]").forEach((btn) => btn.onclick = () => {
    EV.confirm({ title: "Delete this event?", body: `<b style="color:var(--text)">${esc(btn.dataset.title)}</b> will be permanently removed. If it has paid buyers, it will be cancelled first.`, confirmText: "Delete Event", danger: true,
      onConfirm: async () => {
        try { await EV.api.del(`/admin/events/${btn.dataset.deleteEvent}`); }
        catch (e) {
          if (e.status === 409) { await EV.api.del(`/admin/events/${btn.dataset.deleteEvent}?force=true`); }
          else throw e;
        }
        EV.toast("Event deleted.", "ok"); reload(true);
      } });
  });
}

/* ===================================================================== ORDERS */
EV.page("/admin/orders", requireAdminPage(async () => {
  const html = shell("orders", `
    <div class="dash-head"><h1>Orders</h1></div>
    <div class="filters" style="grid-template-columns:1fr 160px">
      <input id="o-q" placeholder="Search buyer, email, event, order ref…">
      <select id="o-status"><option value="">Any status</option><option value="paid">Paid</option><option value="pending">Pending</option><option value="expired">Expired</option><option value="failed">Failed</option></select>
    </div>
    <div id="o-list" style="margin-top:18px">${loading()}</div>
    <div style="text-align:center;margin-top:20px" id="o-more"></div>`);
  setTimeout(() => wireOrders());
  return html;
}));

async function wireOrders() {
  const list = $("#o-list"), more = $("#o-more");
  const state = { q: "", status: "", offset: 0 };
  const LIMIT = 20;
  async function load(reset) {
    if (reset) { state.offset = 0; list.innerHTML = loading(); }
    let data;
    try { data = await EV.api.get("/admin/orders" + qs({ q: state.q, status: state.status, limit: LIMIT, offset: state.offset })); }
    catch (e) { list.innerHTML = alertHtml(e.message); return; }
    const rows = data.orders.map(orderRow).join("");
    list.innerHTML = (state.offset === 0 ? rows : list.innerHTML + rows) || EV.emptyState("No orders match that search.");
    state.offset += data.orders.length;
    more.innerHTML = state.offset < data.total ? `<button class="btn btn-secondary" id="o-more-btn">Load more</button>` : "";
    const btn = $("#o-more-btn"); if (btn) btn.onclick = () => load(false);
    wireOrderActions(load);
  }
  const run = debounce(() => load(true), 300);
  $("#o-q").addEventListener("input", (e) => { state.q = e.target.value; run(); });
  $("#o-status").addEventListener("change", (e) => { state.status = e.target.value; load(true); });
  load(true);
}

const STATUS_TAG = { paid: "ok", pending: "warn", expired: "bad", failed: "bad" };
function orderRow(o) {
  const remaining = o.total_cents - o.refunded_cents;
  return `<div class="row-item" style="align-items:flex-start;flex-wrap:wrap;gap:14px;padding:16px 12px;border-bottom:1px solid var(--border)">
    <div class="grow" style="min-width:240px">
      <b>${esc(o.buyer_name)}</b><small style="display:block">${esc(o.buyer_email)}</small>
      <small><a href="#/events/${o.event_id}" style="color:inherit">${esc(o.event_title)}</a> · ${esc(o.public_ref)}</small>
    </div>
    <div style="text-align:right">
      <span class="tag ${STATUS_TAG[o.status] || "warn"}">${esc(o.status)}</span>
      <div style="font-family:var(--head);font-weight:700;color:var(--gold);margin-top:4px">${money(o.total_cents, o.currency)}</div>
      ${o.refunded_cents ? `<small>${money(o.refunded_cents, o.currency)} refunded</small>` : ""}
    </div>
    <div class="actions" style="align-self:center">
      ${o.status === "paid" ? `<button class="btn btn-secondary btn-sm" data-tickets="${o.id}" data-buyer="${esc(o.buyer_name)}">Tickets</button>` : ""}
      ${o.status === "paid" ? `<button class="btn btn-secondary btn-sm" data-resend="${o.id}">Resend</button>` : ""}
      ${o.status === "paid" && remaining > 0 ? `<button class="btn btn-secondary btn-sm" data-refund="${o.id}" data-remaining="${remaining}" data-currency="${o.currency}">Refund</button>` : ""}
    </div></div>`;
}
function wireOrderActions(reload) {
  $$("[data-resend]").forEach((btn) => btn.onclick = async () => {
    btn.disabled = true;
    try { await EV.api.post(`/admin/orders/${btn.dataset.resend}/resend`); EV.toast("Email sent.", "ok"); }
    catch (e) { EV.toast(e.message, "err"); }
    btn.disabled = false;
  });
  $$("[data-tickets]").forEach((btn) => btn.onclick = () => openTicketsModal(btn.dataset.tickets, btn.dataset.buyer));
  $$("[data-refund]").forEach((btn) => btn.onclick = () => openRefundModal(btn.dataset.refund, parseInt(btn.dataset.remaining, 10), btn.dataset.currency, reload));
}
function openTicketsModal(orderId, buyer) {
  const m = EV.modal(`
    <div class="modal-head"><h2>Tickets for ${esc(buyer)}</h2><button class="icon-btn" data-x>${icon("close")}</button></div>
    <p style="margin:8px 0 14px">Void a lost or stolen ticket, issue a fresh one with a new code, or put a wrongly scanned ticket back to valid.</p>
    <div id="tk-list">${loading()}</div>`);
  $("[data-x]", m.node).onclick = m.close;
  const TAG = { valid: ["ok", "Valid"], used: ["warn", "Used"], void: ["bad", "Void"] };
  async function refresh() {
    const box = $("#tk-list", m.node);
    let data;
    try { data = await EV.api.get(`/admin/orders/${orderId}/tickets`); } catch (e) { box.innerHTML = alertHtml(e.message); return; }
    box.innerHTML = `<ul class="log">${data.tickets.map((t) => {
      const [cls, label] = TAG[t.status] || ["warn", t.status];
      return `<li style="align-items:flex-start;flex-wrap:wrap;gap:10px">
        <span style="min-width:0"><b>#${t.seq} · ${esc(t.tier_name)}</b>${t.is_reissue ? ' <small style="color:var(--gold)">reissued</small>' : ""}
          <small style="display:block;font-family:Consolas,monospace;word-break:break-all">${esc(t.token)}</small>
          ${t.status === "void" && t.void_reason ? `<small style="display:block">${esc(t.void_reason)}</small>` : ""}
          ${t.status === "used" && t.used_at ? `<small style="display:block">Scanned ${fmtWhen(t.used_at)}</small>` : ""}</span>
        <span style="display:flex;gap:6px;align-items:center;flex-wrap:wrap"><span class="tag ${cls}">${label}</span>
          ${t.status !== "void" ? `<button class="btn btn-secondary btn-sm" data-act="reissue" data-token="${esc(t.token)}">Reissue</button><button class="btn btn-danger btn-sm" data-act="void" data-token="${esc(t.token)}">Void</button>` : ""}
          ${t.status === "used" ? `<button class="btn btn-secondary btn-sm" data-act="reset" data-token="${esc(t.token)}">Reset to valid</button>` : ""}</span></li>`;
    }).join("")}</ul>`;
    $$("[data-act]", box).forEach((btn) => btn.onclick = () => act(btn.dataset.act, btn.dataset.token));
  }
  function act(kind, token) {
    const copy = {
      void: ["Void this ticket?", "The code stops working immediately. This can't be undone.", "Void Ticket", true],
      reissue: ["Reissue this ticket?", "The old code is voided and a brand-new code takes its place.", "Reissue", false],
      reset: ["Reset this ticket to valid?", "Use this when a ticket was scanned by mistake. It can be scanned once more.", "Reset Ticket", false],
    }[kind];
    EV.confirm({ title: copy[0], body: copy[1], confirmText: copy[2], danger: copy[3],
      onConfirm: async () => {
        const res = await EV.api.post(`/admin/tickets/${encodeURIComponent(token)}/${kind}`, kind === "reset" ? undefined : {});
        EV.toast(kind === "reissue" ? `New ticket issued: ${res.token}` : kind === "void" ? "Ticket voided." : "Ticket reset.", "ok");
        refresh();
      } });
  }
  refresh();
}
function openRefundModal(orderId, remainingCents, currency, reload) {
  const m = EV.modal(`
    <div class="modal-head"><h2>Refund order</h2><button class="icon-btn" data-x>${icon("close")}</button></div>
    <p style="margin:8px 0 16px">Up to ${money(remainingCents, currency)} can be refunded on this order.</p>
    <div id="refund-alert"></div>
    <div class="field"><label for="refund-amt">Amount to refund</label>
      <div class="money" style="position:relative"><span style="position:absolute;left:14px;top:50%;transform:translateY(-50%);color:var(--muted)">$</span>
      <input id="refund-amt" type="number" min="0.01" step="0.01" style="padding-left:30px" value="${(remainingCents / 100).toFixed(2)}"></div></div>
    <div class="btns"><button class="btn btn-ghost" data-cancel>Cancel</button><button class="btn btn-primary" data-ok>Refund</button></div>`);
  $("[data-x]", m.node).onclick = m.close; $("[data-cancel]", m.node).onclick = m.close;
  $("[data-ok]", m.node).onclick = async () => {
    const btn = $("[data-ok]", m.node); const alertBox = $("#refund-alert", m.node); alertBox.innerHTML = "";
    const cents = Math.round(parseFloat($("#refund-amt", m.node).value) * 100);
    if (!cents || cents <= 0) { alertBox.innerHTML = alertHtml("Enter an amount greater than zero."); return; }
    btn.disabled = true; const orig = btn.innerHTML; btn.innerHTML = '<span class="spinner"></span>';
    try { await EV.api.post(`/admin/orders/${orderId}/refund`, { amount_cents: cents }); EV.toast("Refund issued.", "ok"); m.close(); reload(true); }
    catch (e) { alertBox.innerHTML = alertHtml(e.message); btn.disabled = false; btn.innerHTML = orig; }
  };
}

/* ===================================================================== SCANS */
EV.page("/admin/scans", requireAdminPage(async () => {
  const html = shell("scans", `
    <div class="dash-head"><h1>Scan activity</h1></div>
    <div class="filters" style="grid-template-columns:1fr">
      <select id="s-result"><option value="">Any result</option><option value="ok">Admitted</option><option value="already_used">Duplicate</option><option value="wrong_event">Wrong event</option><option value="void">Void</option><option value="invalid">Invalid</option></select>
    </div>
    <div class="card panel" style="margin-top:18px"><ul class="log" id="s-list">${loading()}</ul></div>
    <div style="text-align:center;margin-top:20px" id="s-more"></div>`);
  setTimeout(() => wireScansPage());
  return html;
}));

const SCAN_TAG = { ok: ["ok", "Admitted"], already_used: ["warn", "Duplicate"], wrong_event: ["warn", "Wrong event"], void: ["bad", "Void"], invalid: ["bad", "Invalid"] };
async function wireScansPage() {
  const list = $("#s-list"), more = $("#s-more");
  const state = { result: "", offset: 0 };
  const LIMIT = 25;
  async function load(reset) {
    if (reset) { state.offset = 0; list.innerHTML = loading(); }
    let data;
    try { data = await EV.api.get("/admin/scans" + qs({ result: state.result, limit: LIMIT, offset: state.offset })); }
    catch (e) { list.innerHTML = alertHtml(e.message); return; }
    const rows = data.scans.map((s) => {
      const [tag, label] = SCAN_TAG[s.result] || ["bad", s.result];
      return `<li><span>${s.holder_name ? esc(s.holder_name) + (s.tier_name ? " · " + esc(s.tier_name) : "") : "Unknown code"} — <a href="#/events/${s.event_id}" style="color:var(--muted)">${esc(s.event_title)}</a> <small style="color:var(--muted)">${new Date(s.created_at).toLocaleString()}</small></span><span class="tag ${tag}">${label}</span></li>`;
    }).join("");
    list.innerHTML = (state.offset === 0 ? rows : list.innerHTML + rows) || `<li style="color:var(--muted)">No scans match that filter.</li>`;
    state.offset += data.scans.length;
    more.innerHTML = state.offset < data.total ? `<button class="btn btn-secondary" id="s-more-btn">Load more</button>` : "";
    const btn = $("#s-more-btn"); if (btn) btn.onclick = () => load(false);
  }
  $("#s-result").addEventListener("change", (e) => { state.result = e.target.value; load(true); });
  load(true);
}

/* ===================================================================== ORGANIZER REQUESTS */
EV.page("/admin/requests", requireAdminPage(async () => {
  const html = shell("requests", `
    <div class="dash-head"><h1>Organizer requests</h1></div>
    <div class="filters" style="grid-template-columns:200px">
      <select id="r-status"><option value="pending">Pending</option><option value="approved">Approved</option><option value="denied">Denied</option><option value="all">All</option></select>
    </div>
    <div id="r-list" class="list" style="margin-top:18px">${loading()}</div>`);
  setTimeout(() => wireRequests());
  return html;
}));

async function wireRequests() {
  const list = $("#r-list");
  async function load() {
    list.innerHTML = loading();
    const status = $("#r-status").value;
    let data;
    try { data = await EV.api.get("/admin/organizer-requests" + qs({ status })); }
    catch (e) { list.innerHTML = alertHtml(e.message); return; }
    list.innerHTML = data.requests.map(requestRow).join("") || EV.emptyState("No requests here.");
    $$("[data-approve]", list).forEach((btn) => btn.onclick = async () => {
      try { await EV.api.post(`/admin/organizer-requests/${btn.dataset.approve}/approve`); EV.toast("Approved.", "ok"); load(); }
      catch (e) { EV.toast(e.message, "err"); }
    });
    $$("[data-deny]", list).forEach((btn) => btn.onclick = async () => {
      try { await EV.api.post(`/admin/organizer-requests/${btn.dataset.deny}/deny`, {}); EV.toast("Denied.", "ok"); load(); }
      catch (e) { EV.toast(e.message, "err"); }
    });
  }
  $("#r-status").addEventListener("change", load);
  load();
}
function requestRow(r) {
  return `<div class="row-item" style="align-items:flex-start;flex-wrap:wrap;gap:14px;padding:16px 12px;border-bottom:1px solid var(--border)">
    <div class="grow" style="min-width:240px">
      <b>${esc(r.user_name)}</b><small style="display:block">${esc(r.user_email)}</small>
      ${r.message ? `<small style="display:block;margin-top:4px;color:var(--text)">"${esc(r.message)}"</small>` : ""}
      <small>${new Date(r.created_at).toLocaleDateString()}${r.reviewed_by_name ? ` · reviewed by ${esc(r.reviewed_by_name)}` : ""}</small>
    </div>
    <span class="tag ${r.status === "approved" ? "ok" : r.status === "denied" ? "bad" : "warn"}">${esc(r.status)}</span>
    ${r.status === "pending" ? `<div class="actions" style="align-self:center"><button class="btn btn-secondary btn-sm" data-approve="${r.id}">Approve</button><button class="btn btn-secondary btn-sm" data-deny="${r.id}">Deny</button></div>` : ""}
  </div>`;
}

/* ===================================================================== MESSAGES */
EV.page("/admin/messages", requireAdminPage(async () => {
  const html = shell("messages", `<div class="dash-head"><h1>Contact messages</h1></div><div id="m-list" class="list">${loading()}</div>`);
  setTimeout(() => wireMessages());
  return html;
}));
async function wireMessages() {
  const list = $("#m-list");
  async function load() {
    let data;
    try { data = await EV.api.get("/admin/messages?limit=50"); } catch (e) { list.innerHTML = alertHtml(e.message); return; }
    list.innerHTML = data.messages.map((m) => `<div class="row-item" style="align-items:flex-start;flex-wrap:wrap;gap:14px;padding:16px 12px;border-bottom:1px solid var(--border)">
      <div class="grow" style="min-width:240px"><b>${esc(m.name)}</b><small style="display:block">${esc(m.email)}</small><p style="margin-top:6px">${esc(m.message)}</p><small>${new Date(m.created_at).toLocaleString()}</small></div>
      <button class="btn icon-btn" data-del-msg="${m.id}" aria-label="Delete" style="color:var(--bad)">${icon("trash", 17)}</button>
    </div>`).join("") || EV.emptyState("No messages yet.");
    $$("[data-del-msg]", list).forEach((btn) => btn.onclick = async () => { await EV.api.del(`/admin/messages/${btn.dataset.delMsg}`); load(); });
  }
  load();
}

/* ===================================================================== SETTINGS */
EV.page("/admin/settings", requireAdminPage(async () => {
  const html = shell("settings", `<div class="dash-head"><h1>System settings</h1></div><div id="sys-list">${loading()}</div>`);
  setTimeout(() => wireSettings());
  return html;
}));
async function wireSettings() {
  const box = $("#sys-list");
  let s;
  try { s = await EV.api.get("/admin/system"); } catch (e) { box.innerHTML = alertHtml(e.message); return; }
  box.innerHTML = `<div class="panel">
    <div class="row-item"><div class="grow"><b>Payments</b><small>How checkout is currently processed</small></div><span class="tag ${s.payments_mode === "stripe" ? "ok" : "warn"}">${s.payments_mode === "stripe" ? "Stripe" : "Demo mode"}</span></div>
    <div class="row-item"><div class="grow"><b>Email</b><small>Ticket delivery via Resend</small></div><span class="tag ${s.email_enabled ? "ok" : "warn"}">${s.email_enabled ? "Configured" : "Not configured"}</span></div>
    <div class="row-item"><div class="grow"><b>Stripe webhook</b><small>Reliable ticket issuance if a buyer doesn't return to the site</small></div><span class="tag ${s.stripe_webhook_configured ? "ok" : "warn"}">${s.stripe_webhook_configured ? "Configured" : "Not configured"}</span></div>
  </div>`;
}

})(window.EV);
