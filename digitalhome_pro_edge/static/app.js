// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 D-LAB-5
//
// app.js — digitalhome.pro: a home's workspaces and the design in each.
// core.js wires the header (window.core: api, esc, toast, dialog); edge.js
// the chat and the connections. The design is changed mostly through the
// chat's confirmed proposals, so the page re-reads it every few seconds and
// redraws only when it changed.

"use strict";

const $ = (sel) => document.querySelector(sel);
const esc = (s) => core.esc(String(s ?? ""));
const LANG = (navigator.language || "en").slice(0, 2);

const S = { ws: null, item: null, tab: "design", seen: {} };

function hashState() {
  const h = new URLSearchParams(location.hash.slice(1));
  return { ws: h.get("w"), item: h.get("i") };
}

async function select(ws, item) {
  S.ws = ws; S.item = item || null;
  history.replaceState(null, "", ws ? `#w=${encodeURIComponent(ws)}${item ? `&i=${encodeURIComponent(item)}` : ""}` : "#");
  try { await core.api("POST", "/api/selection", { workspace: ws || "", item: item || "" }); } catch (_) { /* fine */ }
  $("#btn-labels").disabled = !ws;
  const ex = $("#btn-export");
  ex.hidden = !ws;
  if (ws) ex.href = `/api/workspaces/${encodeURIComponent(ws)}/export.ttl`;
  S.seen = {};
  refresh();
}

// ----------------------------------------------------------- the list ----

async function drawList() {
  const homes = await core.api("GET", "/api/homes");
  const key = JSON.stringify(homes) + S.ws;
  if (S.seen.list === key) return;
  S.seen.list = key;
  const box = $("#ws-list");
  if (!homes.length) {
    box.innerHTML = '<p class="note">No workspace yet. Start one below, or ask in the chat.</p>';
    return;
  }
  box.innerHTML = homes.map((h) => `<div class="home">${esc(h.home)}</div>` + h.workspaces.map((w) =>
    `<button data-ws="${esc(w.workspace)}" class="${w.workspace === S.ws ? "is-on" : ""}">
       <span>${esc(w.title)}</span><small>${esc(w.status)} · ${w.circuits}</small></button>`).join("")).join("");
  box.querySelectorAll("button[data-ws]").forEach((b) => b.onclick = () => select(b.dataset.ws));
}

// --------------------------------------------------------- the design ----

function circuitLine(c) {
  const what = [c.type.replace("_", " "), `${c.rated_current} A`, `${c.cross_section} mm²`,
                c.points ? `${c.points} pts` : "", c.appliance.replace("_", " ")].filter(Boolean).join(" · ");
  const ref = c.breakers.map((b) => b.reference).filter(Boolean).join(", ");
  return `<li data-item="${esc(c.id)}" class="${c.id === S.item ? "is-on" : ""}">
            <span>${esc(c.label)}</span><small>${esc(what)}${ref ? " · " + esc(ref) : ""}</small></li>`;
}

function boardBlock(b) {
  const cap = b.rows * b.modules_per_row;
  const pct = Math.min(100, Math.round(100 * b.modules_used / cap));
  const cls = b.modules_used > cap ? "full" : (cap - b.modules_used) / cap < 0.2 ? "tight" : "";
  return `<article class="board">
    <header><b>${esc(b.label)}</b><small>${b.rows} × ${b.modules_per_row} modules · ${b.modules_used} used</small></header>
    <div class="meter ${cls}"><i style="width:${pct}%"></i></div>
    ${b.rcds.map((r) => `<div class="rcd"><b>${esc(r.label)}</b>
        <small> ${r.rated_current} A · ${r.sensitivity_ma} mA · type ${esc(r.rcd_type)} · ${r.circuits.length} circuits</small>
        <ul class="circuits">${r.circuits.map(circuitLine).join("")}</ul></div>`).join("")}
    ${b.devices.length ? `<ul class="devices">${b.devices.map((d) =>
      `<li data-item="${esc(d.id)}"><span>${esc(d.label)}</span><small>${esc(d.kind.replace("_", " "))}${
        d.rated_current != null ? " · " + d.rated_current + " A" : ""} · ${d.modules} mod.</small></li>`).join("")}</ul>` : ""}
  </article>`;
}

async function drawDesign() {
  const d = await core.api("GET", `/api/workspaces/${encodeURIComponent(S.ws)}`);
  const key = JSON.stringify(d) + S.item;
  if (S.seen.design === key) return;
  S.seen.design = key;
  const box = $("#tab-design");
  box.innerHTML = `<h2>${esc(d.title)}</h2>
    <p class="sub">${esc(d.home)} · ${esc(d.country)} · ${esc(d.status)}</p>
    ${d.boards.length ? d.boards.map(boardBlock).join("")
      : '<p class="note">No board yet. Ask in the chat, e.g. “a board of 2 rows of 13 modules with two type A RCDs”.</p>'}
    ${d.rooms.length ? `<h3>Rooms</h3><div class="rooms">${d.rooms.map((r) =>
      `<span>${esc(r.label)}${r.items.length ? " · " + r.items.length : ""}</span>`).join("")}</div>` : ""}`;
  box.querySelectorAll("li[data-item]").forEach((li) => li.onclick = () => select(S.ws, li.dataset.item));
}

async function drawReport() {
  const r = await core.api("GET", `/api/workspaces/${encodeURIComponent(S.ws)}/report?lang=${LANG}`);
  const key = JSON.stringify(r);
  if (S.seen.report === key) return;
  S.seen.report = key;
  $("#tab-report").innerHTML = !r.findings.length
    ? '<p class="ok">Nothing to report: the design meets every rule this edge checks.</p>'
    : r.findings.map((f) => `<div class="finding ${esc(f.severity)}"><b>${esc(f.label || "Whole design")}</b>${esc(f.message)}</div>`).join("");
}

