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
const t = (key, vars) => window.i18n.t(key, vars);
const status = (v) => t(`status.${v}`) === `status.${v}` ? v : t(`status.${v}`);
const kind = (v) => t(`kind.${v}`) === `kind.${v}` ? v : t(`kind.${v}`);
const when = (iso) => { try { return new Date(iso).toLocaleString(window.i18n.lang); } catch (_) { return iso || ""; } };
const failed = (err) => (err && err.errors) ? err.errors.join("; ") : t("failed");

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

// A home of the linked cloud as a link to it in the Portal (the Portal opens a home with ?home=);
// a draft or a home of another cloud stays plain text.
function homeLink(id) {
  const c = S.cloud;
  if (!c || !c.site || !c.homes.some((h) => h.smartHomeId === id)) return esc(id);
  const label = (c.homes.find((h) => h.smartHomeId === id) || {}).label;
  return `<a href="${esc(c.site.replace(/\/$/, ""))}/?home=${encodeURIComponent(id)}" target="_blank" rel="noopener noreferrer"
            title="${esc(t("list.openPortal", { name: label || id }))}">${esc(id)} ↗</a>`;
}

async function drawList() {
  const homes = await core.api("GET", "/api/homes");
  const open = homes.flatMap((h) => h.workspaces).find((w) => w.workspace === S.ws);
  S.wsTitle = open ? open.title : "";
  const key = JSON.stringify(homes) + S.ws + JSON.stringify(S.cloud || null);
  if (S.seen.list === key) return;
  S.seen.list = key;
  const box = $("#ws-list");
  if (!homes.length) {
    box.innerHTML = `<p class="note">${esc(t("list.none"))}</p>`;
    return;
  }
  box.innerHTML = homes.map((h) => `<div class="home">${homeLink(h.home)}</div>` + h.workspaces.map((w) =>
    `<button data-ws="${esc(w.workspace)}" class="${w.workspace === S.ws ? "is-on" : ""}">
       <span>${esc(w.title)}</span><small>${esc(status(w.status))} · ${w.circuits}</small></button>`).join("")).join("");
  box.querySelectorAll("button[data-ws]").forEach((b) => b.onclick = () => select(b.dataset.ws));
}

// The homes a new workspace may name: the person's homes on digitalhome.cloud.
// Not linked yet: a draft for a local name, said so.
async function drawHomeChoice() {
  let got;
  try { got = await core.api("GET", "/api/cloud-homes"); } catch (_) { return; }
  const key = JSON.stringify(got);
  if (S.seen.homes === key) return;
  S.seen.homes = key;
  S.cloud = got.linked ? { site: got.site, homes: got.homes } : null;
  S.seen.list = S.seen.design = null;           // redraw the home links
  const sel = $("#nw-home"), why = $("#nw-home-why");
  const draft = !got.linked || got.unavailable;
  sel.innerHTML = got.homes.map((h) =>
    `<option value="${esc(h.smartHomeId)}">${esc(h.label)}${h.isDemo ? " " + esc(t("home.demo")) : ""}</option>`).join("")
    + (draft ? `<option value="__draft">${esc(t("home.draft"))}</option>` : "");
  why.hidden = false;
  why.textContent = (got.linked ? t("home.onConnection", { name: got.connection }) : "")
    + (got.why || (got.homes.length ? "" : t("home.noneYet")));
  $("#nw-make").disabled = !got.homes.length && !draft;
  $("#nw-draft").hidden = sel.value !== "__draft";
}

// --------------------------------------------------------- the design ----

function circuitLine(c) {
  const what = [c.type.replace("_", " "), `${c.rated_current} A`, `${c.cross_section} mm²`,
                c.points ? t("circuit.pts", { n: c.points }) : "", c.appliance.replace("_", " ")].filter(Boolean).join(" · ");
  const ref = c.breakers.map((b) => b.reference).filter(Boolean).join(", ");
  return `<li data-item="${esc(c.id)}" class="${c.id === S.item ? "is-on" : ""}">
            <span>${esc(c.label)}</span><small>${esc(what)}${ref ? " · " + esc(ref) : ""}</small></li>`;
}

