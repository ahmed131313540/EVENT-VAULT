/* Event Vault: organizer pages — create/edit event, manage events, event stats, check-in scanner. */
(function (EV) {
"use strict";
const { $, $$, esc, money, qs, fmtDate, fmtTime, fmtWhen, relTime } = EV.util;
const icon = EV.icon;

function requireLoginPage(fn) {
  return async (params, query) => { if (!EV.requireLogin()) return `<div class="container" style="padding:80px 0;text-align:center"><span class="spinner lg"></span></div>`; return fn(params, query); };
}

/* ===================================================================== IMAGE HELPER (resize in-browser before upload) */
function wireImageDrop(dropEl, onDataUrl) {
  const input = $("input[type=file]", dropEl);
  function openPicker() { input.click(); }
  dropEl.addEventListener("click", (e) => { if (e.target !== input) openPicker(); });
  ["dragover", "dragenter"].forEach((ev) => dropEl.addEventListener(ev, (e) => { e.preventDefault(); dropEl.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => dropEl.addEventListener(ev, (e) => { e.preventDefault(); dropEl.classList.remove("over"); }));
  dropEl.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) handle(f); });
  input.addEventListener("change", () => { if (input.files[0]) handle(input.files[0]); });
  function handle(file) {
    if (!/^image\/(jpeg|png|webp)$/.test(file.type)) { EV.toast("Please choose a JPG, PNG or WebP image.", "err"); return; }
    const img = new Image();
    const reader = new FileReader();
    reader.onload = () => { img.onload = () => resizeAndEmit(img); img.src = reader.result; };
    reader.readAsDataURL(file);
  }
  function resizeAndEmit(img) {
    const MAX = 1600;
    let { width, height } = img;
    if (width > MAX || height > MAX) { const scale = MAX / Math.max(width, height); width = Math.round(width * scale); height = Math.round(height * scale); }
    const canvas = document.createElement("canvas"); canvas.width = width; canvas.height = height;
    canvas.getContext("2d").drawImage(img, 0, 0, width, height);
    const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
    onDataUrl(dataUrl);
  }
}
function dropPreview(dropEl, dataUrl) {
  dropEl.classList.toggle("has", !!dataUrl);
  const existing = $("img", dropEl); if (existing) existing.remove();
  if (dataUrl) dropEl.insertAdjacentHTML("afterbegin", `<img src="${dataUrl}" alt="Event image preview">`);
}

/* ===================================================================== CREATE EVENT */
EV.page("/create", requireLoginPage(async () => {
  if (EV.state.user.role === "user") {
    const html = `<section class="form-page container"><div id="access-prompt">${accessPromptSkeleton()}</div></section>`;
    setTimeout(() => wireAccessPrompt());
    return html;
  }
  const meta = EV.state.meta || { categories: [] };
  const html = eventFormShell({
    title: "Create Your Event", sub: "List tiered tickets and start selling in minutes.",
    submitLabel: "Create Event", categories: meta.categories.map((c) => c.name), tiers: [{ name: "Regular", price: "", quantity: "" }],
  });
  setTimeout(() => wireEventForm({ mode: "create" }));
  return html;
}));

function accessPromptSkeleton() {
  return `<div class="card form-card" style="text-align:center;padding:60px 30px"><span class="spinner lg" style="margin:0 auto"></span></div>`;
}

async function wireAccessPrompt() {
  const box = $("#access-prompt");
  let state;
  try { state = await EV.api.get("/organizer-requests/mine"); } catch (e) { box.innerHTML = alertHtml(e.message); return; }
  const req = state.request;
  const iconWrap = (ic) => `<span class="ic-wrap" style="width:60px;height:60px;border-radius:18px;background:rgba(124,58,237,.16);display:grid;place-items:center;color:#C4B5FD;margin:0 auto 18px">${icon(ic, 26)}</span>`;

  if (req && req.status === "pending") {
    box.innerHTML = `<div class="card form-card" style="text-align:center;padding:48px 30px">
      ${iconWrap("clock")}<h2 style="margin-bottom:8px">Your request is being reviewed</h2>
      <p class="sub" style="max-width:44ch;margin-inline:auto">You asked to create events on ${new Date(req.created_at).toLocaleDateString()}. An admin will approve or deny it soon — you'll be able to create events as soon as that happens.</p>
      <a class="btn btn-secondary" href="#/" style="margin-top:18px">${icon("chevronR", 16)}Back to Event Vault</a></div>`;
    return;
  }

  const deniedNote = req && req.status === "denied"
    ? `<div class="alert warn" style="margin:0 0 20px;text-align:left">${icon("alert", 18)}<span>A previous request was denied${req.reviewed_at ? " on " + new Date(req.reviewed_at).toLocaleDateString() : ""}. You're welcome to try again with more detail below.</span></div>`
    : "";
  box.innerHTML = `<div class="card form-card" style="text-align:center;padding:48px 30px">
    ${iconWrap("ticket")}<h2 style="margin-bottom:8px">Want to host events on Event Vault?</h2>
    <p class="sub" style="max-width:48ch;margin:0 auto 22px">Creating events is limited to approved organisers. Tell us a bit about what you'd like to run, and an admin will review your request.</p>
    <div style="max-width:480px;margin:22px auto 0;text-align:left">
      ${deniedNote}
      <div id="req-alert"></div>
      <form id="access-form">
        <div class="field"><label for="req-msg">What will you be hosting? <span style="color:var(--muted);font-weight:400">(optional)</span></label>
        <textarea id="req-msg" maxlength="500" placeholder="e.g. Monthly jazz nights at a venue in Chicago"></textarea></div>
        <div class="form-actions" style="margin-top:16px"><button class="btn btn-primary btn-lg" type="submit">${icon("plus", 18)}Request Organizer Access</button></div>
      </form>
    </div></div>`;
  $("#access-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const alertBox = $("#req-alert"); alertBox.innerHTML = "";
    const btn = e.target.querySelector("button"); btn.disabled = true; const orig = btn.innerHTML; btn.innerHTML = '<span class="spinner"></span>';
    try {
      await EV.api.post("/organizer-requests", { message: $("#req-msg").value.trim() });
      EV.toast("Request sent.", "ok");
      wireAccessPrompt();
    } catch (err) { alertBox.innerHTML = alertHtml(err.message); btn.disabled = false; btn.innerHTML = orig; }
  });
}

