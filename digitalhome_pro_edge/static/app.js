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

// A loading indicator in the middle of the screen, for what the person
// started (a tab, a workspace, a wizard step, a preview); never for the
// background poll. It shows only when the wait is long enough to notice.
let busyN = 0, busyT = null;
function busyOn() {
  if (busyN++ === 0) busyT = setTimeout(() => { $("#busy").hidden = false; }, 150);
}
function busyOff() {
  if (busyN > 0 && --busyN === 0) { clearTimeout(busyT); $("#busy").hidden = true; }
}
async function busy(work) {
  busyOn();
  try { return await (typeof work === "function" ? work() : work); } finally { busyOff(); }
}

function hashState() {
  const h = new URLSearchParams(location.hash.slice(1));
  return { ws: h.get("w"), item: h.get("i") };
}

async function select(ws, item) {
  if (ws !== S.ws) Object.assign(S, { cmp: null, cmpFrom: null, cmpTo: null, tagging: "", restoring: "",
                                      conf: null, confSure: "", vaultPlan: null });
  S.ws = ws; S.item = item || null;
  history.replaceState(null, "", ws ? `#w=${encodeURIComponent(ws)}${item ? `&i=${encodeURIComponent(item)}` : ""}` : "#");
  try { await core.api("POST", "/api/selection", { workspace: ws || "", item: item || "" }); } catch (_) { /* fine */ }
  $("#btn-labels").disabled = !ws;
  const ex = $("#btn-export");
  ex.hidden = !ws;
  if (ws) ex.href = `/api/workspaces/${encodeURIComponent(ws)}/export.ttl`;
  S.seen = {};
  busy(refresh);
}

// ----------------------------------------------------------- the list ----

// A home on the current connection as a link to it in the Portal (the Portal opens a home with
// ?home=); a home on another connection, or a workspace not attached yet, stays plain text.
function homeLink(id, instance) {
  const c = S.cloud;
  if (!c || !c.site || instance !== c.connection || !c.homes.some((h) => h.smartHomeId === id)) return esc(id);
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
  box.innerHTML = homes.map((h) => `<div class="home">${h.instance
      ? `${homeLink(h.home, h.instance)} <small class="instance">${esc(h.instance)}</small>`
      : `${esc(h.home)} <small class="instance">${esc(t("list.unattached"))}</small>`}</div>` + h.workspaces.map((w) =>
    `<button data-ws="${esc(w.workspace)}" class="${w.workspace === S.ws ? "is-on" : ""}">
       <span>${esc(w.title)}</span><small>${esc(status(w.status))} · ${w.circuits}</small></button>`).join("")).join("");
  box.querySelectorAll("button[data-ws]").forEach((b) => b.onclick = () => select(b.dataset.ws));
}

// The homes a new workspace may name: the person's homes on the current connection.
// Not linked: no new workspace (ADR-0008).
async function drawHomeChoice() {
  let got;
  try { got = await core.api("GET", "/api/cloud-homes"); } catch (_) { return; }
  const key = JSON.stringify(got);
  if (S.seen.homes === key) return;
  S.seen.homes = key;
  S.cloud = got.linked ? { site: got.site, homes: got.homes, connection: got.connection } : null;
  S.seen.list = S.seen.design = null;           // redraw the home links
  const sel = $("#nw-home"), why = $("#nw-home-why");
  sel.innerHTML = got.homes.map((h) =>
    `<option value="${esc(h.smartHomeId)}">${esc(h.label)}${h.isDemo ? " " + esc(t("home.demo")) : ""}</option>`).join("");
  why.hidden = false;
  why.textContent = (got.linked ? t("home.onConnection", { name: got.connection }) : "")
    + (got.why || (got.homes.length ? "" : t("home.noneYet")));
  $("#nw-make").disabled = !got.linked || !got.homes.length;
}

// The homes the open workspace may be attached to, as <option>s.
function homeOptions() {
  return ((S.cloud && S.cloud.homes) || []).map((h) =>
    `<option value="${esc(h.smartHomeId)}">${esc(h.label)}${h.isDemo ? " " + esc(t("home.demo")) : ""}</option>`).join("");
}

// --------------------------------------------------------- the design ----