function boardBlock(b) {
  const cap = b.rows * b.modules_per_row;
  const pct = Math.min(100, Math.round(100 * b.modules_used / cap));
  const cls = b.modules_used > cap ? "full" : (cap - b.modules_used) / cap < 0.2 ? "tight" : "";
  return `<article class="board">
    <header><b>${esc(b.label)}</b><small>${esc(t("board.modules", { rows: b.rows, per: b.modules_per_row, used: b.modules_used }))}</small></header>
    <div class="meter ${cls}"><i style="width:${pct}%"></i></div>
    ${b.rcds.map((r) => `<div class="rcd"><b>${esc(r.label)}</b>
        <small> ${esc(t("board.rcd", { a: r.rated_current, ma: r.sensitivity_ma, type: r.rcd_type, n: r.circuits.length }))}</small>
        <ul class="circuits">${r.circuits.map(circuitLine).join("")}</ul></div>`).join("")}
    ${b.devices.length ? `<ul class="devices">${b.devices.map((d) =>
      `<li data-item="${esc(d.id)}"><span>${esc(d.label)}</span><small>${esc(d.kind.replace("_", " "))}${
        d.rated_current != null ? " · " + d.rated_current + " A" : ""} · ${esc(t("board.mod", { n: d.modules }))}</small></li>`).join("")}</ul>` : ""}
  </article>`;
}

async function drawDesign() {
  const d = await core.api("GET", `/api/workspaces/${encodeURIComponent(S.ws)}`);
  const key = JSON.stringify(d) + S.item + JSON.stringify(S.cloud || null);
  if (S.seen.design === key) return;
  S.seen.design = key;
  const box = $("#tab-design");
  box.innerHTML = `<div class="ws-head"><h2>${esc(d.title)}</h2>
      <button type="button" class="ws-rename" title="${esc(t("design.renameTitle", { id: S.ws }))}">${esc(t("design.rename"))}</button></div>
    <p class="sub">${homeLink(d.home)} · ${esc(d.country)} · ${esc(status(d.status))}</p>
    ${d.boards.length ? d.boards.map(boardBlock).join("")
      : `<p class="note">${esc(t("design.noBoard"))}</p>`}
    ${d.rooms.length ? `<h3>${esc(t("design.rooms"))}</h3><div class="rooms">${d.rooms.map((r) =>
      `<span>${esc(r.label)}${r.items.length ? " · " + r.items.length : ""}</span>`).join("")}</div>` : ""}`;
  box.querySelectorAll("li[data-item]").forEach((li) => li.onclick = () => select(S.ws, li.dataset.item));
  box.querySelector(".ws-rename").onclick = () => renameForm(box.querySelector(".ws-head"), d.title);
}

// The workspace's display name. Only the title changes: the id, and with it
// the folder mydocs/<id>/, stay as they are (ADR-0007).
function renameForm(head, title) {
  const form = document.createElement("form");
  form.className = "ws-head ws-rename-form";
  form.innerHTML = `<input name="title" required maxlength="120" value="${esc(title)}">
    <button class="primary">${esc(t("design.save"))}</button>
    <button type="button" class="cancel">${esc(t("design.cancel"))}</button>`;
  const ws = S.ws;
  const back = () => { S.seen.design = null; refresh(); };
  form.onsubmit = async (e) => {
    e.preventDefault();
    const value = form.title.value.trim();
    if (!value || value === title) return back();
    try {
      await core.api("POST", `/api/workspaces/${encodeURIComponent(ws)}`, { title: value });
      core.toast(t("design.renamed"));
    } catch (err) { core.toast(failed(err)); }
    S.seen.list = null;
    back();
  };
  form.querySelector(".cancel").onclick = back;
  form.title.onkeydown = (e) => { if (e.key === "Escape") back(); };
  head.replaceWith(form);
  form.title.focus();
  form.title.select();
}

