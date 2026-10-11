/* Event Vault: public pages — home, events list, event detail, categories, about, contact, auth. */
(function (EV) {
"use strict";
const { $, $$, esc, money, h, el, qs, debounce, fmtDate, fmtTime, fmtWhen } = EV.util;
const icon = EV.icon;

/* ===================================================================== HOME */
EV.page("/", async () => {
  const [featuredRes, upcomingRes] = await Promise.all([
    EV.api.get("/events" + qs({ featured: true, limit: 3 })),
    EV.api.get("/events" + qs({ limit: 6, sort: "soonest" })),
  ]);
  const meta = EV.state.meta || { categories: [] };
  const [main, ...rest] = featuredRes.events;

  const html = `
  <section class="hero">
    <div class="hero-glow g1" aria-hidden="true"></div><div class="hero-glow g2" aria-hidden="true"></div>
    <div class="container hero-grid">
      <div class="hero-in">
        <h1><span>Discover.</span><span class="grad-text">Experience.</span><span>Remember.</span></h1>
        <p class="lead">Event Vault helps you discover, explore and manage the events worth remembering — concerts, weddings, conferences, festivals and more, all in one place.</p>
        <form id="hero-search" class="search-panel" role="search">
          <label class="sp-field">${icon("search")}<input name="q" placeholder="Search events" aria-label="Search events"></label>
          <label class="sp-field">${icon("location")}<select name="city" aria-label="Location"><option value="">Any location</option>${meta.cities.map((c) => `<option>${esc(c)}</option>`).join("")}</select></label>
          <label class="sp-field">${icon("calendar")}<input type="date" name="date" aria-label="Date"></label>
        </form>
        <div class="hero-cta">
          <button class="btn btn-primary btn-lg" id="hero-explore">${icon("search", 18)}Explore Events</button>
          <a class="btn btn-secondary btn-lg" href="#/create">${icon("plus", 18)}Create Event</a>
        </div>
      </div>
      <div class="hero-art" aria-hidden="true">
        <div class="tk back"></div>
        <div class="tk front">
          <div class="media"><div class="cover" style="--a:#7C3AED66;--b:#EC489966;height:100%"><span class="cover-ic">${icon("music", 130)}</span></div></div>
          <div class="tk-body"><h3>Neon Nights Festival</h3><p class="gold">Sat 24 Oct · 4:00 PM</p><p>Arena Spree, Berlin</p></div>
          <div class="tk-foot"><div><small>Ticket holder</small><b>Ahmed Khan</b></div><div class="qr">${simpleQr()}</div></div>
        </div>
      </div>
    </div>
  </section>

  <section class="section container">
    <div class="section-head"><div><h2>Browse by category</h2><p>Find the kind of night — or day — you're after.</p></div><a class="link-more" href="#/categories">All categories${icon("chevronR", 16)}</a></div>
    <div class="cat-grid">${meta.categories.slice(0, 8).map(categoryCard).join("")}</div>
  </section>

  <section class="section container" id="featured">
    <div class="section-head"><div><h2>Featured events</h2><p>Handpicked and unmissable, right now.</p></div><a class="link-more" href="#/events?featured=1">See all featured${icon("chevronR", 16)}</a></div>
    ${main ? `<div class="feat-grid">
      <a class="card feat-main" href="#/events/${main.id}">
        ${EV.eventThumb(main)}
        <div class="feat-copy">
          <span class="badge gold" style="width:max-content">${icon("spark", 14)}Featured</span>
          <h3>${esc(main.title)}</h3>
          <ul class="meta"><li class="date">${icon("calendar", 16)}${fmtDate(main.starts_at)}</li><li>${icon("location", 16)}${esc(main.venue)}, ${esc(main.city)}</li></ul>
          <div class="feat-row"><span class="price">${main.max_price_cents === 0 ? "Free" : "From " + money(main.min_price_cents)}</span><span class="btn btn-primary btn-sm">View Details${icon("chevronR", 16)}</span></div>
        </div></a>
      <div class="feat-side">${rest.map(sideCard).join("") || emptySide()}</div>
    </div>` : `<p style="padding:20px 0">No featured events yet — check back soon.</p>`}
  </section>

  <section class="section container">
    <div class="section-head"><div><h2>Happening soon</h2><p>The next events across every category.</p></div><a class="link-more" href="#/events">Browse all events${icon("chevronR", 16)}</a></div>
    <div class="grid">${upcomingRes.events.map(EV.eventCard).join("") || emptyState()}</div>
  </section>

  <section class="section container">
    <div class="section-head"><div><h2>How it works</h2></div></div>
    <div class="steps">
      <div class="step"><span class="n">1</span><h3>Find your event</h3><p>Search by city, category or date, and see real ticket availability before you book.</p></div>
      <div class="step"><span class="n">2</span><h3>Choose your tier</h3><p>Early Bird, Regular or VIP — pick what fits, pay securely, and you're booked in seconds.</p></div>
      <div class="step"><span class="n">3</span><h3>Walk in with a QR code</h3><p>Your ticket lands in your inbox as a PDF. Show the QR code at the door — that's it.</p></div>
    </div>
  </section>

  <section class="section container">
    <div class="promo">
      <div><h2>Hosting something unforgettable?</h2><p>List tiered tickets, sell securely and check guests in with a phone camera — no extra hardware.</p></div>
      <a class="btn btn-lg" href="#/create">${icon("plus", 18)}Create Your Event</a>
    </div>
  </section>`;

  setTimeout(() => {
    $("#hero-explore").addEventListener("click", (e) => { e.preventDefault(); submitHeroSearch(); });
    $("#hero-search").addEventListener("submit", (e) => { e.preventDefault(); submitHeroSearch(); });
  });
  return html;
});

function simpleQr() {
  // Decorative mini QR pattern for the hero mock ticket (not a real code).
  const cells = [1, 1, 1, 0, 1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 1, 0, 1, 0, 1, 1, 1, 0, 1, 1, 1, 1, 0, 1, 0, 1, 0, 0, 0, 0, 1, 1, 1, 0, 1, 1, 0, 1, 1, 0, 1, 0, 1, 1, 1, 0, 1, 0, 1, 1, 1, 0, 0, 1, 0, 0, 1, 0, 1, 1, 1, 0, 1, 0, 1, 1, 1, 0, 1, 0, 0, 1, 1, 1, 0, 1, 0, 1];
  let path = ""; const n = 9;
  for (let i = 0; i < cells.length; i++) if (cells[i]) { const x = i % n, y = Math.floor(i / n); path += `M${x} ${y}h1v1h-1z`; }
  return `<svg viewBox="0 0 9 9" width="100%" height="100%"><rect width="9" height="9" fill="#fff"/><path d="${path}" fill="#0B1020"/></svg>`;
}
function submitHeroSearch() {
  const f = $("#hero-search");
  location.hash = "#/events" + qs({ q: f.q.value, city: f.city.value, date: f.date.value });
}
function categoryCard(c) {
  return `<a class="cat-card" href="#/events${qs({ category: c.name })}">
    <span class="cat-ic">${icon(EV.catIcon(c.name), 26)}</span>
    <span class="cat-info"><h3>${esc(c.name)}</h3><small>${c.count} event${c.count === 1 ? "" : "s"}</small></span></a>`;
}
function sideCard(e) {
  return `<article class="card ev-card">
    ${EV.eventThumb(e)}
    <div class="ev-body">
      <h3>${esc(e.title)}</h3>
      <ul class="meta"><li class="date">${icon("calendar", 15)}${fmtDate(e.starts_at, { month: "short", day: "numeric" })}</li><li>${icon("location", 15)}${esc(e.city)}</li></ul>
      <div class="inline-price"><span class="price" style="font-size:1.05rem">${e.max_price_cents === 0 ? "Free" : money(e.min_price_cents)}</span><a class="btn btn-secondary btn-sm" href="#/events/${e.id}">View</a></div>
    </div></article>`;
}
function emptySide() { return `<div class="empty" style="grid-column:1/-1"><p>More featured events coming soon.</p></div>`; }
function emptyState(msg) {
  return `<div class="empty" style="grid-column:1/-1">
    <span class="ic-wrap">${icon("calendar", 28)}</span><h3>No events found</h3><p>${esc(msg || "Try a different search or check back soon.")}</p></div>`;
}
EV.emptyState = emptyState;

/* ===================================================================== EVENTS LIST */
EV.page("/events", async (params, query) => {
  const meta = EV.state.meta || { categories: [], cities: [] };
  const state = { q: query.get("q") || "", category: query.get("category") || "", city: query.get("city") || "", date: query.get("date") || "",
                  sort: query.get("sort") || "soonest", featured: query.get("featured") === "1", offset: 0 };

  const html = `
  <section class="page-head container">
    <h1>${state.category ? esc(state.category) + " events" : "All events"}</h1>
    <p>Search across every event on Event Vault, and filter by category, city or date.</p>
  </section>
  <section class="container">
    <form id="filters" class="filters">
      <label class="sr-only" for="f-q">Search</label><input id="f-q" placeholder="Search events, venues, cities…" value="${esc(state.q)}">
      <label class="sr-only" for="f-city">City</label><select id="f-city"><option value="">Any city</option>${meta.cities.map((c) => `<option ${c === state.city ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>
      <label class="sr-only" for="f-date">Date</label><input id="f-date" type="date" value="${esc(state.date)}">
      <label class="sr-only" for="f-sort">Sort</label><select id="f-sort">
        <option value="soonest" ${state.sort === "soonest" ? "selected" : ""}>Soonest first</option>
        <option value="newest" ${state.sort === "newest" ? "selected" : ""}>Newest listed</option>
        <option value="price_low" ${state.sort === "price_low" ? "selected" : ""}>Price: low to high</option>
        <option value="price_high" ${state.sort === "price_high" ? "selected" : ""}>Price: high to low</option>
      </select>
    </form>
    <div class="chips" id="chips">
      <button type="button" class="chip" data-cat="" aria-pressed="${!state.category}">All</button>
      ${meta.categories.map((c) => `<button type="button" class="chip" data-cat="${esc(c.name)}" aria-pressed="${state.category === c.name}">${esc(c.name)}</button>`).join("")}
    </div>
    <div class="result-bar"><span id="result-count">Searching…</span></div>
    <div class="grid" id="ev-grid">${EV.skeletons(6)}</div>
    <div style="text-align:center;margin-top:30px" id="more-wrap"></div>
  </section>`;

  setTimeout(() => wireEventsList(state));
  return html;
});

async function wireEventsList(state) {
  const grid = $("#ev-grid"), count = $("#result-count"), moreWrap = $("#more-wrap");
  const LIMIT = 9;
  async function load(reset) {
    if (reset) { state.offset = 0; grid.innerHTML = EV.skeletons(6); count.textContent = "Searching…"; }
    let data;
    try { data = await EV.api.get("/events" + qs({ q: state.q, category: state.category, city: state.city, date: state.date, sort: state.sort, featured: state.featured, limit: LIMIT, offset: state.offset })); }
    catch (e) { grid.innerHTML = ""; count.textContent = ""; EV.toast(e.message, "err"); return; }
    const cards = data.events.map(EV.eventCard).join("");
    grid.innerHTML = (state.offset === 0 ? cards : grid.innerHTML + cards) || (state.offset === 0 ? emptyState("Try a wider search or clear a filter.") : grid.innerHTML);
    count.innerHTML = data.total ? `<b>${data.total}</b> event${data.total === 1 ? "" : "s"} found` : "No events match those filters.";
    state.offset += data.events.length;
    moreWrap.innerHTML = state.offset < data.total ? `<button class="btn btn-secondary" id="load-more">Load more events</button>` : "";
    const btn = $("#load-more"); if (btn) btn.onclick = () => load(false);
  }
  const run = debounce(() => load(true), 320);
  $("#f-q").addEventListener("input", (e) => { state.q = e.target.value; run(); });
  $("#f-city").addEventListener("change", (e) => { state.city = e.target.value; load(true); });
  $("#f-date").addEventListener("change", (e) => { state.date = e.target.value; load(true); });
  $("#f-sort").addEventListener("change", (e) => { state.sort = e.target.value; load(true); });
  $$("#chips .chip").forEach((c) => c.addEventListener("click", () => { state.category = c.dataset.cat; $$("#chips .chip").forEach((x) => x.setAttribute("aria-pressed", x === c)); load(true); }));
  load(true);
}

/* ===================================================================== EVENT DETAIL */
EV.page("/events/:id", async (params) => {
  let e;
  try { e = await EV.api.get(`/events/${params.id}`); }
  catch (err) { return EV.notFound(); }

  const relatedPromise = EV.api.get("/events" + qs({ category: e.category, limit: 3, exclude: e.id })).catch(() => ({ events: [] }));
  const priceRange = e.max_price_cents === 0 ? "Free" : (e.min_price_cents === e.max_price_cents ? money(e.min_price_cents) : `${money(e.min_price_cents)} – ${money(e.max_price_cents)}`);
  const seatsClass = e.seats_left === 0 ? "out" : e.seats_left <= 10 ? "low" : "";
  const isOwner = EV.state.user && EV.state.user.id === e.organizer_id;

  const html = `
  <section class="container">
    <div class="banner">${e.image_url ? `<div class="media"><img src="${e.image_url}" alt=""></div>` : (() => { const [a, b] = EV.catColors(e.category); return `<div class="media"><div class="cover" style="--a:${a};--b:${b};height:100%"><span class="cover-ic">${icon(EV.catIcon(e.category), 220)}</span></div></div>`; })()}
      <div class="banner-copy">
        <span class="badge gold" style="width:max-content">${esc(e.category)}${e.featured ? " · Featured" : ""}</span>
        <h1>${esc(e.title)}</h1>
      </div></div>
  </section>

  <section class="container detail">
    <div>
      <div class="facts">
        <div class="fact gold"><span class="ic-wrap">${icon("calendar", 20)}</span><div><small>Date & time</small><b>${fmtDate(e.starts_at)}<br>${fmtTime(e.starts_at)}</b></div></div>
        <div class="fact"><span class="ic-wrap">${icon("location", 20)}</span><div><small>Location</small><b>${esc(e.venue)}<br>${esc(e.city)}</b></div></div>
        <div class="fact"><span class="ic-wrap">${icon("ticket", 20)}</span><div><small>Tickets</small><b>${priceRange}<br>${e.seats_left} seats left</b></div></div>
      </div>
      <div class="prose">
        <h2>About this event</h2>
        ${e.description.split("\n").filter(Boolean).map((p) => `<p>${esc(p)}</p>`).join("")}
      </div>
      <div class="organizer">
        <span class="avatar">${esc(e.organizer_name.trim().split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase())}</span>
        <div class="info"><small>Organised by</small><b>${esc(e.organizer_name)}</b></div>
        <a class="contact" href="mailto:${esc(e.contact_email)}">${icon("mail", 16)}${esc(e.contact_email)}</a>
        ${e.contact_phone ? `<a class="contact" href="tel:${esc(e.contact_phone)}">${icon("phone", 16)}${esc(e.contact_phone)}</a>` : ""}
        ${isOwner ? `<a class="btn btn-secondary btn-sm" href="#/dashboard/events/${e.id}/edit" style="margin-left:auto">${icon("edit", 16)}Edit event</a>` : ""}
      </div>
      <div id="related-wrap"></div>
    </div>

    <aside class="card book">
      <h2>Book Now</h2>
      <div class="seats ${seatsClass}"><span class="dot"></span>${e.sold_out ? "Sold out" : e.seats_left + " seats left"}</div>
      <div id="tier-list">${e.tiers.map((t, i) => tierRow(t, i)).join("") || `<p>No ticket types are set up yet.</p>`}</div>
      <div class="total"><span>Total</span><b id="cart-total">${money(0)}</b></div>
      <button class="btn btn-primary btn-block btn-lg" id="book-btn" ${e.sold_out ? "disabled" : ""}>${icon("ticket", 18)}${e.sold_out ? "Sold Out" : "Book Now"}</button>
      <p class="fine">${e.max_price_cents === 0 ? "Free tickets — instant confirmation." : "Secure checkout. Tickets are emailed as PDF with a QR code."}</p>
      <div class="share-row">
        <button class="btn btn-ghost btn-sm" id="share-btn" style="flex:1">${icon("share", 16)}Share</button>
        <a class="btn btn-ghost btn-sm" href="#/events/${e.id}" style="flex:1;justify-content:center">${icon("location", 16)}${esc(e.city)}</a>
      </div>
    </aside>
  </section>`;

  setTimeout(async () => {
    wireBooking(e);
    $("#share-btn").addEventListener("click", () => shareEvent(e));
    try {
      const rel = await relatedPromise;
      if (rel.events.length) $("#related-wrap").innerHTML = `<div class="prose"><h2>Related events</h2><div class="grid">${rel.events.map(EV.eventCard).join("")}</div></div>`;
    } catch {}
  });
  return html;
});

function tierRow(t, i) {
  const out = t.available === 0;
  return `<div class="tier ${out ? "out" : ""}" data-tier="${t.id}" data-price="${t.price_cents}" data-max="${t.available}">
    <div><b>${esc(t.name)}</b></div><div class="p">${t.price_cents === 0 ? "Free" : money(t.price_cents)}</div>
    <div class="left">${out ? "Sold out" : t.available + " left"}</div>
    ${out ? "" : `<div class="stepper">
      <button type="button" data-dec aria-label="Fewer ${esc(t.name)} tickets">${icon("minus", 15)}</button>
      <output>0</output>
      <button type="button" data-inc aria-label="More ${esc(t.name)} tickets">${icon("plus", 15)}</button>
    </div>`}
  </div>`;
}

function wireBooking(e) {
  const list = $("#tier-list");
  const max = EV.state.meta?.max_tickets || 10;
  function recalc() {
    let total = 0, count = 0;
    $$(".tier", list).forEach((row) => {
      const n = parseInt($("output", row)?.textContent || "0", 10);
      total += n * parseInt(row.dataset.price, 10);
      count += n;
      row.classList.toggle("picked", n > 0);
    });
    $("#cart-total").textContent = money(total);
    const btn = $("#book-btn");
    if (!btn.dataset.soldout) btn.disabled = count === 0;
  }
  list.addEventListener("click", (ev) => {
    const row = ev.target.closest(".tier"); if (!row) return;
    const out = $("output", row); const rowMax = Math.min(parseInt(row.dataset.max, 10), max);
    const total = $$(".tier", list).reduce((s, r) => s + parseInt($("output", r)?.textContent || "0", 10), 0);
    if (ev.target.closest("[data-inc]")) { const v = parseInt(out.textContent, 10); if (v < rowMax && total < max) out.textContent = v + 1; else EV.toast(total >= max ? `You can book up to ${max} tickets per order.` : "No more available in this tier.", "err"); }
    if (ev.target.closest("[data-dec]")) { const v = parseInt(out.textContent, 10); if (v > 0) out.textContent = v - 1; }
    recalc();
  });
  if ($("#book-btn").disabled) $("#book-btn").dataset.soldout = "1";
  $("#book-btn").addEventListener("click", async () => {
    if (!EV.requireLogin("Log in to book tickets.")) return;
    const items = $$(".tier", list).map((r) => ({ tier_id: parseInt(r.dataset.tier, 10), quantity: parseInt($("output", r)?.textContent || "0", 10) })).filter((i) => i.quantity > 0);
    if (!items.length) return;
    const btn = $("#book-btn"); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
    try {
      const res = await EV.api.post("/checkout", { event_id: e.id, items });
      if (res.mode === "stripe") { location.href = res.url; return; }
      EV.toast("Booked! Your tickets are ready.", "ok");
      location.hash = `#/order/${res.order_ref}`;
    } catch (err) { EV.toast(err.message, "err"); btn.disabled = false; btn.innerHTML = icon("ticket", 18) + "Book Now"; recalc(); }
  });
}

async function shareEvent(e) {
  const url = location.origin + location.pathname + `#/events/${e.id}`;
  if (navigator.share) { try { await navigator.share({ title: e.title, url }); } catch {} return; }
  try { await navigator.clipboard.writeText(url); EV.toast("Link copied to clipboard.", "ok"); } catch { EV.toast(url, "ok"); }
}

/* ===================================================================== CATEGORIES */
EV.page("/categories", async () => {
  const meta = EV.state.meta || { categories: [] };
  return `<section class="page-head container"><h1>Categories</h1><p>Every event on Event Vault, grouped by the kind of experience it is.</p></section>
  <section class="container section" style="padding-top:0"><div class="cat-grid">${meta.categories.map(categoryCard).join("")}</div></section>`;
});

/* ===================================================================== ABOUT */
EV.page("/about", async () => `
  <section class="hero" style="padding-bottom:40px">
    <div class="hero-glow g1"></div>
    <div class="container">
      <h1 style="max-width:16ch">Built for the moments worth <span class="grad-text">remembering</span>.</h1>
      <p class="lead" style="margin-top:20px">Event Vault is a ticketing platform for organisers who want their events to feel as good behind the scenes as they do on the night. Tiered pricing, instant QR tickets and a check-in scanner that just works.</p>
    </div>
  </section>
  <section class="section container">
    <div class="feature-grid">
      ${aboutFeature("ticket", "Tiered ticketing", "Early Bird, Regular and VIP — set your own prices and capacity for each, and watch sales update live.")}
      ${aboutFeature("mail", "Tickets that arrive instantly", "Every purchase generates a unique QR-coded PDF ticket, emailed the moment payment clears.")}
      ${aboutFeature("camera", "Check-in from any phone", "Scan tickets at the door with nothing but a camera. Used tickets are blocked automatically, even if two doors scan at once.")}
      ${aboutFeature("chart", "A dashboard that tells the truth", "Track sales, revenue and check-ins for every event you run, in one place.")}
    </div>
  </section>
  <section class="section container">
    <div class="promo">
      <div><h2>Ready to host your first event?</h2><p>It takes a few minutes to list tickets and start selling.</p></div>
      <a class="btn btn-lg" href="#/create">${icon("plus", 18)}Create Event</a>
    </div>
  </section>`);
function aboutFeature(ic, title, body) { return `<div class="feature"><span class="cat-ic">${icon(ic, 24)}</span><h3>${esc(title)}</h3><p>${esc(body)}</p></div>`; }

/* ===================================================================== CONTACT */
EV.page("/contact", async () => {
  const html = `<section class="page-head container"><h1>Contact us</h1><p>Questions about an event, a booking, or hosting on Event Vault? We'll get back to you.</p></section>
  <section class="container section" style="padding-top:0"><div class="contact-grid">
    <form class="card form-card" id="contact-form">
      <h2>Send a message</h2><p class="sub">We typically reply within one business day.</p>
      <div id="contact-alert"></div>
      <div class="form-grid" style="margin-top:12px">
        <div class="field"><label for="c-name">Name</label><input id="c-name" required></div>
        <div class="field"><label for="c-email">Email</label><input id="c-email" type="email" required></div>
        <div class="field full"><label for="c-msg">Message</label><textarea id="c-msg" required minlength="10"></textarea></div>
      </div>
      <div class="form-actions"><button class="btn btn-primary btn-lg" type="submit">${icon("mail", 18)}Send message</button></div>
    </form>
    <div class="card info-card">
      <h3>Other ways to reach us</h3>
      <ul>
        <li>${icon("mail", 20)}<div><b>Email</b><span>support@eventvault.example</span></div></li>
        <li>${icon("phone", 20)}<div><b>Phone</b><span>+1 (555) 010-0199</span></div></li>
        <li>${icon("location", 20)}<div><b>Office</b><span>148 Harbor Row, San Francisco, CA</span></div></li>
      </ul>
    </div>
  </div></section>`;
  setTimeout(() => {
    $("#contact-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const alertBox = $("#contact-alert"); alertBox.innerHTML = "";
      const btn = e.target.querySelector("button"); btn.disabled = true; const orig = btn.innerHTML; btn.innerHTML = '<span class="spinner"></span>';
      try {
        await EV.api.post("/contact", { name: $("#c-name").value, email: $("#c-email").value, message: $("#c-msg").value });
        e.target.reset(); alertBox.innerHTML = `<div class="alert ok">${icon("check", 18)}Message sent — thanks for reaching out.</div>`;
      } catch (err) { alertBox.innerHTML = `<div class="alert err">${icon("alert", 18)}${esc(err.message)}</div>`; }
      btn.disabled = false; btn.innerHTML = orig;
    });
  });
  return html;
});

