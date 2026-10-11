/* Event Vault: tiny hash router + API client + shared UI. No build step, no framework. */
(function (global) {
"use strict";

const EV = {};
global.EV = EV;

/* ------------------------------------------------------------------ utils */
const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (cents, currency) => new Intl.NumberFormat("en-US", { style: "currency", currency: (currency || "usd").toUpperCase(), maximumFractionDigits: (cents % 100 === 0) ? 0 : 2 }).format((cents || 0) / 100);
const h = (strings, ...vals) => strings.reduce((out, s, i) => out + s + (i < vals.length ? vals[i] : ""), "");
function el(html) { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; }
function qs(params) { const p = new URLSearchParams(); Object.entries(params || {}).forEach(([k, v]) => { if (v !== "" && v != null && v !== false) p.set(k, v); }); const s = p.toString(); return s ? "?" + s : ""; }
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
function fmtDate(iso, opts) { return new Date(iso).toLocaleDateString("en-US", opts || { weekday: "short", month: "short", day: "numeric", year: "numeric" }); }
function fmtTime(iso) { return new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }); }
function fmtWhen(iso) { return fmtDate(iso) + " · " + fmtTime(iso); }
function relTime(iso) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 45) return "just now";
  if (s < 3600) return Math.round(s / 60) + "m ago";
  if (s < 86400) return Math.round(s / 3600) + "h ago";
  return Math.round(s / 86400) + "d ago";
}
EV.util = { $, $$, esc, money, h, el, qs, debounce, fmtDate, fmtTime, fmtWhen, relTime };