async function drawReport() {
  const r = await core.api("GET", `/api/workspaces/${encodeURIComponent(S.ws)}/report?lang=${window.i18n.lang}`);
  const key = JSON.stringify(r);
  if (S.seen.report === key) return;
  S.seen.report = key;
  $("#tab-report").innerHTML = !r.findings.length
    ? `<p class="ok">${esc(t("report.ok"))}</p>`
    : r.findings.map((f) => `<div class="finding ${esc(f.severity)}"><b>${esc(f.label || t("report.whole"))}</b>${esc(f.message)}</div>`).join("");
}

async function drawBom() {
  const b = await core.api("GET", `/api/workspaces/${encodeURIComponent(S.ws)}/bom`);
  const key = JSON.stringify(b);
  if (S.seen.bom === key) return;
  S.seen.bom = key;
  $("#tab-bom").innerHTML = `<table class="bom"><thead><tr><th>${esc(t("bom.item"))}</th><th class="num">${esc(t("bom.qty"))}</th>
      <th>${esc(t("bom.reference"))}</th><th class="num">${esc(t("bom.unit"))}</th><th class="num">${esc(t("bom.total"))}</th></tr></thead><tbody>
    ${b.lines.map((l) => `<tr><td>${esc(l.description)}${l.modules_each ? ` <small>(${esc(t("board.mod", { n: l.modules_each }))})</small>` : ""}</td>
      <td class="num">${l.quantity}</td>
      <td>${l.reference ? esc(l.partner + " " + l.reference) : ""}${l.missing ? `<div class="missing">${esc(l.missing)}</div>` : ""}</td>
      <td class="num">${l.unit_price ? esc(l.unit_price) : ""}</td><td class="num">${l.total ? esc(l.total) : ""}</td></tr>`).join("")}
    </tbody><tfoot><tr><th colspan="4">${esc(t("bom.priced"))}${b.complete ? "" : esc(t("bom.incomplete"))}</th>
      <th class="num">${esc(b.total)}</th></tr></tfoot></table>
    <p class="note">${esc(t("bom.note"))}</p>`;
}

// ---------------------------------------------------------- partners ----

