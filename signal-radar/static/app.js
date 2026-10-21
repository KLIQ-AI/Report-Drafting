"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const list = (s) => String(s || "").split(",").map((x) => x.trim()).filter(Boolean);
const numOrNull = (v) => (v === "" || v == null ? null : Number(v));

function apiKey() {
  try { return localStorage.getItem("sr_api_key") || ""; } catch { return ""; }
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", "X-API-Key": apiKey() },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401) {
    const key = prompt("API key for this Signal Radar server:");
    if (key) {
      try { localStorage.setItem("sr_api_key", key); } catch {}
      return api(path, opts);
    }
  }
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(typeof detail.detail === "string" ? detail.detail : `Request failed (${res.status})`);
  }
  return res.status === 204 ? null : res.json();
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), 2600);
}

async function busy(btn, fn) {
  btn.disabled = true;
  const label = btn.textContent;
  btn.textContent = "Working…";
  try { return await fn(); }
  catch (e) { toast(e.message); }
  finally { btn.disabled = false; btn.textContent = label; }
}

const heat = (n) => (n >= 70 ? "hot" : n >= 40 ? "warm" : "cold");
const ago = (iso) => {
  if (!iso) return "never";
  const m = Math.round((Date.now() - new Date(iso)) / 60000);
  if (m < 60) return `${m}m ago`;
  if (m < 1440) return `${Math.round(m / 60)}h ago`;
  return `${Math.round(m / 1440)}d ago`;
};

/* ---------- routing between views ---------- */
function show(view) {
  $$(".view").forEach((v) => (v.hidden = v.id !== `view-${view}`));
  $$("nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  ({ leads: loadLeads, monitors: loadMonitors, icp: loadICP, integrations: loadRouting }[view] || loadLeads)();
}
window.addEventListener("hashchange", () => show(location.hash.slice(1) || "leads"));

/* ---------- status + stats ---------- */
async function loadStatus() {
  const s = await api("/api/status");
  $("#status").innerHTML = `
    <div>Data: <b>${esc(s.provider)}</b></div>
    <div>Scoring: <b>${esc(s.scoring === "claude" ? "Claude AI" : "heuristic")}</b></div>
    <div>Enrichment: <b>${esc(s.enrichment)}</b></div>
    <div>Auto-run: <b>${s.run_interval_minutes ? `every ${s.run_interval_minutes}m` : "off"}</b></div>`;
}

async function loadStats() {
  const s = await api("/api/stats");
  const items = [["Active monitors", s.monitors], ["Posts scanned", s.posts], ["Engagements", s.signals],
                 ["Leads", s.leads], ["Qualified", s.qualified], ["New this month", s.leads_this_month]];
  $("#stats").innerHTML = items.map(([l, n]) => `<div class="stat"><div class="n">${n}</div><div class="l">${l}</div></div>`).join("");
}

/* ---------- leads ---------- */
function leadQuery() {
  const p = new URLSearchParams();
  if ($("#f-q").value) p.set("q", $("#f-q").value);
  if ($("#f-status").value) p.set("status", $("#f-status").value);
  if ($("#f-monitor").value) p.set("monitor_id", $("#f-monitor").value);
  if (+$("#f-intent").value) p.set("min_intent", $("#f-intent").value);
  return p.toString();
}

async function loadLeads() {
  loadStats();
  const monitors = await api("/api/monitors");
  const sel = $("#f-monitor");
  const current = sel.value;
  sel.innerHTML = `<option value="">All monitors</option>` +
    monitors.map((m) => `<option value="${m.id}">${esc(m.name)}</option>`).join("");
  sel.value = current;

  const q = leadQuery();
  const csvQ = new URLSearchParams(q);
  if (apiKey()) csvQ.set("api_key", apiKey());
  $("#btn-export").href = `/api/leads.csv?${csvQ}`;
  const leads = await api(`/api/leads${q ? "?" + q : ""}`);
  $("#lead-empty").hidden = leads.length > 0;
  $("#lead-rows").innerHTML = leads.map((l) => `
    <tr data-id="${l.id}">
      <td class="person"><b>${esc(l.name)}</b><span>${esc(l.title || l.headline)}</span></td>
      <td class="company">${esc(l.company)}<br><span>${l.company_size ? esc(l.company_size) + " emp · " : ""}${esc(l.location)}</span></td>
      <td><span class="score ${heat(l.intent_score)}">${l.intent_score}</span></td>
      <td>${l.icp_fit}<div class="bar"><i style="width:${l.icp_fit}%"></i></div></td>
      <td class="signal">${l.last_comment ? `💬 <q>${esc(l.last_comment.slice(0, 110))}</q>` : `👍 ${l.signal_count} reaction${l.signal_count === 1 ? "" : "s"}`}
          <br><span class="pill ${esc(l.status)}">${esc(l.status)}</span> ${esc(l.buying_stage.replace(/_/g, " "))}</td>
      <td><a href="${esc(l.profile_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">LinkedIn ↗</a></td>
    </tr>`).join("");
}

$("#lead-rows").addEventListener("click", (e) => {
  const tr = e.target.closest("tr[data-id]");
  if (tr) openLead(+tr.dataset.id);
});
["#f-status", "#f-monitor"].forEach((s) => $(s).addEventListener("change", loadLeads));
$("#f-q").addEventListener("input", () => { clearTimeout(loadLeads._t); loadLeads._t = setTimeout(loadLeads, 250); });
$("#f-intent").addEventListener("input", (e) => { e.target.nextElementSibling.value = e.target.value; });
$("#f-intent").addEventListener("change", loadLeads);

$("#btn-run-all").addEventListener("click", (e) => busy(e.target, async () => {
  const runs = await api("/api/run-all", { method: "POST" });
  const n = runs.reduce((a, r) => a + r.new_leads, 0);
  const errs = runs.filter((r) => r.error);
  toast(errs.length ? `Finished with ${errs.length} error(s): ${errs[0].error}` : `Done: ${n} new lead${n === 1 ? "" : "s"}`);
  loadLeads();
}));

/* ---------- lead drawer ---------- */
function closeDrawer() { $("#drawer").hidden = true; $("#drawer-backdrop").hidden = true; }
$("#drawer-backdrop").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => e.key === "Escape" && closeDrawer());