EV.page("/dashboard/events/:id/edit", EV.requireRolePage(["organizer", "admin"], async (params) => {
  let form;
  try { form = await EV.api.get(`/events/${params.id}/edit`); } catch (e) { return EV.notFound(); }
  const meta = EV.state.meta || { categories: [] };
  const html = eventFormShell({
    title: "Edit Event", sub: "Update the details, capacity or image.", submitLabel: "Save Changes",
    categories: meta.categories.map((c) => c.name), values: form, tiers: form.tiers, imageUrl: form.image_url, editing: true,
  });
  setTimeout(() => wireEventForm({ mode: "edit", id: params.id, form }));
  return html;
}));

function eventFormShell({ title, sub, submitLabel, categories, values, tiers, imageUrl, editing }) {
  const v = values || {};
  return `<section class="form-page container">
    <h1>${esc(title)}</h1><p style="margin-top:6px">${esc(sub)}</p>
    <form class="card form-card" id="event-form">
      <div id="form-alert"></div>
      <h2>Event details</h2>
      <div class="form-grid">
        <div class="field full"><label for="ef-title">Event name</label><input id="ef-title" required minlength="3" maxlength="120" value="${esc(v.title || "")}"></div>
        <div class="field"><label for="ef-cat">Category</label><select id="ef-cat" required>${categories.map((c) => `<option ${v.category === c ? "selected" : ""}>${esc(c)}</option>`).join("")}</select></div>
        <div class="field"><label for="ef-date">Event date</label><input id="ef-date" type="date" required value="${esc(v.date || "")}"></div>
        <div class="field"><label for="ef-time">Event time</label><input id="ef-time" type="time" required value="${esc(v.time || "")}"></div>
        <div class="field"><label for="ef-city">City</label><input id="ef-city" required maxlength="80" value="${esc(v.city || "")}"></div>
        <div class="field full"><label for="ef-venue">Location / venue</label><input id="ef-venue" required maxlength="160" value="${esc(v.venue || "")}"></div>
        <div class="field full"><label for="ef-desc">Event description</label><textarea id="ef-desc" required minlength="10" maxlength="5000">${esc(v.description || "")}</textarea></div>
        <div class="field"><label for="ef-email">Contact email</label><input id="ef-email" type="email" required value="${esc(v.contact_email || "")}"></div>
        <div class="field"><label for="ef-phone">Contact phone <span style="color:var(--muted);font-weight:400">(optional)</span></label><input id="ef-phone" value="${esc(v.contact_phone || "")}"></div>
        <div class="field full"><label>Event image</label>
          <div class="drop ${imageUrl ? "has" : ""}" id="ef-drop">
            <input type="file" accept="image/jpeg,image/png,image/webp" aria-label="Upload event image">
            ${imageUrl ? `<img src="${imageUrl}" alt="Event image preview">` : ""}
            <div class="keep">${icon("upload", 26)}<span>Drop an image, or click to browse</span><small style="color:var(--muted)">JPG, PNG or WebP, up to 2.5 MB</small></div>
          </div>
          ${imageUrl ? `<button type="button" class="btn btn-ghost btn-sm" id="ef-remove-img" style="width:max-content">${icon("trash", 15)}Remove image</button>` : ""}
        </div>
      </div>

      <h2 style="margin-top:36px">Ticket types</h2>
      <p class="sub">Each type gets its own price and capacity.${editing ? " Prices can't change once a ticket type exists — add a new one instead." : ""}</p>
      <div id="tier-rows">${(tiers || []).map((t, i) => tierRowEditor(t, i, editing)).join("")}</div>
      ${editing ? `<button type="button" class="btn btn-secondary btn-sm" id="add-tier">${icon("plus", 16)}Add ticket type</button>` : `
      <div class="form-actions" style="margin:0 0 8px">
        <button type="button" class="btn btn-secondary btn-sm" id="add-tier">${icon("plus", 16)}Add another tier</button>
      </div>`}

      <div class="form-actions">
        <button class="btn btn-primary btn-lg" type="submit">${icon(editing ? "check" : "plus", 18)}${esc(submitLabel)}</button>
        <a class="btn btn-ghost btn-lg" href="${editing ? "#/dashboard/events" : "#/"}">Cancel</a>
      </div>
    </form>
  </section>`;
}