/* ------------------------------------------------------------------ icons (all inline, no icon font) */
const ICONS = {
  search: '<path d="M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16Zm10 2-5.6-5.6"/>',
  location: '<path d="M12 22s7-7.6 7-12.5A7 7 0 0 0 5 9.5C5 14.4 12 22 12 22Z"/><circle cx="12" cy="9.5" r="2.5"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M8 3v4M16 3v4M3 10h18"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>',
  ticket: '<path d="M3 9a3 3 0 0 1 0 6v2a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2Z"/><path d="M13 5v2M13 17v2M13 11v2"/>',
  chevronR: '<path d="M9 6l6 6-6 6"/>',
  chevronD: '<path d="M6 9l6 6 6-6"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 20c1.5-4.5 5-6 8-6s6.5 1.5 8 6"/>',
  logout: '<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 17l5-5-5-5M15 12H3"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
  eyeOff: '<path d="M3 3l18 18"/><path d="M10.6 5.2A10.4 10.4 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4.1M6.6 6.6A16.7 16.7 0 0 0 2 12s3.5 7 10 7c1.4 0 2.7-.3 3.9-.8"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  chart: '<path d="M4 20V10M12 20V4M20 20v-7"/>',
  share: '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="M8.6 10.5 15.4 6.5M8.6 13.5l6.8 4"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m4 7 8 6 8-6"/>',
  phone: '<path d="M6.6 10.8a15 15 0 0 0 6.6 6.6l2.2-2.2a1.5 1.5 0 0 1 1.5-.4c1.1.4 2.3.6 3.6.6a1.5 1.5 0 0 1 1.5 1.5V20a1.5 1.5 0 0 1-1.5 1.5C10.7 21.5 2.5 13.3 2.5 3.5A1.5 1.5 0 0 1 4 2h3.1a1.5 1.5 0 0 1 1.5 1.5c0 1.3.2 2.5.6 3.6a1.5 1.5 0 0 1-.4 1.5Z"/>',
  spark: '<path d="M12 3v5M12 16v5M3 12h5M16 12h5M5.6 5.6l3.5 3.5M14.9 14.9l3.5 3.5M18.4 5.6l-3.5 3.5M9.1 14.9l-3.5 3.5"/>',
  upload: '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="m4.5 18 5-5 3 2.7L18 10l1.5 2"/>',
  camera: '<path d="M4 8a2 2 0 0 1 2-2h1.5l1-1.6h7l1 1.6H18a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z"/><circle cx="12" cy="13" r="3.5"/>',
  bolt: '<path d="M13 2 4 14h6l-1 8 9-12h-6l1-8Z"/>',
  alert: '<circle cx="12" cy="12" r="9"/><path d="M12 8v5"/><circle cx="12" cy="16.2" r=".2" fill="currentColor" stroke="none"/>',
  ban: '<circle cx="12" cy="12" r="9"/><path d="m5.5 5.5 13 13"/>',
  music: '<path d="M9 18V5l10-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="16" cy="16" r="3"/>',
  briefcase: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12h18"/>',
  heart2: '<path d="M12 20s-7.5-4.7-9.7-9.4C.7 6.9 3 3.5 6.6 3.5c2 0 3.6 1 5.4 3 1.8-2 3.4-3 5.4-3 3.6 0 5.9 3.4 4.3 7.1C19.5 15.3 12 20 12 20Z"/>',
  trophy: '<path d="M8 4h8v5a4 4 0 0 1-8 0Z"/><path d="M8 5H5a3 3 0 0 0 3 5M16 5h3a3 3 0 0 1-3 5M10 15v3M14 15v3M8 21h8"/>',
  tool: '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2-2Z"/>',
  festival: '<path d="M4 20 9 8l3 6 2-4 6 10Z"/>',
  party: '<path d="M4 20 16 8M14 4l2 2M17 2l2 2M4 20l2-6 4 4Z"/><circle cx="19" cy="9" r="1"/><circle cx="8" cy="5" r="1"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="10" y="10" width="4" height="4"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  minus: '<path d="M5 12h14"/>',
  arrowUp: '<path d="M12 19V5M6 11l6-6 6 6"/>',
  google: '<path d="M21.6 12.2c0-.7-.1-1.4-.2-2H12v3.9h5.4a4.6 4.6 0 0 1-2 3v2.5h3.2c1.9-1.7 3-4.3 3-7.4Z" fill="#7C3AED" stroke="none"/><path d="M12 22c2.7 0 5-.9 6.6-2.4l-3.2-2.5c-.9.6-2 1-3.4 1-2.6 0-4.8-1.7-5.6-4.1H3.1v2.6A10 10 0 0 0 12 22Z" fill="#EC4899" stroke="none"/><path d="M6.4 14c-.2-.6-.3-1.3-.3-2s.1-1.4.3-2V7.4H3.1a10 10 0 0 0 0 9.2Z" fill="#F59E0B" stroke="none"/><path d="M12 5.9c1.5 0 2.8.5 3.8 1.5l2.8-2.8A10 10 0 0 0 3.1 7.4L6.4 10c.8-2.4 3-4.1 5.6-4.1Z" fill="#F8FAFC" stroke="none"/>',
};
function icon(name, size) {
  const s = size || 20;
  return `<svg class="ic" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ""}</svg>`;
}
EV.icon = icon;

const CAT_ICON = { Music: "music", Conferences: "briefcase", Weddings: "heart2", Sports: "trophy", Workshops: "tool", Festivals: "festival", Parties: "party", Technology: "cpu" };
const CAT_COLORS = { Music: ["#7C3AED66", "#EC489966"], Conferences: ["#7C3AED55", "#38BDF855"], Weddings: ["#EC489966", "#F59E0B55"], Sports: ["#F59E0B55", "#7C3AED55"], Workshops: ["#38BDF855", "#7C3AED55"], Festivals: ["#EC489966", "#7C3AED66"], Parties: ["#EC489966", "#F59E0B66"], Technology: ["#7C3AED66", "#38BDF866"] };
EV.catIcon = (c) => CAT_ICON[c] || "spark";
EV.catColors = (c) => CAT_COLORS[c] || ["#7C3AED55", "#EC489955"];