async function openLead(id) {
  const l = await api(`/api/leads/${id}`);
  const d = $("#drawer");
  d.innerHTML = `
    <button class="btn ghost small close" data-act="close">✕</button>
    <h2>${esc(l.name)}</h2>
    <div class="muted">${esc(l.headline)}</div>
    <div class="row">
      <span class="score ${heat(l.intent_score)}">Intent ${l.intent_score}</span>
      <span class="score cold">ICP ${l.icp_fit}</span>
      <span class="pill ${esc(l.status)}">${esc(l.status)}</span>
    </div>
    <div class="section"><h3>Why</h3><div>${esc(l.intent_reason) || "—"}</div>
      <div class="muted" style="font-size:12px;margin-top:4px">Scored by ${esc(l.scored_by || "—")} · ${esc(l.sentiment)} · ${esc(l.buying_stage.replace(/_/g, " "))}</div></div>
    ${l.suggested_opener ? `<div class="section"><h3>Suggested opener</h3><div class="opener">${esc(l.suggested_opener)}</div>
      <div class="row"><button class="btn ghost small" data-act="copy">Copy</button></div></div>` : ""}
    <div class="section"><h3>Contact</h3><dl class="kv">
      <dt>Company</dt><dd>${esc(l.company)} ${l.company_domain ? `(${esc(l.company_domain)})` : ""}</dd>
      <dt>Size</dt><dd>${esc(l.company_size ?? "—")}</dd>
      <dt>Industry</dt><dd>${esc(l.industry || "—")}</dd>
      <dt>Location</dt><dd>${esc(l.location || "—")}</dd>
      <dt>Email</dt><dd>${l.email ? `${esc(l.email)} <span class="pill">${esc(l.email_status)}</span>` : "—"}</dd>
      <dt>LinkedIn</dt><dd><a href="${esc(l.profile_url)}" target="_blank" rel="noopener">${esc(l.profile_url)}</a></dd>
    </dl></div>
    <div class="section"><h3>Signals (${l.signals.length})</h3>
      ${l.signals.map((s) => `<div class="sig">
        ${s.kind === "comment" ? `💬 Commented: <q>${esc(s.comment_text)}</q>` : `👍 Reacted <b>${esc(s.reaction_type || "like")}</b>`}
        <div class="post">On <a href="${esc(s.post_url)}" target="_blank" rel="noopener">${esc(s.author_name || "a post")}'s post</a>
          · ${esc(s.monitor_name)}${s.is_competitor ? '<span class="tag">competitor</span>' : ""} · ${ago(s.created_at)}<br>
          “${esc((s.post_text || "").slice(0, 200))}”</div></div>`).join("")}
    </div>
    ${l.deliveries.length ? `<div class="section"><h3>Deliveries</h3>${l.deliveries.map((x) =>
      `<div>${x.ok ? "✅" : "⚠️"} ${esc(x.destination)} · ${esc(x.detail)} · ${ago(x.created_at)}</div>`).join("")}</div>` : ""}
    <div class="row">
      <button class="btn small" data-act="status" data-v="contacted">Mark contacted</button>
      <button class="btn ghost small" data-act="push">Push to integrations</button>
      <button class="btn ghost small" data-act="rescore">Re-score</button>
      <button class="btn danger small" data-act="status" data-v="disqualified">Disqualify</button>
    </div>`;
  d.hidden = false;
  $("#drawer-backdrop").hidden = false;
  d.onclick = (e) => {
    const b = e.target.closest("[data-act]");
    if (!b) return;
    const act = b.dataset.act;
    if (act === "close") return closeDrawer();
    if (act === "copy") return navigator.clipboard.writeText(l.suggested_opener).then(() => toast("Copied"));
    busy(b, async () => {
      if (act === "status") await api(`/api/leads/${id}`, { method: "PATCH", body: { status: b.dataset.v } });
      if (act === "rescore") await api(`/api/leads/${id}/rescore`, { method: "POST" });
      if (act === "push") {
        const r = await api(`/api/leads/${id}/push`, { method: "POST" });
        toast(r.length ? r.map((x) => `${x.destination}: ${x.ok ? "sent" : x.detail}`).join(" · ") : "No destinations configured");
      }
      await openLead(id);
      loadLeads();
    });
  };
}