function tierRowEditor(t, i, editing) {
  const locked = editing && t.id;
  return `<div class="tier-row" data-row data-tier-id="${t.id || ""}" data-locked="${locked ? "1" : ""}">
    <div class="field"><label>Name</label><input class="t-name" maxlength="40" value="${esc(t.name || "")}" placeholder="e.g. VIP" required></div>
    <div class="field ${locked ? "locked" : ""}"><label>Price</label><div class="money"><span>$</span><input class="t-price" type="number" min="0" step="0.01" value="${t.price_cents != null ? (t.price_cents / 100) : (t.price ?? "")}" placeholder="0.00" ${locked ? "disabled title=\"Price can't change once a tier exists\"" : "required"}></div></div>
    <div class="field"><label>${locked ? "Capacity" : "Quantity"}</label><input class="t-qty" type="number" min="${locked ? (t.sold || 0) : 1}" value="${t.quantity ?? ""}" required></div>
    <button type="button" class="btn icon-btn" data-remove aria-label="Remove this ticket type" ${(tiersCount() <= 1) ? "" : ""}>${icon("trash", 17)}</button>
  </div>`;
}
function tiersCount() { return $$("#tier-rows [data-row]").length; }

function wireEventForm({ mode, id, form }) {
  const drop = $("#ef-drop");
  let imageDataUrl = null, removeImage = false;
  wireImageDrop(drop, (url) => { imageDataUrl = url; removeImage = false; dropPreview(drop, url); const rm = $("#ef-remove-img"); if (rm) rm.hidden = false; });
  const removeBtn = $("#ef-remove-img");
  if (removeBtn) removeBtn.addEventListener("click", () => { imageDataUrl = null; removeImage = true; dropPreview(drop, null); });

  function addTierRow(t) { $("#tier-rows").insertAdjacentHTML("beforeend", tierRowEditor(t || {}, tiersCount(), mode === "edit")); wireTierRemovals(); }
  function wireTierRemovals() {
    $$("#tier-rows [data-remove]").forEach((btn) => btn.onclick = () => {
      if (tiersCount() <= 1) { EV.toast("Keep at least one ticket type.", "err"); return; }
      const row = btn.closest("[data-row]");
      if (row.dataset.locked) { EV.toast("A ticket type that's already for sale can't be removed — set its quantity to match tickets sold instead.", "err"); return; }
      row.remove();
    });
  }
  wireTierRemovals();
  $("#add-tier").addEventListener("click", () => addTierRow());

  $("#event-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const alertBox = $("#form-alert"); alertBox.innerHTML = "";
    const rows = $$("#tier-rows [data-row]");
    if (!rows.length) { alertBox.innerHTML = alertHtml("Add at least one ticket type."); return; }
    const names = rows.map((r) => $(".t-name", r).value.trim().toLowerCase());
    if (new Set(names).size !== names.length) { alertBox.innerHTML = alertHtml("Each ticket type needs a different name."); return; }

    const body = {
      title: $("#ef-title").value.trim(), category: $("#ef-cat").value, description: $("#ef-desc").value.trim(),
      venue: $("#ef-venue").value.trim(), city: $("#ef-city").value.trim(), date: $("#ef-date").value, time: $("#ef-time").value,
      contact_email: $("#ef-email").value.trim(), contact_phone: $("#ef-phone").value.trim() || null,
    };
    if (imageDataUrl) body.image = imageDataUrl;

    const btn = e.target.querySelector('button[type=submit]'); btn.disabled = true; const orig = btn.innerHTML; btn.innerHTML = '<span class="spinner"></span>';
    try {
      if (mode === "create") {
        body.tiers = rows.map((r) => ({ name: $(".t-name", r).value.trim(), price: parseFloat($(".t-price", r).value), quantity: parseInt($(".t-qty", r).value, 10) }));
        const res = await EV.api.post("/events", body);
        EV.toast("Event created.", "ok");
        location.hash = `#/events/${res.id}`;
      } else {
        body.remove_image = removeImage;
        body.tiers = rows.filter((r) => r.dataset.tierId).map((r) => ({ id: parseInt(r.dataset.tierId, 10), name: $(".t-name", r).value.trim(), quantity: parseInt($(".t-qty", r).value, 10) }));
        body.new_tiers = rows.filter((r) => !r.dataset.tierId).map((r) => ({ name: $(".t-name", r).value.trim(), price: parseFloat($(".t-price", r).value), quantity: parseInt($(".t-qty", r).value, 10) }));
        await EV.api.put(`/events/${id}`, body);
        EV.toast("Changes saved.", "ok");
        location.hash = `#/events/${id}`;
      }
    } catch (err) { alertBox.innerHTML = alertHtml(err.message); btn.disabled = false; btn.innerHTML = orig; window.scrollTo({ top: 0, behavior: "smooth" }); }
  });
}
function alertHtml(msg) { return `<div class="alert err">${icon("alert", 18)}${esc(msg)}</div>`; }

