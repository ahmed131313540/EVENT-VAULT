/* Event Vault: account pages — order confirmation, my tickets, dashboard overview. */
(function (EV) {
"use strict";
const { $, $$, esc, money, qs, fmtDate, fmtTime, fmtWhen } = EV.util;
const icon = EV.icon;

function requireLoginPage(fn) {
  return async (params, query) => { if (!EV.requireLogin()) return `<div class="container" style="padding:80px 0;text-align:center"><span class="spinner lg"></span></div>`; return fn(params, query); };
}

/* ===================================================================== ORDER CONFIRMATION */
EV.page("/order/:ref", requireLoginPage(async (params, query) => {
  const cancelled = query.get("cancelled") === "1";
  const html = `<section class="order container" id="order-wrap"><div style="text-align:center;padding:60px 0"><span class="spinner lg"></span></div></section>`;
  setTimeout(() => loadOrder(params.ref, cancelled));
  return html;
}));

async function loadOrder(ref, cancelled, silent) {
  const wrap = $("#order-wrap");
  let o;
  try { o = await EV.api.get(`/orders/${ref}`); }
  catch (e) { wrap.innerHTML = `<div class="order-hero"><div class="check bad">${icon("alert", 36)}</div><h1>We couldn't find that order</h1><p>${esc(e.message)}</p><a class="btn btn-primary" href="#/events">Browse events</a></div>`; return; }

  if (o.status === "pending" && !cancelled) {
    if (!silent) wrap.innerHTML = `<div class="order-hero"><span class="spinner lg"></span><h1>Confirming your payment…</h1><p>This updates automatically once Stripe confirms it.</p></div>`;
    setTimeout(() => loadOrder(ref, cancelled, true), 2500);
    return;
  }
  if (o.status !== "paid") {
    const why = cancelled ? "You cancelled checkout before it completed." : o.status === "expired" ? "This checkout session expired before payment completed." : "This order couldn't be completed.";
    wrap.innerHTML = `<div class="order-hero"><div class="check bad">${icon("close", 36)}</div><h1>Order not completed</h1><p>${esc(why)} No charge was made.</p>
      <div class="hero-cta" style="justify-content:center"><a class="btn btn-primary" href="#/events/${o.event.id}">Try again</a><a class="btn btn-secondary" href="#/events">Browse events</a></div></div>`;
    return;
  }

  wrap.innerHTML = `
    <div class="order-hero">
      <div class="check">${icon("check", 36)}</div>
      <h1>You're going!</h1>
      <p>${o.tickets.length} ticket${o.tickets.length === 1 ? "" : "s"} for <b style="color:var(--text)">${esc(o.event.title)}</b>. ${o.emailed ? `Sent to ${esc(o.buyer_email)}.` : (o.email_error ? esc(o.email_error) : "")}</p>
    </div>
    <div class="card panel" style="margin-bottom:22px">
      <h2 style="margin-bottom:14px">${esc(o.event.title)}</h2>
      <ul class="meta"><li class="date">${icon("calendar", 16)}${fmtWhen(o.event.starts_at)}</li><li>${icon("location", 16)}${esc(o.event.venue)}, ${esc(o.event.city)}</li></ul>
      ${!o.emailed ? `<div class="alert warn" style="margin-top:16px">${icon("alert", 18)}<span>${esc(o.email_error || "Your tickets weren't emailed.")} <button class="btn btn-sm btn-secondary" id="resend-btn" style="margin-left:8px">Resend email</button></span></div>` : ""}
    </div>
    <div class="tix">${o.tickets.map((t) => ticketCard(t, o.event)).join("")}</div>
    <div class="hero-cta" style="justify-content:center;margin-top:30px"><a class="btn btn-secondary" href="#/dashboard/tickets">${icon("ticket", 18)}All my tickets</a><a class="btn btn-primary" href="#/events">${icon("search", 18)}Find more events</a></div>`;

  const resend = $("#resend-btn");
  if (resend) resend.addEventListener("click", async () => { resend.disabled = true; resend.innerHTML = '<span class="spinner"></span>'; try { await EV.api.post(`/orders/${ref}/resend`); EV.toast("Email sent.", "ok"); loadOrder(ref, false, true); } catch (e) { EV.toast(e.message, "err"); resend.disabled = false; resend.textContent = "Resend email"; } });
}

function ticketCard(t, event) {
  return `<div class="tix-card">
    <div class="info">
      <span class="status-pill ${t.status === "used" ? "used" : "valid"}">${icon(t.status === "used" ? "check" : "ticket", 13)}${t.status === "used" ? "Checked in" : "Valid"}</span>
      <b>${esc(t.tier_name)}</b><span style="color:var(--muted);font-size:.88rem">${esc(t.holder_name)} · Ticket ${t.seq}</span>
      <span class="code">${esc(t.token)}</span>
      <div class="tix-actions">
        <a class="btn btn-secondary btn-sm" href="/api/tickets/${encodeURIComponent(t.token)}/pdf" target="_blank" rel="noopener">${icon("upload", 15)}Download PDF</a>
      </div>
    </div>
    <div class="qr"><img src="/api/tickets/${encodeURIComponent(t.token)}/qr.svg" alt="QR code for ticket ${esc(t.token)}" loading="lazy"></div>
  </div>`;
}

/* ===================================================================== MY TICKETS */
EV.page("/dashboard/tickets", requireLoginPage(async () => {
  const html = dashShell("tickets", `<div id="tix-content"><div style="text-align:center;padding:60px 0"><span class="spinner lg"></span></div></div>`);
  setTimeout(loadMyTickets);
  return html;
}));

async function loadMyTickets() {
  const box = $("#tix-content");
  let data;
  try { data = await EV.api.get("/me/tickets"); } catch (e) { box.innerHTML = `<div class="alert err">${icon("alert", 18)}${esc(e.message)}</div>`; return; }
  if (!data.tickets.length) { box.innerHTML = EV.emptyState("Tickets you buy will show up here, ready to scan at the door."); return; }
  const now = Date.now();
  const upcoming = data.tickets.filter((t) => new Date(t.event.starts_at).getTime() >= now - 12 * 3600e3);
  const past = data.tickets.filter((t) => new Date(t.event.starts_at).getTime() < now - 12 * 3600e3);
  const group = (list) => {
    const byEvent = new Map();
    list.forEach((t) => { if (!byEvent.has(t.event.id)) byEvent.set(t.event.id, []); byEvent.get(t.event.id).push(t); });
    return Array.from(byEvent.values());
  };
  const section = (title, groups, muted) => !groups.length ? "" : `<div class="tix-group"><h2>${title}</h2>
    ${groups.map((g) => `<p style="${muted ? "opacity:.7" : ""}"><a href="#/events/${g[0].event.id}" style="color:var(--text);font-weight:600">${esc(g[0].event.title)}</a> · ${fmtWhen(g[0].event.starts_at)} · ${esc(g[0].event.venue)}, ${esc(g[0].event.city)}</p>
    <div class="tix" style="${muted ? "opacity:.6" : ""};margin-bottom:26px">${g.map((t) => ticketCard(t, g[0].event)).join("")}</div>`).join("")}</div>`;
  box.innerHTML = section("Upcoming", group(upcoming)) + section("Past events", group(past), true);
}

/* ===================================================================== DASHBOARD OVERVIEW */
EV.page("/dashboard", requireLoginPage(async () => {
  if (EV.state.user.role === "user") {           // the overview is organizer stats; a buyer's home is their tickets
    location.hash = "#/dashboard/tickets";
    return `<div class="container" style="padding:80px 0;text-align:center"><span class="spinner lg"></span></div>`;
  }
  const html = dashShell("overview", `<div id="ov-content"><div style="text-align:center;padding:60px 0"><span class="spinner lg"></span></div></div>`);
  setTimeout(loadOverview);
  return html;
}));

async function loadOverview() {
  const box = $("#ov-content");
  let data;
  try { data = await EV.api.get("/me/overview"); } catch (e) { box.innerHTML = `<div class="alert err">${icon("alert", 18)}${esc(e.message)}</div>`; return; }
  const s = data.stats;
  box.innerHTML = `
    <div class="stats">
      ${EV.statCard("ticket", "Tickets you've booked", s.tickets_bought)}
      ${EV.statCard("calendar", "Your upcoming events", s.upcoming_registered)}
      ${EV.statCard("chart", "Events you've created", s.events_created)}
      ${EV.statCard("ticket", "Tickets sold across your events", s.tickets_sold)}
      ${EV.statCard("check", "Guests checked in", s.checked_in)}
      ${EV.statCard("spark", "Revenue earned", null, { cents: s.revenue_cents, gold: true })}
    </div>
    <div class="panel" style="margin-top:20px">
      <h2>Ticket sales, last 14 days</h2><p class="sub">Across every event you organise.</p>
      ${barChart(data.sales_by_day)}
    </div>
    <div class="dash-head" style="margin-top:8px"><div></div><a class="btn btn-secondary btn-sm" href="#/dashboard/tickets">${icon("ticket", 16)}View my tickets</a></div>`;
  EV.armReveal(box);
  EV.animateCounts(box);
}

function barChart(days) {
  if (!days || !days.length) return `<p style="padding:20px 0">No sales yet.</p>`;
  const W = 720, H = 220, PAD = 28, n = days.length;
  const max = Math.max(1, ...days.map((d) => d.tickets));
  const bw = (W - PAD * 2) / n * 0.62, gap = (W - PAD * 2) / n;
  const bars = days.map((d, i) => {
    const bh = (d.tickets / max) * (H - PAD * 2 - 16);
    const x = PAD + i * gap + (gap - bw) / 2, y = H - PAD - bh;
    return `<g><title>${esc(d.day)}: ${d.tickets} ticket${d.tickets === 1 ? "" : "s"}</title><rect class="bar" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(bh, d.tickets ? 3 : 0).toFixed(1)}" rx="4"/></g>`;
  }).join("");
  const gridLines = [0, .5, 1].map((f) => `<line class="grid-line" x1="${PAD}" x2="${W - PAD}" y1="${(H - PAD - f * (H - PAD * 2 - 16)).toFixed(1)}" y2="${(H - PAD - f * (H - PAD * 2 - 16)).toFixed(1)}"/>`).join("");
  const labels = days.filter((_, i) => i % Math.ceil(n / 7) === 0).map((d) => `<text x="${(PAD + days.indexOf(d) * gap + gap / 2).toFixed(1)}" y="${H - 6}" text-anchor="middle">${new Date(d.day).toLocaleDateString("en-US", { month: "short", day: "numeric" })}</text>`).join("");
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Ticket sales over the last 14 days">${gridLines}${bars}${labels}</svg>`;
}
EV.barChart = barChart;

/* ===================================================================== SHARED DASHBOARD SHELL */
function dashShell(active, content, navItems) {
  // A plain user only has tickets to look at; organizers and admins get the event-management links too.
  const isUser = !EV.state.user || EV.state.user.role === "user";
  const items = navItems || (isUser
    ? [["tickets", "ticket", "My tickets", "#/dashboard/tickets"], ["create", "plus", "Become an organizer", "#/create"]]
    : [["overview", "chart", "Overview", "#/dashboard"], ["events", "calendar", "My events", "#/dashboard/events"], ["tickets", "ticket", "My tickets", "#/dashboard/tickets"], ["create", "plus", "Create event", "#/create"], ["scanner", "camera", "Scan tickets", "#/scanner"]]);
  return `<div class="container dash">
    <nav class="side" aria-label="Dashboard">${items.map(([key, ic, label, href]) => `<a href="${href}" class="${active === key ? "active" : ""}">${icon(ic, 18)}${label}</a>`).join("")}</nav>
    <div>${content}</div>
  </div>`;
}
EV.dashShell = dashShell;

})(window.EV);