async function drawBom() {
  const b = await core.api("GET", `/api/workspaces/${encodeURIComponent(S.ws)}/bom`);
  const key = JSON.stringify(b);
  if (S.seen.bom === key) return;
  S.seen.bom = key;
  $("#tab-bom").innerHTML = `<table class="bom"><thead><tr><th>Item</th><th class="num">Qty</th>
      <th>Reference</th><th class="num">Unit</th><th class="num">Total</th></tr></thead><tbody>
    ${b.lines.map((l) => `<tr><td>${esc(l.description)}${l.modules_each ? ` <small>(${l.modules_each} mod.)</small>` : ""}</td>
      <td class="num">${l.quantity}</td>
      <td>${l.reference ? esc(l.partner + " " + l.reference) : ""}${l.missing ? `<div class="missing">${esc(l.missing)}</div>` : ""}</td>
      <td class="num">${l.unit_price ? esc(l.unit_price) : ""}</td><td class="num">${l.total ? esc(l.total) : ""}</td></tr>`).join("")}
    </tbody><tfoot><tr><th colspan="4">Priced total${b.complete ? "" : " (incomplete)"}</th>
      <th class="num">${esc(b.total)}</th></tr></tfoot></table>
    <p class="note">Prices come from each partner's API or imported file (Partners tab) and stay on this computer.</p>`;
}

// ---------------------------------------------------------- partners ----

async function drawPartners() {
  const list = await core.api("GET", "/api/partners");
  const key = JSON.stringify(list);
  if (S.seen.partners === key) return;
  S.seen.partners = key;
  $("#tab-partners").innerHTML = `<p class="sub">Product data and prices come from each partner's API when
      this edge has access to it, otherwise from a data exchange file you import. Both stay on this computer.</p>` +
    list.map((p) => `<section class="partner" data-p="${esc(p.partner)}">
      <header><b>${esc(p.name)}</b><span class="use">${esc(p.use)}</span></header>
      ${p.note ? `<p class="note">${esc(p.note)}</p>` : ""}
      ${p.file ? `<p class="note">File: ${esc(p.file.name || p.file.format)} · ${p.file.articles} articles</p>` : ""}
      <form class="imp"><input type="file" name="file" required>
        <select name="format">${p.formats.map((f) => `<option>${esc(f)}</option>`).join("")}</select>
        <button>Import</button></form>
      ${p.api_possible ? `<form class="cred">
        <input type="text" name="client_id" placeholder="client id" autocomplete="off">
        <input type="password" name="client_secret" placeholder="client secret" autocomplete="off">
        <input type="text" name="supplier_id" placeholder="supplier id">
        <input type="text" name="customer_id" placeholder="customer id">
        <button>${p.api_configured ? "Replace" : "Use the API"}</button>
        ${p.api_configured ? '<button type="button" class="forget danger">Forget</button>' : ""}</form>` : ""}
    </section>`).join("");
  document.querySelectorAll(".partner").forEach((sec) => {
    const p = sec.dataset.p;
    sec.querySelector("form.imp").onsubmit = async (e) => {
      e.preventDefault();
      const res = await fetch(`/api/partners/${encodeURIComponent(p)}/import`, { method: "POST", body: new FormData(e.target) });
      const got = await res.json().catch(() => ({}));
      core.toast(res.ok ? `${got.articles} articles imported, ${got.priced} with a price` : (got.errors || ["failed"]).join("; "));
      S.seen.partners = null; drawPartners();
    };
    const cred = sec.querySelector("form.cred");
    if (cred) {
      cred.onsubmit = async (e) => {
        e.preventDefault();
        try {
          await core.api("POST", `/api/partners/${encodeURIComponent(p)}/credentials`, Object.fromEntries(new FormData(cred)));
          core.toast("Saved on this computer");
        } catch (err) { core.toast(err.errors.join("; ")); }
        S.seen.partners = null; drawPartners();
      };
      const f = cred.querySelector(".forget");
      if (f) f.onclick = async () => {
        await core.api("DELETE", `/api/partners/${encodeURIComponent(p)}/credentials`);
        S.seen.partners = null; drawPartners();
      };
    }
  });
}

// ------------------------------------------------------------- wiring ----

async function refresh() {
  try {
    await drawList();
    if (S.tab === "partners") return drawPartners();
    if (!S.ws) return;
    if (S.tab === "design") await drawDesign();
    if (S.tab === "report") await drawReport();
    if (S.tab === "bom") await drawBom();
  } catch (err) {
    if (err && err.status === 404 && S.ws) select(null);
  }
}

function wire() {
  document.querySelectorAll(".tabs button").forEach((b) => b.onclick = () => {
    S.tab = b.dataset.tab;
    document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("is-on", x === b));
    document.querySelectorAll(".tab").forEach((t) => t.hidden = t.id !== `tab-${S.tab}`);
    S.seen = {};
    refresh();
  });
  $("#nw-make").onclick = async () => {
    try {
      const got = await core.api("POST", "/api/workspaces", {
        title: $("#nw-title").value, home: $("#nw-home").value, country: $("#nw-country").value });
      $("#nw-title").value = "";
      select(got.workspace);
    } catch (err) { core.toast(err.errors.join("; ")); }
  };
  $("#btn-labels").onclick = () => S.ws && window.open(`/workspaces/${encodeURIComponent(S.ws)}/labels`, "_blank");
  const h = hashState();
  select(h.ws, h.item);
  setInterval(() => { if (!document.hidden) refresh(); }, 4000);
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wire);
else wire();