/* ===================================================================== MY EVENTS (manage) */
EV.page("/dashboard/events", EV.requireRolePage(["organizer", "admin"], async () => {
  const html = EV.dashShell("events", `
    <div class="dash-head"><h1>My events</h1><a class="btn btn-primary" href="#/create">${icon("plus", 18)}Create Event</a></div>
    <div id="my-events"><div style="text-align:center;padding:60px 0"><span class="spinner lg"></span></div></div>`);
  setTimeout(loadMyEvents);
  return html;
}));

async function loadMyEvents() {
  const box = $("#my-events");
  let data;
  try { data = await EV.api.get("/me/events"); } catch (e) { box.innerHTML = alertHtml(e.message); return; }
  if (!data.events.length) { box.innerHTML = EV.emptyState("Create your first event to start selling tickets.") + `<div style="text-align:center;margin-top:16px"><a class="btn btn-primary" href="#/create">${icon("plus", 18)}Create Event</a></div>`; return; }
  box.innerHTML = `<div class="mine">${data.events.map(mineCard).join("")}</div>`;
  $$("[data-delete]", box).forEach((btn) => btn.addEventListener("click", () => {
    const id = btn.dataset.delete, title = btn.dataset.title;
    EV.confirm({ title: "Delete this event?", body: `<b style="color:var(--text)">${esc(title)}</b> will be permanently removed. This can't be undone.`, confirmText: "Delete Event", danger: true,
      onConfirm: async () => { await EV.api.del(`/events/${id}`); EV.toast("Event deleted.", "ok"); loadMyEvents(); } });
  }));
}
function mineCard(e) {
  const pct = e.capacity ? Math.round((e.tickets_sold / e.capacity) * 100) : 0;
  return `<div class="card mine-card">
    ${EV.eventThumb(e, 96)}
    <div>
      <a href="#/events/${e.id}"><h3>${esc(e.title)}</h3></a>
      <ul class="meta"><li class="date">${icon("calendar", 15)}${fmtDate(e.starts_at, { month: "short", day: "numeric", year: "numeric" })}</li><li>${icon("location", 15)}${esc(e.venue)}, ${esc(e.city)}</li></ul>
      <div class="kpis">
        <div><b>${e.tickets_sold}${e.capacity ? "/" + e.capacity : ""}</b>sold<div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div></div>
        <div><b>${e.checked_in}</b>checked in</div>
        <div><b class="gold">${money(e.revenue_cents)}</b>revenue</div>
      </div>
    </div>
    <div class="actions">
      <a class="btn icon-btn" href="#/dashboard/events/${e.id}/stats" aria-label="Stats">${icon("chart", 18)}</a>
      <a class="btn icon-btn" href="#/dashboard/events/${e.id}/edit" aria-label="Edit">${icon("edit", 18)}</a>
      <a class="btn icon-btn" href="#/scanner?event=${e.id}" aria-label="Scan tickets">${icon("camera", 18)}</a>
      <button class="btn icon-btn" data-delete="${e.id}" data-title="${esc(e.title)}" aria-label="Delete" style="color:var(--bad)">${icon("trash", 18)}</button>
    </div>
  </div>`;
}