/* ------------------------------------------------------------------ API client */
async function api(method, path, body) {
  const opts = { method, headers: {}, credentials: "same-origin" };
  if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  let res;
  try {
    res = await fetch("/api" + path, opts);
  } catch {
    throw new ApiError("Can't reach the server. Check your connection and try again.", 0);
  }
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) throw new ApiError((data && data.detail) || `Something went wrong (${res.status}).`, res.status, data);
  return data;
}
class ApiError extends Error { constructor(message, status, data) { super(message); this.status = status; this.data = data; } }
EV.api = { get: (p) => api("GET", p), post: (p, b) => api("POST", p, b), put: (p, b) => api("PUT", p, b), del: (p) => api("DELETE", p) };
EV.ApiError = ApiError;

/* ------------------------------------------------------------------ session */
EV.state = { user: null, meta: null, ready: false };
EV.renderAuthSlot = renderAuthSlot;
async function refreshUser() { try { EV.state.user = (await EV.api.get("/auth/me")).user; } catch { EV.state.user = null; } renderAuthSlot(); }
async function refreshMeta() { try { EV.state.meta = await EV.api.get("/meta"); } catch { EV.state.meta = { categories: [], cities: [], currency: "usd" }; } }
EV.requireLogin = function (message) {
  if (EV.state.user) return true;
  EV.toast(message || "Please log in to continue.", "err");
  location.hash = "#/login?next=" + encodeURIComponent(location.hash.slice(1) || "/");
  return false;
};
/* Role gate for a whole page: EV.page("/admin", requireRolePage(["admin"], async () => {...})).
   Unlike requireLogin (which redirects to /login), a logged-in user with the wrong role isn't sent
   anywhere — they just see an inline "you don't have access" message, since redirecting them away
   from a page they typed or clicked into is more disorienting than explaining why it's blocked. */
EV.requireRolePage = function (roles, fn) {
  return async (params, query) => {
    if (!EV.state.user) { EV.requireLogin(); return `<div class="container" style="padding:80px 0;text-align:center"><span class="spinner lg"></span></div>`; }
    if (!roles.includes(EV.state.user.role)) return EV.accessDenied(roles);
    return fn(params, query);
  };
};
EV.accessDenied = function (roles) {
  const needs = roles.includes("admin") && roles.length === 1 ? "an administrator" : "an organizer or administrator";
  return `<div class="container notfound">
    <div class="ic-wrap" style="width:80px;height:80px;border-radius:22px;background:rgba(124,58,237,.16);display:grid;place-items:center;color:#C4B5FD">${icon("ban", 40)}</div>
    <h1>You don't have access to this page</h1><p style="max-width:44ch">This page is only available to ${needs}.</p>
    <div class="hero-cta" style="justify-content:center">
      ${EV.state.user && EV.state.user.role === "user" && roles.includes("organizer") ? `<a class="btn btn-primary" href="#/create">${icon("plus", 18)}Request organizer access</a>` : ""}
      <a class="btn ${EV.state.user && EV.state.user.role === "user" && roles.includes("organizer") ? "btn-secondary" : "btn-primary"}" href="#/">${icon("chevronR", 18)}Back to Event Vault</a></div></div>`;
};