async function drawPartners() {
  const got = await core.api("GET", "/api/partners");
  const key = JSON.stringify(got);
  if (S.seen.partners === key) return;
  S.seen.partners = key;
  const again = () => { S.seen.partners = null; drawPartners(); };
  const fail = (err) => core.toast(failed(err));
  const st = got.store;
  $("#tab-partners").innerHTML = `
    <p class="sub">${esc(t("p.intro"))}</p>
    <form class="store">${esc(t("p.keep"))}
      <select name="where"><option value="local" ${st.where === "local" ? "selected" : ""}>${esc(t("p.local"))}</option>
        <option value="cloud" ${st.where === "cloud" ? "selected" : ""}>${esc(t("p.cloud"))}</option></select>
      <button>${esc(t("p.move"))}</button></form>` +
    got.partners.map((p) => `<section class="partner" data-p="${esc(p.partner)}">
      <header><b>${esc(p.name)}</b> <small>${esc(kind(p.kind))}</small><span class="use">${esc(p.use)}</span></header>
      ${p.note ? `<p class="note">${esc(p.note)}</p>` : ""}
      ${p.file ? `<p class="note">${esc(t("p.file", { name: p.file.name || p.file.format, n: p.file.articles }))}</p>` : ""}
      <form class="imp"><input type="file" name="file" required>
        <select name="format">${p.formats.map((f) => `<option>${esc(f)}</option>`).join("")}</select>
        <button>${esc(t("p.import"))}</button></form>
      ${p.api ? `<form class="cred">
        <input type="text" name="client_id" placeholder="${esc(t("p.clientId"))}" autocomplete="off">
        <input type="password" name="client_secret" placeholder="${esc(t("p.clientSecret"))}" autocomplete="off">
        <input type="text" name="supplier_id" placeholder="${esc(t("p.supplierId"))}">
        <input type="text" name="customer_id" placeholder="${esc(t("p.customerId"))}">
        <button>${esc(p.api_configured ? t("p.replace") : t("p.useApi"))}</button>
        ${p.api_configured ? `<button type="button" class="forget">${esc(t("p.forget"))}</button>` : ""}</form>` : ""}
      ${p.market ? `<form class="attach"><input type="text" name="reference" placeholder="${esc(t("p.refPh"))}" required>
        <input type="file" name="file" accept=".jpg,.jpeg,.png,.webp,.pdf" required>
        <button>${esc(t("p.attach"))}</button></form>` : ""}
      <button type="button" class="drop danger">${esc(t("p.remove"))}</button>
    </section>`).join("") + `
    <details class="partner"><summary>${esc(t("p.add"))}</summary>
      <form class="add">
        <input type="text" name="id" placeholder="${esc(t("p.idPh"))}" required pattern="[a-z][a-z0-9-]{0,39}">
        <input type="text" name="name" placeholder="${esc(t("p.namePh"))}" required>
        <select name="kind">${["distributor", "manufacturer", "wholesaler"].map((k) =>
          `<option value="${k}">${esc(kind(k))}</option>`).join("")}</select>
        ${got.formats.map((f) => `<label><input type="checkbox" name="formats" value="${esc(f)}" ${f === "csv" ? "checked" : ""}> ${esc(f)}</label>`).join("")}
        <select name="api"><option value="">${esc(t("p.noApi"))}</option>${got.connectors.map((c) => `<option>${esc(c)}</option>`).join("")}</select>
        <button class="primary">${esc(t("p.addBtn"))}</button></form></details>
    <details class="partner market" ${S.marketOpen ? "open" : ""}><summary>${esc(t("m.title"))}</summary><div class="mk"></div></details>`;
  const box = $("#tab-partners");
  const mkt = box.querySelector("details.market");
  if (mkt.open) drawMarket(mkt.querySelector(".mk"));
  mkt.ontoggle = () => { S.marketOpen = mkt.open; if (mkt.open) drawMarket(mkt.querySelector(".mk")); };
  box.querySelector("form.store").onsubmit = async (e) => {
    e.preventDefault();
    try { await core.api("POST", "/api/partners/store", { where: e.target.where.value }); core.toast(t("p.moved")); }
    catch (err) { fail(err); }
    again();
  };
  box.querySelector("form.add").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      await core.api("POST", "/api/partners", { id: f.get("id"), name: f.get("name"), kind: f.get("kind"),
                                               formats: f.getAll("formats"), api: f.get("api") });
    } catch (err) { fail(err); }
    again();
  };
  box.querySelectorAll("section.partner").forEach((sec) => {
    const p = sec.dataset.p;
    sec.querySelector("form.imp").onsubmit = async (e) => {
      e.preventDefault();
      const res = await fetch(`/api/partners/${encodeURIComponent(p)}/import`, { method: "POST", body: new FormData(e.target) });
      const r = await res.json().catch(() => ({}));
      core.toast(res.ok ? t("p.imported", { n: r.articles, p: r.priced }) : failed(r));
      again();
    };
    const att = sec.querySelector("form.attach");
    if (att) att.onsubmit = async (e) => {
      e.preventDefault();
      const res = await fetch(`/api/partners/${encodeURIComponent(p)}/articles/file`, { method: "POST", body: new FormData(att) });
      const r = await res.json().catch(() => ({}));
      core.toast(res.ok ? t("p.attached") : failed(r));
      again();
    };
    sec.querySelector(".drop").onclick = async () => {
      try { await core.api("DELETE", `/api/partners/${encodeURIComponent(p)}`); } catch (err) { fail(err); }
      again();
    };
    const cred = sec.querySelector("form.cred");
    if (cred) {
      cred.onsubmit = async (e) => {
        e.preventDefault();
        try {
          const r = await core.api("POST", `/api/partners/${encodeURIComponent(p)}/credentials`, Object.fromEntries(new FormData(cred)));
          core.toast(r.where === "cloud" ? t("p.savedCloud") : t("p.savedLocal"));
        } catch (err) { fail(err); }
        again();
      };
      const f = cred.querySelector(".forget");
      if (f) f.onclick = async () => {
        await core.api("DELETE", `/api/partners/${encodeURIComponent(p)}/credentials`);
        again();
      };
    }
  });
}