/* ===================================================================== EVENT STATS */
EV.page("/dashboard/events/:id/stats", EV.requireRolePage(["organizer", "admin"], async (params) => {
  const html = EV.dashShell("events", `<div id="stats-content"><div style="text-align:center;padding:60px 0"><span class="spinner lg"></span></div></div>`);
  setTimeout(() => loadEventStats(params.id));
  return html;
}));
async function loadEventStats(id) {
  const box = $("#stats-content");
  let s;
  try { s = await EV.api.get(`/events/${id}/stats`); } catch (e) { box.innerHTML = alertHtml(e.message); return; }
  box.innerHTML = `
    <div class="dash-head"><h1>${esc(s.title)}</h1><div style="display:flex;gap:10px"><a class="btn btn-secondary btn-sm" href="#/dashboard/events/${id}/edit">${icon("edit", 16)}Edit</a><a class="btn btn-primary btn-sm" href="#/scanner?event=${id}">${icon("camera", 16)}Scan Tickets</a></div></div>
    <div class="stats">
      ${EV.statCard("ticket", "Tickets sold", `${s.totals.sold}/${s.totals.capacity}`)}
      ${EV.statCard("check", "Checked in", s.totals.checked_in)}
      ${EV.statCard("spark", "Revenue", null, { cents: s.totals.revenue_cents, gold: true })}
      ${EV.statCard("ban", "Duplicate scans blocked", s.blocked_duplicates)}
    </div>
    <div class="cols" style="margin-top:20px">
      <div class="panel"><h2>Sales, last 14 days</h2><p class="sub">Tickets sold per day.</p>${EV.barChart(s.sales_by_day)}</div>
      <div class="panel"><h2>By ticket type</h2><p class="sub">Sold, checked in and revenue per tier.</p>
        <div class="list">${s.tiers.map((t) => `<div class="row-item"><div class="grow"><b>${esc(t.name)}</b><small>${t.sold}/${t.quantity} sold · ${t.checked_in} checked in</small></div><b class="gold" style="font-family:var(--head)">${money(t.revenue_cents)}</b></div>`).join("") || "<p>No ticket types.</p>"}</div>
      </div>
    </div>`;
  EV.armReveal(box);
  EV.animateCounts(box);
}