/* ===================================================================== AUTH */
function passwordField(id, label) {
  return `<div class="field"><label for="${id}">${label}</label><div class="pw"><input id="${id}" type="password" autocomplete="${id === "reg-pw" ? "new-password" : "current-password"}" minlength="8" required>
    <button type="button" data-toggle aria-label="Show password">${icon("eye", 18)}</button></div></div>`;
}
function wirePasswordToggle(root) {
  $$("[data-toggle]", root).forEach((btn) => btn.addEventListener("click", () => {
    const input = btn.previousElementSibling; const show = input.type === "password";
    input.type = show ? "text" : "password"; btn.innerHTML = icon(show ? "eyeOff" : "eye", 18); btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
  }));
}

EV.page("/login", async (_, query) => {
  const next = query.get("next") || "/";
  const html = `<section class="auth"><div class="auth-card">
    <a class="logo" href="#/"><svg width="34" height="34"><use href="#logo-mark"/></svg>Event Vault</a>
    <h1>Welcome back</h1><p>Log in to book tickets, manage events and check guests in.</p>
    <div id="auth-alert"></div>
    <form id="login-form">
      <div class="field"><label for="li-email">Email</label><input id="li-email" type="email" autocomplete="email" required></div>
      ${passwordField("li-pw", "Password")}
      <button class="btn btn-primary btn-block btn-lg" type="submit">Log In</button>
    </form>
    <p class="switch">New to Event Vault? <a href="#/register${next !== "/" ? "?next=" + encodeURIComponent(next) : ""}">Create an account</a></p>
  </div></section>`;
  setTimeout(() => {
    wirePasswordToggle(document);
    $("#login-form").addEventListener("submit", async (e) => {
      e.preventDefault(); const alertBox = $("#auth-alert"); alertBox.innerHTML = "";
      const btn = e.target.querySelector("button"); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
      try {
        const res = await EV.api.post("/auth/login", { email: $("#li-email").value.trim(), password: $("#li-pw").value });
        EV.state.user = res.user; EV.toast(`Welcome back, ${res.user.name.split(" ")[0]}.`, "ok");
        EV.renderAuthSlot();
        location.hash = "#" + next;
      } catch (err) { alertBox.innerHTML = `<div class="alert err">${icon("alert", 18)}${esc(err.message)}</div>`; btn.disabled = false; btn.innerHTML = "Log In"; }
    });
  });
  return html;
});