// ------------------------------------------------------ marketplace ----
//
// The digitalhome.cloud marketplace (ADR-0006): sellers' catalogues as graphs.
// Subscribing makes a seller a partner with the same id; Sync merges both
// sides, and asks "mine or theirs" when one fact has two values.

function conflictForm(box, partner, got, again) {
  const form = document.createElement("form");
  form.className = "mk-conflicts";
  form.innerHTML = `<p class="note">${esc(t("m.conflict", { p: partner }))}</p>` +
    got.conflicts.map((c, i) => `<fieldset><legend>${esc(c.subject.split("/").pop())} · ${esc(c.property.split("#").pop())}</legend>
      <label><input type="radio" name="c${i}" value="mine" required> ${esc(t("m.here", { v: c.mine.join(", ") }))}</label>
      <label><input type="radio" name="c${i}" value="theirs"> ${esc(t("m.there", { v: c.theirs.join(", ") }))}</label></fieldset>`).join("") +
    `<button class="primary">${esc(t("m.resolve"))}</button>`;
  form.onsubmit = async (e) => {
    e.preventDefault();
    const resolve = {};
    got.conflicts.forEach((c, i) => { resolve[c.key] = form.elements[`c${i}`].value; });
    await syncPartner(box, partner, resolve, again);
  };
  box.querySelector(".mk-out").replaceChildren(form);
}

