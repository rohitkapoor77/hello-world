"use strict";

const MAX_URLS = 25;
let lastResults = [];

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, html) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html != null) n.innerHTML = html;
  return n;
};
const esc = (s) =>
  String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function hostOf(u) {
  try { return new URL(u).host; } catch { return u; }
}
function pathOf(u) {
  try { const x = new URL(u); return x.pathname + x.search; } catch { return u; }
}
function bandClass(b) { return "b-" + b; }
function bandColor(b) {
  return b === "ready" ? "var(--green)" : b === "partial" ? "var(--amber)" : "var(--red)";
}

/* ----------------------------------------------------------------- input */
function parseUrls(text) {
  return text
    .split(/[\r\n,]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

function updateCounter() {
  const urls = parseUrls($("#urlInput").value);
  const n = urls.length;
  const counter = $("#counter");
  counter.textContent = `${n} / ${MAX_URLS} URLs`;
  counter.classList.toggle("over", n > MAX_URLS);
  const warn = $("#counterWarn");
  if (n > MAX_URLS) {
    warn.hidden = false;
    warn.textContent = `Only the first ${MAX_URLS} URLs will be audited (${n} entered).`;
  } else {
    warn.hidden = true;
  }
  $("#auditBtn").disabled = n === 0;
}

const SAMPLE = [
  "https://www.allbirds.com/products/mens-wool-runner-go",
  "https://www.gymshark.com/products/gymshark-arrival-t-shirt-black",
  "https://www.shopify.com/blog/how-agentic-commerce-works",
];

/* ----------------------------------------------------------------- audit */
async function runAudit() {
  let urls = parseUrls($("#urlInput").value);
  if (urls.length === 0) return;
  if (urls.length > MAX_URLS) urls = urls.slice(0, MAX_URLS);

  $("#emptyState").hidden = true;
  $("#results").hidden = true;
  $("#progressCard").hidden = false;
  $("#auditBtn").disabled = true;
  const bar = $("#progressBar");
  bar.style.width = "8%";
  $("#progressText").textContent = `Auditing ${urls.length} page${urls.length > 1 ? "s" : ""}…`;
  let pct = 8;
  const timer = setInterval(() => { pct = Math.min(90, pct + 4); bar.style.width = pct + "%"; }, 350);

  try {
    const resp = await fetch("/api/audit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ urls }),
    });
    const data = await resp.json();
    clearInterval(timer);
    bar.style.width = "100%";
    if (!resp.ok) throw new Error(data.error || "Audit failed.");
    lastResults = data.results || [];
    render(data);
  } catch (e) {
    clearInterval(timer);
    alert("Audit failed: " + e.message);
  } finally {
    setTimeout(() => { $("#progressCard").hidden = true; bar.style.width = "0"; }, 300);
    $("#auditBtn").disabled = false;
  }
}

/* ---------------------------------------------------------------- render */
function render(data) {
  renderDashboard(data.summary);
  renderTable(data.results);
  renderDetails(data.results);
  $("#results").hidden = false;
}

function renderDashboard(s) {
  const d = $("#dashboard");
  d.innerHTML = "";
  const cards = [
    { cls: "score", num: s.avg_score, lbl: "Avg score" },
    { cls: "", num: s.count, lbl: "Pages audited" },
    { cls: "ready", num: s.ready, lbl: "AI-Ready" },
    { cls: "partial", num: s.partial, lbl: "Partially ready" },
    { cls: "notready", num: s.not_ready, lbl: "Not ready" },
  ];
  cards.forEach((c) => {
    const m = el("div", "metric " + c.cls);
    m.appendChild(el("div", "num", esc(c.num)));
    m.appendChild(el("div", "lbl", esc(c.lbl)));
    d.appendChild(m);
  });
}

function renderTable(results) {
  const tb = $("#summaryTable").querySelector("tbody");
  tb.innerHTML = "";
  results.forEach((r, i) => {
    const tr = el("tr");
    const robots = r.robots || {};
    const robotsPct = robots.access_ratio != null ? Math.round(robots.access_ratio * 100) : "—";
    const gaps = (r.top_missing || []).slice(0, 2).join(", ") || "—";
    tr.innerHTML = `
      <td>${i + 1}</td>
      <td class="url-cell">
        <a href="${esc(r.final_url || r.url)}" target="_blank" rel="noopener">${esc(pathOf(r.url))}</a>
        <div class="url-host">${esc(hostOf(r.url))}</div>
      </td>
      <td><span class="score-pill ${bandClass(r.band)}">${esc(r.score)}</span></td>
      <td><span class="badge ${bandClass(r.band)}">${esc(r.band_label)}</span></td>
      <td>${robotsPct === "—" ? "—" : robotsPct + "%"}</td>
      <td class="gaps">${esc(gaps)}</td>
      <td class="fixcount">${(r.fixes || []).length}</td>
      <td><button class="linkbtn" data-view="${i}">View ▸</button></td>`;
    tb.appendChild(tr);
  });
  tb.querySelectorAll("[data-view]").forEach((b) =>
    b.addEventListener("click", () => openDetail(+b.dataset.view)));
}

function openDetail(i) {
  const card = document.getElementById("detail-" + i);
  if (!card) return;
  card.classList.add("open");
  card.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderDetails(results) {
  const wrap = $("#details");
  wrap.innerHTML = "";
  results.forEach((r, i) => wrap.appendChild(detailCard(r, i)));
}

function detailCard(r, i) {
  const card = el("div", "detail " + r.band);
  card.id = "detail-" + i;

  const robots = r.robots || {};
  const robotsPct = robots.access_ratio != null ? Math.round(robots.access_ratio * 100) : null;
  const sub = [
    r.band_label,
    r.http_status ? "HTTP " + r.http_status : (r.fetched_ok ? "" : "unreachable"),
    robotsPct != null ? `robots ${robotsPct}%` : "",
  ].filter(Boolean).join(" · ");

  const top = el("div", "detail-top");
  top.innerHTML = `
    <div class="detail-id">${i + 1}</div>
    <div class="ring" style="--p:${r.score};--ring-c:${bandColor(r.band)}"><span>${esc(r.score)}</span></div>
    <div class="detail-info">
      <div class="t">${esc(pathOf(r.url))}</div>
      <div class="s">${esc(hostOf(r.url))} — ${esc(sub)}</div>
    </div>
    <div class="detail-toggle">▾</div>`;
  top.addEventListener("click", () => card.classList.toggle("open"));
  card.appendChild(top);

  const body = el("div", "detail-body");

  if (!r.fetched_ok) {
    body.appendChild(el("div", "err-banner",
      "⚠ " + esc(r.error || "The page could not be fetched, so structured-data checks could not run.")));
  }

  // category bars
  body.appendChild(el("div", "section-title", "Category breakdown"));
  const cats = el("div", "cats");
  (r.categories || []).forEach((c) => {
    const cls = c.pct >= 85 ? "g" : c.pct >= 50 ? "a" : "r";
    const cat = el("div", "cat");
    cat.innerHTML = `
      <div class="cat-row"><span>${esc(c.label)}</span><span class="v">${c.earned}/${c.possible}</span></div>
      <div class="cat-bar"><i class="${cls}" style="width:${c.pct}%"></i></div>`;
    cats.appendChild(cat);
  });
  body.appendChild(cats);

  // prioritized fixes
  if ((r.fixes || []).length) {
    body.appendChild(el("div", "section-title", `Prioritised fixes (${r.fixes.length})`));
    const fixes = el("div", "fixes");
    r.fixes.forEach((f) => {
      const fx = el("div", "fix");
      fx.innerHTML = `
        <span class="prio ${esc(f.priority)}">${esc(f.priority)}</span>
        <div class="f-main">
          <div class="f-title">${esc(f.title)} <span class="f-pts">+${f.points} pts</span></div>
          <div class="f-detail">${esc(f.detail)}</div>
        </div>`;
      fixes.appendChild(fx);
    });
    body.appendChild(fixes);
  }

  // all checks
  if ((r.checks || []).length) {
    body.appendChild(el("div", "section-title", "All checks"));
    const checks = el("div", "checks");
    const icon = { pass: "✓", partial: "◐", fail: "✕", na: "–" };
    r.checks.forEach((c) => {
      const row = el("div", "check");
      const fixHtml = c.fix ? `<div class="c-fix"><b>Fix:</b> ${esc(c.fix)}</div>` : "";
      row.innerHTML = `
        <div class="ic ${c.status}">${icon[c.status] || "?"}</div>
        <div class="c-main">
          <div class="c-title"><span>${esc(c.label)}</span><span class="c-pts">${c.earned}/${c.possible}</span></div>
          <div class="c-ev">${esc(c.evidence)}</div>
          ${fixHtml}
        </div>`;
      checks.appendChild(row);
    });
    body.appendChild(checks);
  }

  // robots matrix
  if ((robots.bots || []).length) {
    body.appendChild(el("div", "section-title", "AI &amp; shopping crawler access (robots.txt)"));
    const bots = el("div", "bots");
    robots.bots.forEach((b) => {
      const bt = el("div", "bot");
      bt.innerHTML = `
        <span class="dot ${b.allowed ? "ok" : "no"}"></span>
        <span>${esc(b.label)}</span>
        <span class="bv">${esc(b.vendor)}</span>`;
      bt.title = (b.allowed ? "Allowed" : "Blocked") +
        (b.matched_rule ? " — " + b.matched_rule : "");
      bots.appendChild(bt);
    });
    body.appendChild(bots);
    if (robots.note) body.appendChild(el("p", "robots-note", esc(robots.note)));
  }

  card.appendChild(body);
  return card;
}

/* ---------------------------------------------------------------- export */
async function doExport(format, kind) {
  if (!lastResults.length) return;
  try {
    const resp = await fetch(`/api/export?format=${format}&kind=${kind}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ results: lastResults }),
    });
    if (!resp.ok) {
      const e = await resp.json().catch(() => ({}));
      throw new Error(e.error || "Export failed.");
    }
    const blob = await resp.blob();
    const cd = resp.headers.get("Content-Disposition") || "";
    const m = cd.match(/filename="([^"]+)"/);
    const name = m ? m[1] : (format === "xlsx" ? "audit.xlsx" : "audit.csv");
    const url = URL.createObjectURL(blob);
    const a = el("a");
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  } catch (e) {
    alert("Export failed: " + e.message);
  }
}

/* ------------------------------------------------------------------ wire */
function init() {
  fetch("/api/health").then((r) => r.json()).then((h) => {
    if (h.max_urls) {
      $("#maxUrls").textContent = h.max_urls;
    }
  }).catch(() => {});

  $("#urlInput").addEventListener("input", updateCounter);
  $("#auditBtn").addEventListener("click", runAudit);
  $("#clearBtn").addEventListener("click", () => {
    $("#urlInput").value = ""; updateCounter();
    $("#results").hidden = true; $("#emptyState").hidden = false;
  });
  $("#sampleBtn").addEventListener("click", () => {
    $("#urlInput").value = SAMPLE.join("\n"); updateCounter();
  });
  $("#fileInput").addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const urls = parseUrls(reader.result);
      const existing = parseUrls($("#urlInput").value);
      const merged = [...existing, ...urls];
      $("#urlInput").value = merged.join("\n");
      updateCounter();
    };
    reader.readAsText(file);
    e.target.value = "";
  });
  document.querySelectorAll("[data-export]").forEach((b) =>
    b.addEventListener("click", () => doExport(b.dataset.export, b.dataset.kind)));

  updateCounter();
}

document.addEventListener("DOMContentLoaded", init);