EV.page("/register", async (_, query) => {
  const next = query.get("next") || "/";
  const html = `<section class="auth"><div class="auth-card">
    <a class="logo" href="#/"><svg width="34" height="34"><use href="#logo-mark"/></svg>Event Vault</a>
    <h1>Create your account</h1><p>Book tickets and host your own events in a couple of minutes.</p>
    <div id="auth-alert"></div>
    <form id="reg-form">
      <div class="field"><label for="reg-name">Full name</label><input id="reg-name" required minlength="2"></div>
      <div class="field"><label for="reg-email">Email</label><input id="reg-email" type="email" autocomplete="email" required></div>
      ${passwordField("reg-pw", "Password")}
      <p class="hint" style="color:var(--muted);font-size:.82rem;margin-top:-8px">At least 8 characters.</p>
      <button class="btn btn-primary btn-block btn-lg" type="submit">Create Account</button>
    </form>
    <p class="switch">Already have an account? <a href="#/login${next !== "/" ? "?next=" + encodeURIComponent(next) : ""}">Log in</a></p>
  </div></section>`;
  setTimeout(() => {
    wirePasswordToggle(document);
    $("#reg-form").addEventListener("submit", async (e) => {
      e.preventDefault(); const alertBox = $("#auth-alert"); alertBox.innerHTML = "";
      const btn = e.target.querySelector("button"); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
      try {
        const res = await EV.api.post("/auth/register", { name: $("#reg-name").value.trim(), email: $("#reg-email").value.trim(), password: $("#reg-pw").value });
        EV.state.user = res.user; EV.toast(`Welcome to Event Vault, ${res.user.name.split(" ")[0]}.`, "ok");
        EV.renderAuthSlot();
        location.hash = "#" + next;
      } catch (err) { alertBox.innerHTML = `<div class="alert err">${icon("alert", 18)}${esc(err.message)}</div>`; btn.disabled = false; btn.innerHTML = "Create Account"; }
    });
  });
  return html;
});

})(window.EV);