/* ===================================================================== SCANNER */
let jsQrLoaded = null;
function loadJsQr() {
  if (jsQrLoaded) return jsQrLoaded;
  jsQrLoaded = new Promise((resolve, reject) => {
    if (window.jsQR) return resolve();
    const s = document.createElement("script");
    s.src = "/assets/js/vendor/jsqr.js";
    s.onload = () => resolve(); s.onerror = () => reject(new Error("Couldn't load the QR scanning library."));
    document.head.appendChild(s);
  });
  return jsQrLoaded;
}

EV.page("/scanner", EV.requireRolePage(["organizer", "admin"], async (_, query) => {
  const eventId = query.get("event") || "";
  let events;
  try {
    // An admin may scan at any event's door (the API allows it), so they pick from every active event;
    // an organizer only ever sees their own.
    events = EV.state.user.role === "admin"
      ? (await EV.api.get("/admin/events?status=active&limit=100")).events
      : (await EV.api.get("/me/events")).events;
  } catch { events = []; }
  if (!events.length) {
    return EV.dashShell("scanner", `${EV.emptyState("Create an event first, then come back here to scan tickets at the door.")}<div style="text-align:center;margin-top:16px"><a class="btn btn-primary" href="#/create">${icon("plus", 18)}Create Event</a></div>`);
  }
  const selected = events.find((e) => String(e.id) === eventId) || events[0];
  const html = EV.dashShell("scanner", `
    <div class="dash-head"><h1>Scan tickets</h1>
      <label class="field" style="min-width:260px"><span class="sr-only">Event</span>
        <select id="scan-event">${events.map((e) => `<option value="${e.id}" ${e.id === selected.id ? "selected" : ""}>${esc(e.title)}</option>`).join("")}</select>
      </label></div>
    <div class="scan">
      <div>
        <div class="viewfinder" id="viewfinder">
          <video id="scan-video" playsinline muted></video>
          <div class="frame" id="scan-frame" hidden><i></i><i></i><i></i><i></i></div>
          <div class="idle" id="scan-idle">
            <span class="ic-wrap" style="width:60px;height:60px;border-radius:18px;background:rgba(124,58,237,.18);display:grid;place-items:center;color:#C4B5FD">${icon("camera", 30)}</span>
            <p style="max-width:32ch">Start the camera to scan QR tickets at the door. Works on phones and laptops.</p>
            <button class="btn btn-primary" id="scan-start">${icon("camera", 18)}Start Camera</button>
          </div>
        </div>
        <div class="card counter" style="margin-top:16px"><span>Checked in this session</span><b id="scan-count">0</b></div>
      </div>
      <div class="scan-side">
        <div class="verdict" id="verdict"><span style="color:var(--muted)">Point the camera at a ticket's QR code.</span></div>
        <div class="card panel" style="padding:20px">
          <h2 style="margin-bottom:4px">Type a code instead</h2><p class="sub">If the camera can't read it, enter it manually.</p>
          <form id="manual-form" style="display:flex;gap:10px;flex-wrap:wrap"><input id="manual-code" placeholder="EV-XXXX-XXXX-XXXX-XXXX" style="flex:1;min-width:0;padding:11px 13px;background:var(--bg);border:1px solid var(--border);border-radius:10px;color:var(--text)"><button class="btn btn-secondary" type="submit" style="flex:none">Check</button></form>
        </div>
        <div class="card panel">
          <h2>Recent scans</h2><p class="sub">Latest activity at the door.</p>
          <ul class="log" id="scan-log"><li style="color:var(--muted)">No scans yet.</li></ul>
        </div>
      </div>
    </div>`);
  setTimeout(() => wireScanner(selected.id));
  return html;
}));