/* ---------- monitors ---------- */
async function loadMonitors() {
  const ms = await api("/api/monitors");
  $("#monitor-list").innerHTML = ms.length ? ms.map((m) => `
    <div class="card monitor ${m.active ? "" : "inactive"}" data-id="${m.id}">
      <div>
        <b>${esc(m.name)}</b>${m.is_competitor ? '<span class="tag">competitor</span>' : ""}
        <div class="q">${esc(m.kind)}: ${esc(m.query)}${m.exclude_keywords ? ` · excl. ${esc(m.exclude_keywords)}` : ""}</div>
        <div class="meta">${m.post_count} posts · ${m.lead_count} people · last run ${ago(m.last_run_at)}</div>
      </div>
      <div class="btns">
        <button class="btn small" data-act="run">Run now</button>
        <button class="btn ghost small" data-act="toggle">${m.active ? "Pause" : "Resume"}</button>
        <button class="btn danger small" data-act="delete">Delete</button>
      </div>
    </div>`).join("") : `<div class="empty">No monitors yet. Add one above.</div>`;
}

$("#monitor-list").addEventListener("click", (e) => {
  const b = e.target.closest("[data-act]");
  if (!b) return;
  const card = b.closest("[data-id]");
  const id = card.dataset.id;
  busy(b, async () => {
    if (b.dataset.act === "run") {
      const r = await api(`/api/monitors/${id}/run`, { method: "POST" });
      toast(r.error ? `Error: ${r.error}` : `${r.posts_found} posts · ${r.signals_found} engagements · ${r.new_leads} new leads`);
    }
    if (b.dataset.act === "toggle") {
      await api(`/api/monitors/${id}`, { method: "PATCH", body: { active: card.classList.contains("inactive") } });
    }
    if (b.dataset.act === "delete" && confirm("Delete this monitor and leads found only by it?")) {
      await api(`/api/monitors/${id}`, { method: "DELETE" });
    }
    loadMonitors();
  });
});