function circuitLine(c) {
  // a surveyed circuit may not know its values yet: "?" rather than a guess
  const what = [c.type ? c.type.replace("_", " ") : "?", `${c.rated_current ?? "?"} A`, `${c.cross_section ?? "?"} mm²`,
                c.protection === "fuse" ? t("circuit.fuse") : "",
                c.points ? t("circuit.pts", { n: c.points }) : "", c.appliance.replace("_", " "),
                c.to_verify ? "⚠ " + t("circuit.verify") : ""].filter(Boolean).join(" · ");
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
        <small> ${esc(t("board.rcd", { a: r.rated_current ?? "?", ma: r.sensitivity_ma, type: r.rcd_type || "?", n: r.circuits.length }))}${r.to_verify ? ` · ⚠ ${esc(t("circuit.verify"))}` : ""}</small>
        <ul class="circuits">${r.circuits.map(circuitLine).join("")}</ul></div>`).join("")}
    ${(b.circuits || []).length ? `<div class="rcd no-rcd"><b>${esc(t("board.norcd"))}</b>
        <ul class="circuits">${b.circuits.map(circuitLine).join("")}</ul></div>` : ""}
    ${b.devices.length ? `<ul class="devices">${b.devices.map((d) =>
      `<li data-item="${esc(d.id)}"><span>${esc(d.label)}</span><small>${esc(d.kind.replace("_", " "))}${
        d.rated_current != null ? " · " + d.rated_current + " A" : ""}${
        d.sensitivity_ma != null ? " · " + d.sensitivity_ma + " mA" : ""} · ${esc(t("board.mod", { n: d.modules }))}${
        d.to_verify ? " · ⚠ " + esc(t("circuit.verify")) : ""}</small></li>`).join("")}</ul>` : ""}
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
    <p class="sub">${homeLink(d.home, d.instance)}${d.instance ? ` <small class="instance">${esc(d.instance)}</small>` : ""}
      · ${esc(d.country)} · ${esc(status(d.status))} · <small title="${esc(t("design.idTitle"))}">${esc(S.ws)}</small></p>
    ${d.instance ? "" : `<div class="attach note"><p>${esc(t("design.unattached", { home: d.home }))}</p>
      ${S.cloud && S.cloud.homes.length
        ? `<select class="attach-home">${homeOptions()}</select>
           <button type="button" class="attach-go primary">${esc(t("design.attach", { name: S.cloud.connection }))}</button>`
        : `<p>${esc(t("design.attachLink"))}</p>`}</div>`}
    ${d.boards.length ? d.boards.map(boardBlock).join("")
      : `<p class="note">${esc(t("design.noBoard"))}</p>`}
    ${d.rooms.length ? `<h3>${esc(t("design.rooms"))}</h3><div class="rooms">${d.rooms.map((r) =>
      `<span>${esc(r.label)}${r.items.length ? " · " + r.items.length : ""}</span>`).join("")}</div>` : ""}`;
  box.querySelectorAll("li[data-item]").forEach((li) => li.onclick = () => select(S.ws, li.dataset.item));
  box.querySelector(".ws-rename").onclick = () => renameForm(box.querySelector(".ws-head"), d.title);
  const go = box.querySelector(".attach-go");
  if (go) go.onclick = async () => {
    const ws = S.ws;
    try {
      await core.api("POST", `/api/workspaces/${encodeURIComponent(ws)}/attach`,
                     { home: box.querySelector(".attach-home").value, connection: S.cloud.connection });
      core.toast(t("design.attached"));
      S.seen = {};
      refresh();
    } catch (err) { core.toast(failed(err)); }
  };
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

// ----------------------------------------------------------- history ----
// Every saved state of the design (ADR-0009): compare two, name one, make a
// baseline (a frozen name: the as-is installation), restore one as a new revision.

function drawDiff(d) {
  if (!d) return "";
  const vals = (v) => v.length ? v.map(esc).join(", ") : "—";
  const node = (x) => `${esc(kind(x.type.toLowerCase()) || x.type)} <b>${esc(x.label || x.id)}</b>`;
  const none = !d.added.length && !d.removed.length && !d.changed.length;
  return `<div class="diff"><p class="sub">${esc(t("h.between", { a: d.from, b: d.to }))}</p>
    ${none ? `<p class="ok">${esc(t("h.same"))}</p>` : ""}
    ${d.added.map((x) => `<div class="add">+ ${node(x)}</div>`).join("")}
    ${d.removed.map((x) => `<div class="del">− ${node(x)}</div>`).join("")}
    ${d.changed.map((x) => `<div class="chg">~ ${node(x)}<ul>${x.changes.map((c) =>
      `<li><code>${esc(c.property)}</code> ${vals(c.before)} → ${vals(c.after)}</li>`).join("")}</ul></div>`).join("")}</div>`;
}

async function drawHistory() {
  const revs = await core.api("GET", `/api/workspaces/${encodeURIComponent(S.ws)}/revisions`);
  const key = JSON.stringify(revs) + JSON.stringify(S.cmp || null) + (S.tagging || "") + (S.restoring || "");
  if (S.seen.history === key) return;
  S.seen.history = key;
  const base = revs.flatMap((r) => r.tags.filter((g) => g.frozen).map((g) => g.name))[0];
  const opts = (sel) => revs.map((r) => {
    const name = r.tags.length ? ` · ${r.tags.map((g) => g.name).join(", ")}` : "";
    return `<option value="${r.n}" ${String(r.n) === String(sel) ? "selected" : ""}>r${r.n}${esc(name)}</option>`;
  }).join("");
  const from = S.cmpFrom || (base ? revs.find((r) => r.tags.some((g) => g.name === base)).n : (revs[1] || revs[0] || {}).n);
  const to = S.cmpTo || (revs[0] || {}).n;
  $("#tab-history").innerHTML = `
    <section class="cloud-conf"></section>
    <p class="sub">${esc(t("h.intro"))}</p>
    <form class="compare">${esc(t("h.compare"))} <select name="from">${opts(from)}</select> → <select name="to">${opts(to)}</select>
      <button type="submit">${esc(t("h.go"))}</button></form>
    ${drawDiff(S.cmp)}
    <table class="history"><thead><tr><th>#</th><th>${esc(t("h.when"))}</th><th>${esc(t("h.via"))}</th>
      <th>${esc(t("h.what"))}</th><th></th></tr></thead><tbody>
    ${revs.map((r, i) => `<tr data-n="${r.n}"><td>r${r.n}</td><td>${esc(when(r.at))}</td>
      <td>${esc(t(`h.via.${r.via}`))}<br><small>${esc(r.by)}</small></td>
      <td>${esc(r.summary)}${r.tags.map((g) => ` <span class="tag${g.frozen ? " frozen" : ""}" title="${esc(g.frozen ? t("h.frozen") : "")}">${g.frozen ? "🔒 " : ""}${esc(g.name)}</span>`).join("")}
        ${S.tagging === String(r.n) ? `<form class="tagging"><input name="name" maxlength="80" placeholder="${esc(t("h.tagPh"))}" required>
          <label><input type="checkbox" name="frozen"> ${esc(t("h.baseline"))}</label><button type="submit">${esc(t("h.save"))}</button></form>` : ""}</td>
      <td class="acts"><button class="tag-it">${esc(t("h.tag"))}</button>
        ${i > 0 ? `<button class="restore${S.restoring === String(r.n) ? " sure" : ""}">${esc(t(S.restoring === String(r.n) ? "h.sure" : "h.restore"))}</button>` : ""}</td></tr>`).join("")}
    </tbody></table>`;
  const again = () => { S.seen.history = null; drawHistory(); };
  const path = `/api/workspaces/${encodeURIComponent(S.ws)}`;
  drawCloud();
  $("#tab-history form.compare").onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target;
    S.cmpFrom = f.from.value; S.cmpTo = f.to.value;
    try { S.cmp = await core.api("GET", `${path}/diff?from=${f.from.value}&to=${f.to.value}`); } catch (err) { core.toast(failed(err)); }
    again();
  };
  document.querySelectorAll("#tab-history tr[data-n]").forEach((tr) => {
    const n = tr.dataset.n;
    tr.querySelector(".tag-it").onclick = () => { S.tagging = S.tagging === n ? "" : n; S.restoring = ""; again(); };
    const form = tr.querySelector("form.tagging");
    if (form) {
      form.name.focus();
      form.onsubmit = async (e) => {
        e.preventDefault();
        try { await core.api("POST", `${path}/revisions/${n}/tag`, { name: form.name.value, frozen: form.frozen.checked }); S.tagging = ""; }
        catch (err) { core.toast(failed(err)); }
        again();
      };
    }
    const back = tr.querySelector(".restore");
    if (back) back.onclick = async () => {
      if (S.restoring !== n) { S.restoring = n; S.tagging = ""; return again(); }
      S.restoring = "";
      try { const r = await core.api("POST", `${path}/revisions/${n}/restore`); core.toast(t("h.restored", { n, m: r.revision })); }
      catch (err) { core.toast(failed(err)); }
      S.seen = {}; refresh();
    };
  });
}