function renderAuthSlot() {
  const slot = $("#auth-slot");
  if (EV.state.user) {
    const initials = EV.state.user.name.trim().split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
    const role = EV.state.user.role || "user";
    const roleLink = role === "admin"
      ? `<a href="#/admin" role="menuitem">${icon("bolt", 17)}Admin</a>`
      : role === "user"
        ? `<a href="#/create" role="menuitem">${icon("plus", 17)}Request organizer access</a>`
        : "";
    slot.innerHTML = `<div class="account" id="account-menu">
      <button class="avatar" id="avatar-btn" aria-haspopup="true" aria-expanded="false">${esc(initials)}</button>
      <div class="menu" role="menu">
        <div class="who"><b>${esc(EV.state.user.name)}</b><span>${esc(EV.state.user.email)}</span></div>
        <a href="#/dashboard" role="menuitem">${icon("chart", 17)}Dashboard</a>
        <a href="#/dashboard/tickets" role="menuitem">${icon("ticket", 17)}My tickets</a>
        ${role !== "user" ? `<a href="#/create" role="menuitem">${icon("plus", 17)}Create event</a>` : ""}
        ${roleLink}
        <button type="button" id="logout-btn" role="menuitem">${icon("logout", 17)}Log out</button>
      </div></div>`;
    $("#avatar-btn").onclick = (e) => { e.stopPropagation(); toggleAccountMenu(); };
    $("#logout-btn").onclick = async () => { await EV.api.post("/auth/logout"); EV.state.user = null; renderAuthSlot(); EV.toast("Logged out."); if (location.hash.startsWith("#/dashboard")) location.hash = "#/"; };
  } else {
    slot.innerHTML = `<a href="#/login" class="btn btn-ghost btn-sm">Log in</a>`;
  }
  buildMobilePanel();
}
function toggleAccountMenu(force) {
  const m = $("#account-menu"); if (!m) return;
  const open = force != null ? force : !m.classList.contains("open");
  m.classList.toggle("open", open);
  $("#avatar-btn").setAttribute("aria-expanded", open);
}
document.addEventListener("click", (e) => { if (!e.target.closest("#account-menu")) toggleAccountMenu(false); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") toggleAccountMenu(false); });

/* ------------------------------------------------------------------ nav: active link, scroll, mobile menu */
function buildMobilePanel() {
  const p = $("#mobile-panel");
  const items = [["#/", "Home"], ["#/events", "Events"], ["#/categories", "Categories"], ["#/about", "About"], ["#/contact", "Contact"]];
  const mobileAdminLink = EV.state.user && EV.state.user.role === "admin" ? `<a href="#/admin">${icon("bolt", 17)}Admin</a>` : "";
  let extra = EV.state.user
    ? `<a href="#/dashboard">Dashboard</a><a href="#/dashboard/tickets">My tickets</a>${mobileAdminLink}<a href="#/create" class="btn btn-primary btn-sm" style="justify-content:center;margin-top:10px">${icon("plus", 17)}Create event</a><button type="button" id="m-logout" style="text-align:left">${icon("logout", 17)}Log out</button>`
    : `<a href="#/login">Log in</a><a href="#/create" class="btn btn-primary btn-sm" style="justify-content:center;margin-top:10px">${icon("plus", 17)}Create event</a>`;
  p.innerHTML = items.map(([href, label]) => `<a href="${href}" data-nav="${href === "#/" ? "home" : href.slice(3)}">${label}</a>`).join("") + extra;
  const m = $("#m-logout"); if (m) m.onclick = () => $("#logout-btn").click();
  $$("#mobile-panel a").forEach((a) => a.addEventListener("click", () => setMenu(false)));
}
function setMenu(open) {
  $("#nav").classList.toggle("open", open);
  $("#btn-menu").setAttribute("aria-expanded", open);
}
window.addEventListener("scroll", () => $("#nav").classList.toggle("scrolled", window.scrollY > 8), { passive: true });

function markActiveNav(section) {
  $$("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === section));
}

/* ------------------------------------------------------------------ toasts */
let toastSeq = 0;
EV.toast = function (message, kind) {
  const id = "t" + ++toastSeq;
  const box = $("#toasts");
  const node = el(`<div class="toast ${kind || ""}" id="${id}" role="status">${icon(kind === "ok" ? "check" : kind === "err" ? "alert" : "bolt", 18)}<span>${esc(message)}</span></div>`);
  box.appendChild(node);
  setTimeout(() => { node.classList.add("leave"); setTimeout(() => node.remove(), 260); }, 4200);
};

/* ------------------------------------------------------------------ modal + confirm */
EV.modal = function (innerHtml, opts) {
  const root = $("#overlay-root");
  const ov = el(`<div class="overlay" role="dialog" aria-modal="true"><div class="modal">${innerHtml}</div></div>`);
  root.appendChild(ov);
  const close = () => { ov.remove(); document.removeEventListener("keydown", onKey); };
  function onKey(e) { if (e.key === "Escape" && (!opts || opts.escClose !== false)) close(); }
  document.addEventListener("keydown", onKey);
  ov.addEventListener("click", (e) => { if (e.target === ov && (!opts || opts.backdropClose !== false)) close(); });
  return { node: ov.firstElementChild, close };
};
EV.confirm = function ({ title, body, confirmText, danger, onConfirm }) {
  const m = EV.modal(`
    <div class="modal-head"><h2>${esc(title)}</h2><button class="icon-btn" data-x>${icon("close")}</button></div>
    <p style="margin-top:8px">${body}</p>
    <div class="btns"><button class="btn btn-ghost" data-cancel>Cancel</button><button class="btn ${danger ? "btn-danger" : "btn-primary"}" data-ok>${esc(confirmText || "Confirm")}</button></div>`);
  $("[data-x]", m.node).onclick = m.close; $("[data-cancel]", m.node).onclick = m.close;
  $("[data-ok]", m.node).onclick = async () => { const btn = $("[data-ok]", m.node); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>'; try { await onConfirm(); m.close(); } catch (e) { EV.toast(e.message || "That didn't work.", "err"); btn.disabled = false; btn.innerHTML = esc(confirmText || "Confirm"); } };
};

/* ------------------------------------------------------------------ global search */
function openSearch() {
  const m = EV.modal(`<div class="search-box" style="border-radius:20px">
    <div class="bar">${icon("search")}<input id="gs-input" placeholder="Search events, cities, venues…" autocomplete="off"><button class="icon-btn" data-x>${icon("close")}</button></div>
    <div class="res" id="gs-res"><p class="hintline">Type to search across every event.</p></div></div>`, { backdropClose: true });
  m.node.parentElement.classList.add("search-ov");
  $("[data-x]", m.node).onclick = m.close;
  const input = $("#gs-input", m.node); input.focus();
  const res = $("#gs-res", m.node);
  const run = debounce(async (val) => {
    if (!val.trim()) { res.innerHTML = '<p class="hintline">Type to search across every event.</p>'; return; }
    res.innerHTML = '<p class="hintline"><span class="spinner"></span></p>';
    try {
      const data = await EV.api.get("/events" + qs({ q: val, limit: 8 }));
      res.innerHTML = data.events.length ? data.events.map((e) => `
        <a href="#/events/${e.id}" data-close>
          ${EV.eventThumb(e, 46)}
          <span style="min-width:0"><b style="display:block;color:var(--text);font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(e.title)}</b>
          <small style="color:var(--muted)">${esc(e.category)} · ${esc(e.city)} · ${fmtDate(e.starts_at, { month: "short", day: "numeric" })}</small></span></a>`).join("")
        : `<p class="hintline">No events match "${esc(val)}".</p>`;
      $$("[data-close]", res).forEach((a) => a.addEventListener("click", m.close));
    } catch { res.innerHTML = '<p class="hintline">Search failed. Try again.</p>'; }
  }, 260);
  input.addEventListener("input", () => run(input.value));
}
$("#btn-search").addEventListener("click", openSearch);
document.addEventListener("keydown", (e) => { if ((e.metaKey || e.ctrlKey) && e.key === "k") { e.preventDefault(); openSearch(); } });
$("#btn-menu").addEventListener("click", () => setMenu(!$("#nav").classList.contains("open")));
$("#btn-create").innerHTML = icon("plus", 17) + "Create Event";

/* ------------------------------------------------------------------ shared render helpers */
EV.eventThumb = function (e, size) {
  const s = size || 240;
  if (e.image_url) return `<div class="media" style="width:${size ? s + "px" : "100%"};height:${size ? s + "px" : "100%"};border-radius:${size ? "10px" : "0"};flex:none"><img src="${e.image_url}" alt="" loading="lazy" width="${s}" height="${s}"></div>`;
  const [a, b] = EV.catColors(e.category);
  return `<div class="media" style="width:${size ? s + "px" : "100%"};height:${size ? s + "px" : "100%"};border-radius:${size ? "10px" : "0"};flex:none">
    <div class="cover" style="--a:${a};--b:${b};height:100%"><span class="cover-ic">${icon(EV.catIcon(e.category), 100)}</span></div></div>`;
};

EV.eventCard = function (e) {
  const soldOut = e.sold_out;
  const priceLabel = e.max_price_cents === 0 ? "Free" : (e.min_price_cents === e.max_price_cents ? money(e.min_price_cents, e.currency || EV.state.meta?.currency) : "From " + money(e.min_price_cents, e.currency || EV.state.meta?.currency));
  return `<article class="card ev-card">
    <div class="media">${e.image_url ? `<img src="${e.image_url}" alt="" loading="lazy">` : (() => { const [a, b] = EV.catColors(e.category); return `<div class="cover" style="--a:${a};--b:${b}"><span class="cover-ic">${icon(EV.catIcon(e.category), 140)}</span></div>`; })()}
      <div class="badges"><span class="badge">${esc(e.category)}</span>${e.featured ? `<span class="badge gold">${icon("spark", 14)}Featured</span>` : ""}${soldOut ? `<span class="badge soldout">Sold out</span>` : ""}</div></div>
    <div class="ev-body">
      <h3>${esc(e.title)}</h3>
      <ul class="meta">
        <li class="date">${icon("calendar", 16)}${fmtDate(e.starts_at, { month: "short", day: "numeric", year: "numeric" })}</li>
        <li>${icon("clock", 16)}${fmtTime(e.starts_at)}</li>
        <li>${icon("location", 16)}${esc(e.venue)}, ${esc(e.city)}</li>
      </ul>
      <p class="desc">${esc(e.short_description)}</p>
    </div>
    <div class="stub"><span class="price">${priceLabel}</span><a class="btn btn-secondary btn-sm btn-details" href="#/events/${e.id}">View Details${icon("chevronR", 16)}</a></div>
  </article>`;
};

EV.skeletons = (n) => Array.from({ length: n || 3 }).map(() => `<div class="skel"></div>`).join("");

/* ------------------------------------------------------------------ shared stat card (dashboard tiles) */
/* value: a number (animated count-up), a string (shown as-is), or null + opts.cents (animated currency). */
EV.statCard = function (ic, label, value, opts) {
  opts = opts || {};
  const goldCls = opts.gold ? "gold" : "";
  let body;
  if (opts.cents != null) body = `<b class="${goldCls}" data-money="${opts.cents}">${money(0)}</b>`;
  else if (typeof value === "number") body = `<b class="${goldCls}" data-count="${value}">0</b>`;
  else body = `<b class="${goldCls}">${esc(String(value))}</b>`;
  return `<div class="stat"><div class="top"><span class="ic-wrap">${icon(ic, 19)}</span></div>${body}<span>${esc(label)}</span></div>`;
};

/* ------------------------------------------------------------------ dynamic animations: scroll-reveal + count-up */
const reducedMotion = () => window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const REVEAL_SELECTOR = ".ev-card, .cat-card, .stat, .feature, .step, .fact, .mine-card, .tix-card, .feat-main, .promo";
let revealObserver = null;
function getRevealObserver() {
  if (revealObserver) return revealObserver;
  revealObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) { entry.target.classList.add("in-view"); revealObserver.unobserve(entry.target); }
    });
  }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
  return revealObserver;
}
function armReveal(root) {
  $$(REVEAL_SELECTOR, root).forEach((node, i) => {
    if (reducedMotion()) { node.classList.add("in-view"); return; }
    node.classList.add("reveal");
    node.style.transitionDelay = Math.min(i * 40, 420) + "ms";
    getRevealObserver().observe(node);
  });
}
function animateValue(node, target, fmt, duration) {
  const start = performance.now();
  function tick(now) {
    const t = Math.min(1, (now - start) / (duration || 900));
    const eased = 1 - Math.pow(1 - t, 3);
    node.textContent = fmt(target * eased);
    if (t < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}
function animateCounts(root) {
  $$("[data-count]", root).forEach((node) => {
    const target = Number(node.dataset.count) || 0;
    if (reducedMotion()) { node.textContent = target.toLocaleString(); return; }
    animateValue(node, target, (v) => Math.round(v).toLocaleString());
  });
  $$("[data-money]", root).forEach((node) => {
    const targetCents = Number(node.dataset.money) || 0;
    if (reducedMotion()) { node.textContent = money(targetCents); return; }
    animateValue(node, targetCents, (v) => money(Math.round(v)));
  });
}
EV.armReveal = armReveal;
EV.animateCounts = animateCounts;

/* ------------------------------------------------------------------ pages registry + router */
const pages = {}; EV.page = (path, fn) => { pages[path] = fn; };
const view = $("#view");
let navToken = 0;

async function render() {
  const my = ++navToken;
  const hash = location.hash.slice(1) || "/";
  const [pathPart, queryPart] = hash.split("?");
  const parts = pathPart.split("/").filter(Boolean);
  window.scrollTo({ top: 0, behavior: "instant" in window ? "instant" : "auto" });
  setMenu(false); toggleAccountMenu(false);
  markActiveNav(parts[0] || "home");
  startProgress();

  const match = matchRoute(parts);
  if (!match) { finishProgress(); view.innerHTML = notFoundHtml(); markActiveNav(""); return; }

  view.classList.add("is-leaving"); view.classList.remove("is-entering");
  await sleep(90);
  if (my !== navToken) return;
  try {
    const html = await match.fn(match.params, new URLSearchParams(queryPart || ""));
    if (my !== navToken) return;
    view.innerHTML = html;
  } catch (e) {
    if (my !== navToken) return;
    view.innerHTML = errorHtml(e);
  }
  finishProgress();
  view.classList.remove("is-leaving"); view.classList.add("is-entering");
  view.focus({ preventScroll: true });
  armReveal(view);
  animateCounts(view);
}

function matchRoute(parts) {
  for (const key of Object.keys(pages)) {
    const segs = key.split("/").filter(Boolean);
    if (segs.length !== parts.length) continue;
    const params = {}; let ok = true;
    for (let i = 0; i < segs.length; i++) {
      if (segs[i].startsWith(":")) params[segs[i].slice(1)] = decodeURIComponent(parts[i]);
      else if (segs[i] !== parts[i]) { ok = false; break; }
    }
    if (ok) return { fn: pages[key], params };
  }
  if (parts.length === 0 && pages["/"]) return { fn: pages["/"], params: {} };
  return null;
}
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

function startProgress() { const p = $("#progress"); p.classList.remove("done"); void p.offsetWidth; p.classList.add("on"); }
function finishProgress() { const p = $("#progress"); p.classList.remove("on"); p.classList.add("done"); }

function notFoundHtml() {
  return `<div class="container notfound">
    <div class="ic-wrap" style="width:80px;height:80px;border-radius:22px;background:rgba(124,58,237,.16);display:grid;place-items:center;color:#C4B5FD">${icon("ticket", 40)}</div>
    <h1>This page took a wrong turn</h1><p style="max-width:44ch">We couldn't find that page. It may have moved, or the link might be off.</p>
    <a class="btn btn-primary" href="#/">${icon("chevronR", 18)}Back to Event Vault</a></div>`;
}
function errorHtml(e) {
  return `<div class="container notfound">
    <div class="ic-wrap" style="width:80px;height:80px;border-radius:22px;background:rgba(248,113,113,.14);display:grid;place-items:center;color:var(--bad)">${icon("alert", 40)}</div>
    <h1>Something went wrong</h1><p style="max-width:48ch">${esc(e.message || "Please try again.")}</p>
    <a class="btn btn-primary" href="#/">${icon("chevronR", 18)}Back to Event Vault</a></div>`;
}
EV.notFound = notFoundHtml;

window.addEventListener("hashchange", render);
EV.start = async function () {
  $("#year").textContent = new Date().getFullYear();
  await Promise.all([refreshUser(), refreshMeta()]);
  EV.state.ready = true;
  render();
};

})(window);