function wireScanner(initialEventId) {
  const state = { eventId: initialEventId, stream: null, running: false, lastCode: null, lastAt: 0, count: 0, busy: false };
  const video = $("#scan-video"), idle = $("#scan-idle"), frame = $("#scan-frame"), verdict = $("#verdict"), countEl = $("#scan-count"), log = $("#scan-log");
  const canvas = document.createElement("canvas"); const ctx = canvas.getContext("2d", { willReadFrequently: true });

  $("#scan-event").addEventListener("change", (e) => { state.eventId = e.target.value; history.replaceState(null, "", "#/scanner?event=" + state.eventId); });

  $("#scan-start").addEventListener("click", async () => {
    const btn = $("#scan-start"); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
    try {
      await loadJsQr();
      state.stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
      video.srcObject = state.stream; await video.play();
      idle.hidden = true; frame.hidden = false; state.running = true;
      requestAnimationFrame(tick);
    } catch (e) {
      const msg = e && e.name === "NotAllowedError" ? "Camera access was denied. Allow camera access in your browser settings and try again."
        : e && e.name === "NotFoundError" ? "No camera was found on this device." : (e.message || "Couldn't start the camera.");
      setVerdict("bad", "ban", "Camera unavailable", msg);
      btn.disabled = false; btn.innerHTML = icon("camera", 18) + "Start Camera";
    }
  });

  function tick() {
    if (!state.running) return;
    if (video.readyState === video.HAVE_ENOUGH_DATA) {
      canvas.width = video.videoWidth; canvas.height = video.videoHeight;
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const code = window.jsQR(img.data, img.width, img.height, { inversionAttempts: "dontInvert" });
      if (code && code.data) {
        const now = Date.now();
        if (code.data !== state.lastCode || now - state.lastAt > 2500) { state.lastCode = code.data; state.lastAt = now; submitScan(code.data); }
      }
    }
    requestAnimationFrame(tick);
  }

  async function submitScan(code) {
    if (state.busy) return; state.busy = true;
    try {
      const res = await EV.api.post("/checkin", { event_id: parseInt(state.eventId, 10), code });
      applyResult(res);
    } catch (e) { setVerdict("bad", "alert", "Scan failed", e.message); addLog({ result: "invalid", message: e.message }); }
    finally { setTimeout(() => (state.busy = false), 350); }
  }

  function applyResult(res) {
    const map = { ok: ["ok", "check", "Admitted"], already_used: ["warn", "ban", "Already used"], wrong_event: ["warn", "alert", "Wrong event"], void: ["bad", "ban", "Cancelled"], invalid: ["bad", "alert", "Invalid code"] };
    const [cls, ic, title] = map[res.result] || ["bad", "alert", "Error"];
    const detail = res.holder ? `${esc(res.holder)} · ${esc(res.tier)}${res.seq ? " · #" + res.seq : ""}` : res.message;
    setVerdict(cls, ic, title, detail);
    if (res.result === "ok") { state.count++; countEl.textContent = state.count; navigator.vibrate && navigator.vibrate(60); }
    addLog(res);
  }
  function setVerdict(cls, ic, title, sub) {
    verdict.className = "verdict " + cls; verdict.classList.remove("pop"); void verdict.offsetWidth; verdict.classList.add("pop");
    verdict.innerHTML = `${icon(ic, 34)}<span class="big">${esc(title)}</span>${sub ? `<span style="color:var(--muted)">${esc(sub)}</span>` : ""}`;
  }
  function addLog(res) {
    const map = { ok: ["ok", "Admitted"], already_used: ["warn", "Duplicate"], wrong_event: ["warn", "Wrong event"], void: ["bad", "Cancelled"], invalid: ["bad", "Invalid"] };
    const [tag, label] = map[res.result] || ["bad", "Error"];
    if ($("li", log) && log.firstElementChild.textContent === "No scans yet.") log.innerHTML = "";
    log.insertAdjacentHTML("afterbegin", `<li><span>${res.holder ? esc(res.holder) : "Unknown code"}${res.tier ? " · " + esc(res.tier) : ""}</span><span class="tag ${tag}">${label}</span></li>`);
    while (log.children.length > 10) log.lastElementChild.remove();
  }

  $("#manual-form").addEventListener("submit", (e) => { e.preventDefault(); const v = $("#manual-code").value.trim(); if (v) submitScan(v); $("#manual-code").value = ""; });

  window.addEventListener("hashchange", stop, { once: true });
  function stop() { state.running = false; if (state.stream) state.stream.getTracks().forEach((t) => t.stop()); }
}

})(window.EV);