// The home's configurations and vault in the cloud (ADR-0010): fetched when
// the tab is opened and on Refresh, not on every poll (each is a cloud call).
async function drawCloud() {
  const box = $("#tab-history .cloud-conf");
  if (!box) return;
  const path = `/api/workspaces/${encodeURIComponent(S.ws)}`;
  if (!S.conf) {
    box.innerHTML = `<p class="sub">${esc(t("c.loading"))}</p>`;
    try { S.conf = await core.api("GET", `${path}/configuration`); } catch (err) { S.conf = { error: failed(err) }; }
  }
  const c = S.conf;
  const again = () => drawCloud();
  const reload = () => { S.conf = null; S.seen = {}; refresh(); };
  if (c.error) {
    box.innerHTML = `<h3>${esc(t("c.title"))}</h3><p class="sub">${esc(c.error)}</p><button class="c-reload">${esc(t("c.reload"))}</button>`;
    box.querySelector(".c-reload").onclick = reload;
    return;
  }
  const short = (id) => (id || "").replace(c.homeId + "-", "");
  const link = c.link || {};
  const sure = (k, label) => `<button class="c-${k}${S.confSure === k ? " sure" : ""}">${esc(t(S.confSure === k ? "c.sure" : label))}</button>`;
  const plan = S.vaultPlan;
  box.innerHTML = `<h3>${esc(t("c.title"))}</h3>
    <p class="sub">${esc(t("c.intro"))}</p>
    <dl class="c-facts">
      <dt>${esc(t("c.live"))}</dt><dd>${c.live ? esc(short(c.live)) : esc(t("c.none"))}</dd>
      <dt>${esc(t("c.based"))}</dt><dd>${link.basedOn ? esc(short(link.basedOn)) : "—"}</dd>
      <dt>${esc(t("c.option"))}</dt><dd>${link.option ? `${esc(short(link.option))} · v${link.optionVersion}` : "—"}</dd>
    </dl>
    ${(c.versions || []).length ? `<ul class="c-versions">${c.versions.map((v) =>
      `<li class="${esc(v.status)}"><b>${esc(v.version)}</b> <small>${esc(t(`c.st.${v.status}`))} · ${esc(v.summary || "")} · ${esc(when(v.at))}</small></li>`).join("")}</ul>` : ""}
    ${(c.options || []).length ? `<ul class="c-options">${c.options.map((o) =>
      `<li><b>${esc(short(o.id))}</b> ${esc(o.label)} <small>${esc(t("c.from", { v: short(o.basedOn) }))} · v${o.version} · ${esc(o.status)}</small></li>`).join("")}</ul>` : ""}
    <div class="c-acts">
      ${!c.live ? sure("publish", "c.publish") : ""}
      ${c.live && !link.option ? `<form class="c-new"><input name="label" maxlength="80" placeholder="${esc(t("c.optPh"))}" required><button type="submit">${esc(t("c.newOpt"))}</button></form>` : ""}
      ${link.option ? `<button class="c-pull">${esc(t("c.pull"))}</button><button class="c-push">${esc(t("c.push"))}</button>${sure("promote", "c.promote")}` : ""}
      <button class="c-vault">${esc(t("c.vault"))}</button>
      <button class="c-reload">${esc(t("c.reload"))}</button>
    </div>
    ${plan ? `<div class="c-plan"><p class="sub">${esc(t("c.planIntro", { g: short(plan.group) || "—" }))}</p>
      <ul>${plan.files.map((f) => `<li>${esc(f.name)} <small>${esc(t(`c.f.${f.status}`))}</small></li>`).join("")}</ul>
      ${plan.files.some((f) => f.status === "new") && !plan.done ? `<button class="c-upload">${esc(t("c.upload", { n: plan.files.filter((f) => f.status === "new").length }))}</button>` : ""}</div>` : ""}`;

  const call = async (sub, body, ok) => {
    try { const r = await core.api("POST", `${path}/configuration/${sub}`, body || {}); if (r.status === "conflict") core.toast(r.why); else core.toast(ok(r)); }
    catch (err) { core.toast(failed(err)); }
    S.confSure = ""; reload();
  };
  const twice = (k, go) => () => { if (S.confSure !== k) { S.confSure = k; return again(); } go(); };
  const on = (sel, fn) => { const el = box.querySelector(sel); if (el) el.onclick = fn; };
  on(".c-publish", twice("publish", () => call("publish", {}, (r) => t("c.published", { v: short(r.id) }))));
  on(".c-promote", twice("promote", () => call("promote", {}, (r) => t("c.promoted", { v: short(r.id) }))));
  on(".c-pull", () => call("pull", {}, (r) => t("c.pulled", { v: r.version })));
  on(".c-push", () => call("push", {}, (r) => t("c.pushed", { v: r.version })));
  on(".c-reload", reload);
  const form = box.querySelector("form.c-new");
  if (form) form.onsubmit = (e) => { e.preventDefault(); call("option", { label: form.label.value }, (r) => t("c.created", { v: short(r.id) })); };
  on(".c-vault", async () => {
    try { S.vaultPlan = await core.api("POST", `${path}/vault/upload`, { dry_run: true }); } catch (err) { core.toast(failed(err)); }
    again();
  });
  on(".c-upload", async () => {
    try {
      const r = await core.api("POST", `${path}/vault/upload`, { dry_run: false, config_version: plan.group });
      S.vaultPlan = { ...r, done: true };
      core.toast(t("c.uploaded", { n: r.files.filter((f) => f.status === "ok").length }));
    } catch (err) { core.toast(failed(err)); }
    again();
  });
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

// ------------------------------------------------------------ labels ----
// A wizard in five steps: what to print, its format, what each label says
// (text, pictogram, phase), a check by the chat, then the print page. The
// format is kept per workspace (label-settings.json); what a label says is
// in the design (set_label, set_phase), so revisions keep it.

const LSTEPS = ["what", "format", "content", "check", "print"];
const SUPPLIES = { "1N~230V": ["L1"], "3N~400V": ["L1", "L2", "L3", "L1L2L3"], "3~230V": ["L1L2", "L2L3", "L3L1", "L1L2L3"] };
const phaseText = (p) => (p || "").match(/L\d/g)?.join("-") || "";

async function symbolList() {
  if (!S.symbols) S.symbols = await core.api("GET", "/api/symbols");
  return S.symbols;
}

// typing in a text or number field: the poll waits; what the person clicked redraws at once
const typing = (box) => box.contains(document.activeElement)
  && document.activeElement.matches("input:not([type=checkbox]):not([type=radio]), textarea");

async function drawLabels(force = false) {
  const box = $("#tab-labels");
  if (!force && typing(box)) return;
  const wsq = encodeURIComponent(S.ws);
  const [d, syms] = await Promise.all([core.api("GET", `/api/workspaces/${wsq}/labels`), symbolList()]);
  const step = S.lstep || "what";
  const key = JSON.stringify(d) + step + JSON.stringify(S.lplan || null) + (S.lprint || 0);
  if (S.seen.labels === key) return;
  S.seen.labels = key;
  const s = d.settings;
  const save = async (patch) => {
    if (document.activeElement && box.contains(document.activeElement)) document.activeElement.blur();
    try { await busy(core.api("POST", `/api/workspaces/${wsq}/labels/settings`, patch)); } catch (err) { core.toast(failed(err)); }
    S.seen.labels = null; return busy(() => drawLabels(true));
  };
  const nwarn = d.labels.reduce((n, l) => n + l.warnings.length, 0);
  const nav = `<ol class="lw-steps">${LSTEPS.map((k, i) => `<li><button data-step="${k}" class="${k === step ? "is-on" : ""}">
      ${i + 1}. ${esc(t(`lw.${k}`))}${k === "content" && nwarn ? ` <span class="lw-n">${nwarn}</span>` : ""}</button></li>`).join("")}</ol>`;
  const chk = (name, label) => `<label class="lw-chk"><input type="checkbox" name="${name}" ${s[name] ? "checked" : ""}> ${esc(label)}</label>`;
  const num = (name, label, min, max, stepv, presets) => `<label class="lw-num">${esc(label)}
      <input type="number" name="${name}" min="${min}" max="${max}" step="${stepv}" value="${s[name]}">
      ${(presets || []).map((p) => `<button type="button" class="lw-preset" data-name="${name}" data-v="${p}">${p}</button>`).join("")}</label>`;
  let body = "";
  if (step === "what") {
    body = `<fieldset class="lw-kind"><legend>${esc(t("lw.kindQ"))}</legend>
        ${["board", "cable", "qr", "tag", "blank"].map((k) => `<label class="lw-card ${s.kind === k ? "is-on" : ""}"><input type="radio" name="kind" value="${k}" ${s.kind === k ? "checked" : ""}>
          <b>${esc(t(`lw.k.${k}`))}</b><small>${esc(t(`lw.k.${k}Hint`))}</small></label>`).join("")}</fieldset>
      ${s.kind === "blank" ? `<fieldset class="lw-blank"><legend>${esc(t("lw.blankQ"))}</legend>
        <p class="note">${esc(t("lw.blankHave", { n: d.blank }))}</p>
        <label class="lw-num">${esc(t("lw.blankMint"))} <input type="number" class="lw-blank-n" min="1" max="200" value="24"></label>
        <button class="primary lw-blank-go" ${d.cards ? "" : "disabled"}>${esc(t("lw.blankGo"))}</button></fieldset>` : ""}
      ${d.cards ? `<p class="note">${esc(t("lw.cardsTo", { site: d.cards.site.replace(/^https?:\/\//, "") }))}</p>`
        : `<div class="finding warning"><b>${esc(t("lw.noCardsTitle"))}</b>${esc(t("lw.noCards"))}</div>`}
      <fieldset><legend>${esc(t("lw.boards"))}</legend>
        ${d.boards.map((b) => `<label class="lw-chk"><input type="checkbox" class="lw-board" value="${esc(b.id)}"
           ${!s.boards.length || s.boards.includes(b.id) ? "checked" : ""}> ${esc(b.label)}</label>`).join("") || `<p class="note">${esc(t("lw.noBoards"))}</p>`}</fieldset>
      <fieldset><legend>${esc(t("lw.supply"))}</legend>
        <select class="lw-supply">${d.supply_set || d.supply ? "" : `<option value="">${esc(t("lw.supplyAsk"))}</option>`}
          ${Object.keys(SUPPLIES).map((k) => `<option value="${k}" ${d.supply === k ? "selected" : ""}>${esc(t(`lw.sup.${k}`))}</option>`).join("")}</select>
        ${d.supply_set ? "" : `<small class="note">${esc(d.supply ? t("lw.supplyDefault") : t("lw.supplyNone"))}</small>`}</fieldset>`;
  } else if (step === "format") {
    body = `<form class="lw-format">
      <fieldset><legend>${esc(t("lw.k.board"))}</legend>
        ${num("module_mm", t("lw.module"), 9, 27, 0.5, [17.5, 18])}
        ${num("strip_h", t("lw.strip"), 10, 60, 1, [12, 15, 20, 30])}</fieldset>
      <fieldset><legend>${esc(t("lw.k.cable"))}</legend>
        ${num("cable_h", t("lw.cableH"), 9, 40, 1, [15, 19, 25])}
        ${num("cable_d", t("lw.cableD"), 0, 40, 0.5, [])}<small class="note">${esc(t("lw.cableDHint"))}</small></fieldset>
      <fieldset><legend>${esc(t("lw.k.tag"))}</legend>
        ${num("tag_mm", t("lw.tagSize"), 12, 30, 1, [15, 20, 25])}<small class="note">${esc(t("lw.tagHint"))}</small></fieldset>
      <fieldset><legend>${esc(t("lw.text"))}</legend>
        ${num("font_pt", t("lw.font"), 5, 14, 0.5, [6.5, 7.5, 9])}
        ${chk("show_symbol", t("lw.showSymbol"))}${chk("show_phase", t("lw.showPhase"))}${chk("show_number", t("lw.showNumber"))}</fieldset></form>`;
  } else if (step === "content") {
    const phases = SUPPLIES[d.supply] || [];
    const three = phases.length > 1;
    const symOpts = (cur) => syms.map((x) => `<option value="${x.id}" ${x.id === cur ? "selected" : ""}>${esc(x.name)}</option>`).join("");
    const symSvg = (id) => (syms.find((x) => x.id === id) || {}).svg || "";
    const picked = new Set(s.items);
    body = `<div class="lw-bar">
        ${three ? `<button class="lw-balance">${esc(t("lw.balance"))}</button>` : `<span class="note">${esc(t("lw.onePhase"))}</span>`}
        <span class="note">${esc(t("lw.contentHint"))}</span></div>
      ${S.lplan ? `<div class="lw-plan"><b>${esc(t("lw.planTitle"))}</b>
          ${S.lplan.assign.length ? `<ul>${S.lplan.assign.map((a) => `<li>${esc(a.label)} → <b>${esc(phaseText(a.phase))}</b></li>`).join("")}</ul>
          <p class="note">${esc(t("lw.planLoad", { l: Object.entries(S.lplan.load).map(([k, v]) => `${k} ${v} A`).join(" · ") }))}</p>
          <button class="primary lw-apply">${esc(t("lw.planApply", { n: S.lplan.assign.length }))}</button>`
          : `<p class="note">${esc(S.lplan.note || t("lw.planNone"))}</p>`}
          <button class="lw-plan-x">${esc(t("lw.close"))}</button></div>` : ""}
      <table class="lw-table"><thead><tr><th>✓</th><th>№</th><th>${esc(t("lw.col.symbol"))}</th><th>${esc(t("lw.col.text"))}</th>
        <th>${esc(t("lw.col.short"))}</th>${three ? `<th>${esc(t("lw.col.phase"))}</th>` : ""}<th>${esc(t("lw.col.check"))}</th></tr></thead><tbody>
      ${d.labels.map((l) => `<tr data-item="${esc(l.item)}" class="${l.warnings.length ? "has-warn" : ""}">
        <td><input type="checkbox" class="lw-pick" ${!picked.size || picked.has(l.item) ? "checked" : ""}></td>
        <td class="num">${esc(l.number || "—")}<small>${esc(kind(l.kind))}</small></td>
        <td class="lw-sym"><span class="lw-svg">${symSvg(l.symbol)}</span><select class="lw-symbol">${symOpts(l.symbol)}</select></td>
        <td><input class="lw-text" value="${esc(l.label_text)}" placeholder="${esc(l.name)}" maxlength="60"></td>
        <td><input class="lw-short" value="${esc(l.label_short)}" placeholder="${esc(l.derived_short)}" maxlength="20"></td>
        ${three ? `<td>${["circuit", "rcd"].includes(l.kind) || l.phase_own ? `<select class="lw-phase"><option value="">${esc(l.phase && !l.phase_own ? `(${phaseText(l.phase)})` : "—")}</option>
            ${phases.map((p) => `<option value="${p}" ${l.phase_own === p ? "selected" : ""}>${esc(phaseText(p))}</option>`).join("")}</select>` : ""}</td>` : ""}
        <td class="lw-warn">${l.warnings.map((w) => `<div class="w-${esc(w.code)}">${esc(w.text)}</div>`).join("")}</td></tr>`).join("")}
      </tbody></table>`;
  } else if (step === "check") {
    body = `<p>${esc(t("lw.checkIntro"))}</p>
      <ul class="lw-checks">${["len", "words", "lang", "design", "phase"].map((k) => `<li>${esc(t(`lw.chk.${k}`))}</li>`).join("")}</ul>
      <p class="note">${esc(t("lw.warnCount", { n: nwarn }))}</p>
      <button class="primary lw-ask">${esc(t("lw.ask"))}</button>
      <p class="note">${esc(t("lw.askHint"))}</p>`;
  } else {
    const open = d.labels.filter((l) => l.warnings.some((w) => ["too_long", "no_phase", "duplicate"].includes(w.code)));
    const src = `/workspaces/${wsq}/labels?_=${S.lprint || 0}`;
    body = `${["qr", "tag", "blank"].includes(s.kind) ? `<p class="note">${esc(t("lw.pushNote"))}</p>` : ""}
      ${open.length ? `<div class="finding warning"><b>${esc(t("lw.stillOpen", { n: open.length }))}</b>
        ${open.slice(0, 6).map((l) => esc(`${l.number || "—"} ${l.title}: ${l.warnings.map((w) => w.text).join("; ")}`)).join("<br>")}</div>` : ""}
      <div class="lw-bar"><button class="primary lw-print">${esc(t("lw.printBtn"))}</button>
        <a class="btn" href="${src}" target="_blank" rel="noopener">${esc(t("lw.openTab"))}</a>
        <span class="note">${esc(t("lw.printHint"))}</span></div>
      <iframe class="lw-preview" src="${src}" title="${esc(t("lw.print"))}"></iframe>`;
  }
  const i = LSTEPS.indexOf(step);
  box.innerHTML = `${nav}<div class="lw-body">${body}</div>
    <div class="lw-foot">${i > 0 ? `<button class="lw-prev">← ${esc(t(`lw.${LSTEPS[i - 1]}`))}</button>` : ""}
      ${i < LSTEPS.length - 1 ? `<button class="primary lw-next">${esc(t(`lw.${LSTEPS[i + 1]}`))} →</button>` : ""}</div>`;

  const go = (k) => { S.lstep = k; if (k === "print") S.lprint = Date.now(); S.seen.labels = null; return busy(() => drawLabels(true)); };
  box.querySelectorAll(".lw-steps button").forEach((b) => b.onclick = () => go(b.dataset.step));
  const prev = box.querySelector(".lw-prev"); if (prev) prev.onclick = () => go(LSTEPS[i - 1]);
  const next = box.querySelector(".lw-next"); if (next) next.onclick = () => go(LSTEPS[i + 1]);
  box.querySelectorAll("input[name=kind]").forEach((r) => r.onchange = () => save({ kind: r.value }));
  const mint = box.querySelector(".lw-blank-go");
  if (mint) mint.onclick = async () => {
    const n = Number(box.querySelector(".lw-blank-n").value || 0);
    try { await busy(core.api("POST", `/api/workspaces/${wsq}/labels/blank`, { count: n })); core.toast(t("lw.blankDone", { n })); }
    catch (err) { core.toast(failed(err)); }
    S.seen.labels = null; return busy(() => drawLabels(true));
  };
  const boardsBox = box.querySelectorAll(".lw-board");
  boardsBox.forEach((c) => c.onchange = () => {
    const on = [...boardsBox].filter((x) => x.checked).map((x) => x.value);
    save({ boards: on.length === boardsBox.length ? [] : on });
  });
  const sup = box.querySelector(".lw-supply");
  if (sup) sup.onchange = async () => {
    if (!sup.value) return;
    try { await busy(core.api("POST", `/api/workspaces/${wsq}`, { supply: sup.value })); } catch (err) { core.toast(failed(err)); }
    S.seen.labels = null; return busy(() => drawLabels(true));
  };
  const fmt = box.querySelector(".lw-format");
  if (fmt) {
    fmt.querySelectorAll("input[type=number]").forEach((x) => x.onchange = () => save({ [x.name]: Number(x.value) }));
    fmt.querySelectorAll("input[type=checkbox]").forEach((x) => x.onchange = () => save({ [x.name]: x.checked }));
    fmt.querySelectorAll(".lw-preset").forEach((b) => b.onclick = () => save({ [b.dataset.name]: Number(b.dataset.v) }));
  }
  const item = (el) => el.closest("tr").dataset.item;
  const post = async (el, path, data) => {
    try { await busy(core.api("POST", `/api/workspaces/${wsq}/items/${encodeURIComponent(item(el))}/${path}`, data)); }
    catch (err) { core.toast(failed(err)); }
    el.blur(); S.seen.labels = null; return busy(() => drawLabels(true));
  };
  box.querySelectorAll(".lw-text").forEach((x) => x.onchange = () => post(x, "label", { text: x.value }));
  box.querySelectorAll(".lw-short").forEach((x) => x.onchange = () => post(x, "label", { short: x.value }));
  box.querySelectorAll(".lw-symbol").forEach((x) => x.onchange = () => post(x, "label", { symbol: x.value }));
  box.querySelectorAll(".lw-phase").forEach((x) => x.onchange = () => post(x, "phase", { phase: x.value }));
  const picks = box.querySelectorAll(".lw-pick");
  picks.forEach((c) => c.onchange = () => {
    const on = [...picks].filter((x) => x.checked).map(item);
    c.blur();
    save({ items: on.length === picks.length ? [] : on });
  });
  const bal = box.querySelector(".lw-balance");
  if (bal) bal.onclick = async () => {
    try { S.lplan = await busy(core.api("GET", `/api/workspaces/${wsq}/phase-plan`)); } catch (err) { core.toast(failed(err)); }
    S.seen.labels = null; return busy(() => drawLabels(true));
  };
  const px = box.querySelector(".lw-plan-x"); if (px) px.onclick = () => { S.lplan = null; S.seen.labels = null; return busy(() => drawLabels(true)); };
  const apply = box.querySelector(".lw-apply");
  if (apply) apply.onclick = async () => {
    apply.disabled = true;
    busyOn();
    for (const a of S.lplan.assign) {
      try { await core.api("POST", `/api/workspaces/${wsq}/items/${encodeURIComponent(a.item)}/phase`, { phase: a.phase }); }
      catch (err) { core.toast(failed(err)); break; }
    }
    busyOff();
    S.lplan = null; S.seen.labels = null; return busy(() => drawLabels(true));
  };
  const ask = box.querySelector(".lw-ask");
  if (ask) ask.onclick = () => {
    const form = document.querySelector("#edge-chat .edge-chat__ask");
    const input = form && form.querySelector("textarea, input");
    if (!input) { core.toast(t("lw.noChat")); return; }
    input.value = t("lw.askText", { ws: S.wsTitle || S.ws });
    form.requestSubmit();
    core.toast(t("lw.asked"));
  };
  const frame = box.querySelector(".lw-preview");
  if (frame) {                                  // the sheet renders in the frame: wait for it
    busyOn();
    const done = () => { if (frame.dataset.done) return; frame.dataset.done = "1"; busyOff(); };
    frame.addEventListener("load", done);
    setTimeout(done, 15000);
  }
  const pr = box.querySelector(".lw-print");
  if (pr) pr.onclick = () => { const f = box.querySelector(".lw-preview"); if (f && f.contentWindow) f.contentWindow.print(); };
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
    if (S.tab === "labels") await drawLabels();   // the poll: not while typing
    if (S.tab === "history") await drawHistory();
  } catch (err) {
    if (err && err.status === 404 && S.ws) select(null);
  }
}

function wire() {
  document.querySelectorAll(".tabs button").forEach((b) => b.onclick = () => {
    S.tab = b.dataset.tab;
    if (S.tab === "labels") S.lprint = Date.now();      // a fresh preview
    document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("is-on", x === b));
    document.querySelectorAll(".tab").forEach((t) => t.hidden = t.id !== `tab-${S.tab}`);
    S.seen = {};
    busy(refresh);
  });
  $("#nw-make").onclick = async () => {
    try {
      const got = await core.api("POST", "/api/workspaces", {
        title: $("#nw-title").value, home: $("#nw-home").value, country: $("#nw-country").value,
        connection: S.cloud ? S.cloud.connection : "" });
      $("#nw-title").value = "";
      select(got.workspace);
    } catch (err) { core.toast(failed(err)); }
  };
  $("#btn-labels").onclick = () => S.ws && document.querySelector('.tabs button[data-tab="labels"]').click();
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