async function syncPartner(box, partner, resolve, again) {
  try {
    const r = await core.api("POST", "/api/market/sync", { partner, resolve });
    if (r.status === "conflict") return conflictForm(box, partner, r, again);
    if (r.status === "invalid") {
      box.querySelector(".mk-out").innerHTML = `<p class="note">${esc(t("m.refused", { p: partner }))}</p>
        <ul>${r.problems.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
      return;
    }
    core.toast(t("m.result", { p: partner, in: r.pulled, out: r.pushed }) + (r.local_only ? t("m.keptHere", { n: r.local_only }) : ""));
  } catch (err) { core.toast(failed(err)); }
  again();
}

async function drawMarket(box) {
  let got;
  try { got = await core.api("GET", "/api/market"); }
  catch (err) { box.innerHTML = `<p class="note">${esc(err && err.errors ? err.errors.join("; ") : t("unavailable"))}</p>`; return; }
  const again = () => { S.seen.partners = null; drawPartners(); };
  box.innerHTML = `<p class="note">${esc(t("m.intro"))}</p>
    <table class="bom"><thead><tr><th>${esc(t("m.seller"))}</th><th class="num">${esc(t("m.articles"))}</th><th>${esc(t("m.synced"))}</th><th></th></tr></thead><tbody>
    ${got.sellers.map((s) => `<tr data-s="${esc(s.id)}">
      <td><b>${esc(s.name)}</b> <small>${esc(s.id)} · ${esc(kind(s.kind))}${s.mayEdit ? esc(t("m.youEdit")) : ""}</small></td>
      <td class="num">${s.articles}</td>
      <td>${s.synced ? `v${s.synced.version} · ${esc(when(s.synced.synced_at))}${s.synced.local_only ? esc(t("m.hereOnly", { n: s.synced.local_only })) : ""}` : ""}</td>
      <td>${s.subscribed ? `<button type="button" class="sync">${esc(t("m.sync"))}</button>` : `<button type="button" class="sub">${esc(t("m.subscribe"))}</button>`}</td>
    </tr>`).join("") || `<tr><td colspan="4">${esc(t("m.none"))}</td></tr>`}
    </tbody></table><div class="mk-out"></div>`;
  box.querySelectorAll("tr[data-s]").forEach((tr) => {
    const id = tr.dataset.s;
    const sub = tr.querySelector(".sub");
    if (sub) sub.onclick = async () => {
      try { await core.api("POST", "/api/market/subscribe", { seller: id }); core.toast(t("m.subscribed", { id })); }
      catch (err) { core.toast(failed(err)); }
      again();
    };
    const sync = tr.querySelector(".sync");
    if (sync) sync.onclick = () => syncPartner(box, id, null, again);
  });
}

// --------------------------------------------------------------- files ----
//
// Files given to the chat. Dropping one makes it the chat's selection; the
// chat reads it and proposes what to do with it (inbox.py).

// Into the inbox; the server makes it the chat's selection. Returns its meta, or null.
async function addFile(file) {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch("/api/inbox", { method: "POST", body: fd }).catch(() => null);
  const r = res ? await res.json().catch(() => ({})) : {};
  S.seen.files = null;
  if (!res || !res.ok) { core.toast(`${file.name}: ${(r.errors || [t("f.notAdded")]).join("; ")}`); return null; }
  return r;
}

async function upload(file) {
  const r = await addFile(file);
  if (r) core.toast(t("f.added", { name: r.name, note: r.note }));
  refresh();
}

// The same, from the chat: 📎 beside Ask, or a file dropped on the chat. The
// message is started for the person ("I added …: "), who says what it is for.
// The chat panel belongs to the edge layer (edge.js) and is redrawn, so the
// button is put back whenever its form is new.
async function attachToChat(files) {
  const box = $("#edge-chat");
  const form = box && box.querySelector(".edge-chat__ask");
  const input = form && form.querySelector("textarea");
  const btn = form && form.querySelector(".chat-attach");
  if (!input || !files.length) return;
  if (btn) { btn.disabled = true; btn.textContent = "…"; }
  const added = [];
  for (const f of files) { const r = await addFile(f); if (r) added.push(r); }
  if (btn) { btn.disabled = false; btn.textContent = "📎"; }
  if (!added.length) return;
  const line = added.length === 1
    ? t("f.addedOne", { name: added[0].name, id: added[0].id, kind: added[0].kind })
    : t("f.addedMany", { list: added.map((r) => t("f.listItem", { name: r.name, id: r.id })).join(", ") });
  input.value = input.value.trim() ? `${input.value.trim()}\n${line}` : line;
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
  if (S.tab === "files") refresh();
}

function wireChatAttach() {
  const box = $("#edge-chat");
  if (!box) return;
  const hook = () => {
    const form = box.querySelector(".edge-chat__ask");
    if (!form || form.querySelector(".chat-attach")) return;
    const pick = document.createElement("input");
    pick.type = "file"; pick.multiple = true; pick.hidden = true;
    pick.onchange = () => { attachToChat([...pick.files]); pick.value = ""; };
    const btn = document.createElement("button");
    btn.type = "button"; btn.className = "chat-attach"; btn.textContent = "📎";
    btn.setAttribute("aria-label", t("f.attachLabel"));
    btn.dataset.help = t("f.attachHelp");
    btn.onclick = () => pick.click();
    const ask = form.querySelector('button[type="submit"]');
    form.insertBefore(btn, ask || null);
    form.append(pick);
  };
  hook();
  new MutationObserver(hook).observe(box, { childList: true, subtree: true });
  let depth = 0;   // dragenter/leave fire for every child: count them
  const has = (e) => e.dataTransfer && [...(e.dataTransfer.types || [])].includes("Files");
  box.addEventListener("dragenter", (e) => { if (!has(e)) return; e.preventDefault(); depth++; box.classList.add("chat-drop"); });
  box.addEventListener("dragover", (e) => { if (has(e)) e.preventDefault(); });
  box.addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; box.classList.remove("chat-drop"); } });
  box.addEventListener("drop", (e) => {
    if (!has(e)) return;
    e.preventDefault(); depth = 0; box.classList.remove("chat-drop");
    attachToChat([...e.dataTransfer.files]);
  });
}

async function drawFiles() {
  const got = await core.api("GET", "/api/inbox");
  const key = JSON.stringify(got);
  if (S.seen.files === key) return;
  S.seen.files = key;
  const box = $("#tab-files");
  box.innerHTML = `
    <p class="sub">${esc(t("f.intro"))}${S.wsTitle ? " " + esc(t("f.inWorkspace", { name: S.wsTitle })) : ""}</p>
    <label class="dropzone"><input type="file" multiple hidden>
      <span>${esc(t("f.drop"))}</span></label>
    ${got.length ? `<table class="files"><thead><tr><th>${esc(t("f.file"))}</th><th>${esc(t("f.what"))}</th><th>${esc(t("f.where"))}</th><th class="num">${esc(t("f.size"))}</th><th></th></tr></thead><tbody>
      ${got.map((f) => `<tr data-f="${esc(f.id)}"><td>${esc(f.name)}</td><td><b>${esc(f.kind)}</b> · ${esc(f.note)}</td>
        <td>${f.workspace ? `<code>${esc(f.workspace)}/files</code>` : esc(t("f.shared"))}</td>
        <td class="num">${f.size < 1024 ? `${f.size} B` : `${new Intl.NumberFormat(window.i18n.lang).format(Math.round(f.size / 1024))} kB`}</td>
        <td><button class="ask">${esc(t("f.give"))}</button> <button class="drop">${esc(t("f.remove"))}</button></td></tr>`).join("")}
      </tbody></table>` : `<p class="note">${esc(t("f.none"))}</p>`}`;
  const zone = box.querySelector(".dropzone");
  const input = zone.querySelector("input");
  input.onchange = () => [...input.files].forEach(upload);
  zone.ondragover = (e) => { e.preventDefault(); zone.classList.add("over"); };
  zone.ondragleave = () => zone.classList.remove("over");
  zone.ondrop = (e) => { e.preventDefault(); zone.classList.remove("over"); [...e.dataTransfer.files].forEach(upload); };
  box.querySelectorAll("tr[data-f]").forEach((tr) => {
    const f = tr.dataset.f;
    tr.querySelector(".ask").onclick = async () => {
      await core.api("POST", "/api/selection", { workspace: S.ws || "", item: S.item || "", file: f });
      core.toast(t("f.inView"));
    };
    tr.querySelector(".drop").onclick = async () => {
      try { await core.api("DELETE", `/api/inbox/${encodeURIComponent(f)}`); } catch (err) { core.toast(failed(err)); }
      S.seen.files = null; refresh();
    };
  });
}

// ------------------------------------------------------------- wiring ----

async function refresh() {
  try {
    await drawList();
    drawHomeChoice();
    if (S.tab === "partners") return drawPartners();
    if (S.tab === "files") return drawFiles();
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
  $("#nw-home").onchange = () => { $("#nw-draft").hidden = $("#nw-home").value !== "__draft"; };
  $("#nw-make").onclick = async () => {
    try {
      const home = $("#nw-home").value === "__draft" ? $("#nw-draft").value.trim() : $("#nw-home").value;
      const got = await core.api("POST", "/api/workspaces", {
        title: $("#nw-title").value, home, country: $("#nw-country").value });
      $("#nw-title").value = "";
      select(got.workspace);
    } catch (err) { core.toast(failed(err)); }
  };
  $("#btn-labels").onclick = () => S.ws && window.open(`/workspaces/${encodeURIComponent(S.ws)}/labels`, "_blank");
  wireChatAttach();
  // a language switch redraws what this page drew; i18n.js does the rest
  window.i18n.onChange(() => { S.seen = {}; drawHomeChoice(); refresh(); });
  const h = hashState();
  select(h.ws, h.item);
  setInterval(() => { if (!document.hidden) refresh(); }, 4000);
}

// the strings first (i18n.json), then the page
const start = () => window.i18n.ready.then(wire);
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
else start();