$("#monitor-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  try {
    await api("/api/monitors", { method: "POST", body: {
      name: f.name.value, kind: f.kind.value, query: f.query.value,
      exclude_keywords: f.exclude_keywords.value, is_competitor: f.is_competitor.checked,
    } });
    f.reset();
    toast("Monitor added");
    loadMonitors();
  } catch (err) { toast(err.message); }
});

/* ---------- ICP & offer ---------- */
async function loadICP() {
  const [icp, offer] = await Promise.all([api("/api/settings/icp"), api("/api/settings/offer")]);
  const f = $("#icp-form");
  f.titles_include.value = icp.titles_include.join(", ");
  f.titles_exclude.value = icp.titles_exclude.join(", ");
  f.company_size_min.value = icp.company_size_min ?? "";
  f.company_size_max.value = icp.company_size_max ?? "";
  f.industries.value = icp.industries.join(", ");
  f.locations.value = icp.locations.join(", ");
  $$(".seniority input", f).forEach((c) => (c.checked = icp.seniorities.includes(c.value)));
  f.product.value = offer.product;
  f.value_prop.value = offer.value_prop;
  f.competitors.value = offer.competitors.join(", ");
}

async function saveICP() {
  const f = $("#icp-form");
  await api("/api/settings/icp", { method: "PUT", body: {
    titles_include: list(f.titles_include.value), titles_exclude: list(f.titles_exclude.value),
    seniorities: $$(".seniority input:checked", f).map((c) => c.value),
    company_size_min: numOrNull(f.company_size_min.value), company_size_max: numOrNull(f.company_size_max.value),
    industries: list(f.industries.value), locations: list(f.locations.value),
  } });
  await api("/api/settings/offer", { method: "PUT", body: {
    product: f.product.value, value_prop: f.value_prop.value, competitors: list(f.competitors.value),
  } });
}

$("#icp-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try { await saveICP(); toast("Saved"); } catch (err) { toast(err.message); }
});
$("#btn-rescore").addEventListener("click", (e) => busy(e.target, async () => {
  await saveICP();
  const r = await api("/api/rescore-all", { method: "POST" });
  toast(`Re-scored ${r.rescored} leads`);
}));

/* ---------- integrations ---------- */
async function loadRouting() {
  const r = await api("/api/settings/routing");
  const f = $("#routing-form");
  for (const k of ["min_icp_fit", "min_intent", "webhook_url", "slack_webhook_url"]) f[k].value = r[k] ?? "";
}

async function saveRouting() {
  const f = $("#routing-form");
  await api("/api/settings/routing", { method: "PUT", body: {
    min_icp_fit: +f.min_icp_fit.value, min_intent: +f.min_intent.value,
    webhook_url: f.webhook_url.value, slack_webhook_url: f.slack_webhook_url.value,
  } });
}

$("#routing-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try { await saveRouting(); toast("Saved"); } catch (err) { toast(err.message); }
});
$("#btn-test").addEventListener("click", (e) => busy(e.target, async () => {
  await saveRouting();
  const r = await api("/api/destinations/test", { method: "POST" });
  const parts = Object.entries(r).map(([k, v]) => `${k}: ${v.ok ? "ok" : v.detail}`);
  toast(parts.length ? parts.join(" · ") : "No destinations configured");
}));

/* ---------- boot ---------- */
loadStatus();
show(location.hash.slice(1) || "leads");
