/* Outbounder — single-file vanilla JS front end. */
(() => {
  const $ = (sel, el = document) => el.querySelector(sel);
  const view = $("#view");
  const drawer = $("#drawer");
  const modal = $("#modal");
  const backdrop = $("#modal-backdrop");
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ---- auth (shared password) -------------------------------------------
  const PW_KEY = "outbounder.pw";
  function password() { return localStorage.getItem(PW_KEY) || ""; }
  async function askPassword(msg) {
    const pw = window.prompt(msg || "Password for this Outbounder instance:");
    if (pw == null) throw new Error("cancelled");
    localStorage.setItem(PW_KEY, pw);
  }

  async function api(path, opts = {}) {
    const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
    if (password()) headers.Authorization = `Bearer ${password()}`;
    const res = await fetch(path, { ...opts, headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
    if (res.status === 401) {
      await askPassword("Password required:");
      return api(path, opts);
    }
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch {}
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    if (res.status === 204) return null;
    return res.json();
  }

  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg;
    t.classList.remove("hidden");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => t.classList.add("hidden"), 2200);
  }
  async function copy(text) {
    try { await navigator.clipboard.writeText(text); toast(`Copied ${text}`); } catch { toast("Copy failed"); }
  }

  // ---- modal -------------------------------------------------------------
  function openModal(html) { modal.innerHTML = html; backdrop.classList.remove("hidden"); }
  function closeModal() { backdrop.classList.add("hidden"); modal.innerHTML = ""; }
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) closeModal(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeModal(); closeDrawer(); } });

  function newListModal(listId) {
    const appending = Boolean(listId);
    openModal(`
      <h2>${appending ? "Add people to this list" : "New outbound list"}</h2>
      <p class="help">Paste anything: names, "Name – Title at Company", LinkedIn URLs, notes, a copied spreadsheet.
      Each person becomes a row; Outbounder identifies them, finds emails, does the research and links you out.</p>
      ${appending ? "" : `<label>List name (optional)</label><input id="m-name" placeholder="e.g. Seed-stage fintech CTOs — Sept">`}
      <label>People</label>
      <textarea id="m-raw" placeholder="Jane Doe - VP Engineering at Acme
Bob Smith, Head of Growth, Widgets Inc (met at SaaStr)
https://www.linkedin.com/in/someone/ — intro'd by Sam"></textarea>
      ${appending ? "" : `<label>Context for research (optional): who you are / what you're offering</label>
      <textarea id="m-ctx" style="min-height:70px;font-family:inherit" placeholder="I'm the founder of X, a tool that does Y. Looking for design partners among Z."></textarea>`}
      <div class="row">
        <button class="btn" id="m-cancel">Cancel</button>
        <button class="btn btn-primary" id="m-go">${appending ? "Add & enrich" : "Create & enrich"}</button>
      </div>`);
    $("#m-cancel").onclick = closeModal;
    $("#m-raw").focus();
    $("#m-go").onclick = async () => {
      const raw = $("#m-raw").value.trim();
      if (!raw) return toast("Paste at least one person");
      $("#m-go").disabled = true;
      try {
        if (appending) {
          await api(`/api/lists/${listId}/append`, { method: "POST", body: { raw_input: raw } });
          closeModal();
          loadList(listId);
        } else {
          const l = await api("/api/lists", {
            method: "POST",
            body: { name: $("#m-name").value, raw_input: raw, context: $("#m-ctx").value },
          });
          closeModal();
          location.hash = `#/lists/${l.id}`;
        }
      } catch (e) { toast(e.message); $("#m-go").disabled = false; }
    };
  }
  $("#new-list-btn").onclick = () => newListModal();

  // ---- status/providers ------------------------------------------------------
  async function loadProviders() {
    try {
      const s = await api("/api/status");
      const tag = (k, on) => (on ? `<b>${k}</b>` : `<i>${k}</i>`);
      $("#providers").innerHTML = [tag("llm", s.llm), tag("exa", s.exa), tag("firecrawl", s.firecrawl), tag("hunter", s.hunter), tag("smtp", s.smtp_verify)].join(" · ");
    } catch {}
  }

  // ---- routing -----------------------------------------------------------
  let pollTimer = null;
  function stopPolling() { clearTimeout(pollTimer); pollTimer = null; }
  function route() {
    stopPolling();
    closeDrawer();
    const m = location.hash.match(/^#\/lists\/([0-9a-f-]+)/i);
    if (m) loadList(m[1]);
    else loadHome();
  }
  window.addEventListener("hashchange", route);

  // ---- home --------------------------------------------------------------
  async function loadHome() {
    $("#crumbs").innerHTML = "";
    let lists;
    try { lists = await api("/api/lists"); } catch (e) { view.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
    if (!lists.length) {
      view.innerHTML = `<div class="empty"><h2>No lists yet</h2><p>Paste a rough list of people and get back a research-ready table.</p>
        <button class="btn btn-primary" id="empty-new">+ New list</button></div>`;
      $("#empty-new").onclick = () => newListModal();
      return;
    }
    view.innerHTML = `<div class="page-head"><h1>Lists</h1></div><div class="cards">${lists
      .map((l) => {
        const total = Number(l.total) || 0, done = Number(l.done) || 0, err = Number(l.errors) || 0, pend = Number(l.pending) || 0;
        const pct = (n) => (total ? (100 * n) / total : 0);
        return `<a class="card" href="#/lists/${l.id}">
          <h3>${esc(l.name)}</h3>
          <div class="meta">${total} people · ${done} done${err ? ` · <span style="color:var(--bad)">${err} errors</span>` : ""}${pend ? ` · ${pend} in progress` : ""} · ${new Date(l.created_at).toLocaleDateString()}</div>
          ${l.context ? `<div class="meta" style="margin-top:6px">${esc(l.context.slice(0, 140))}${l.context.length > 140 ? "…" : ""}</div>` : ""}
          <div class="progress"><div class="done" style="width:${pct(done)}%"></div><div class="err" style="width:${pct(err)}%"></div><div class="pend" style="width:${pct(pend)}%"></div></div>
        </a>`;
      })
      .join("")}</div>`;
    if (lists.some((l) => l.status === "parsing" || Number(l.pending) > 0)) pollTimer = setTimeout(loadHome, 4000);
  }

  // ---- list view ---------------------------------------------------------
  let current = null; // {list, targets}

  const STATUS = {
    queued: ["Queued", "chip-muted", true],
    identifying: ["Identifying", "chip-info", true],
    finding_email: ["Finding email", "chip-info", true],
    researching: ["Researching", "chip-info", true],
    done: ["Done", "chip-ok", false],
    error: ["Error", "chip-bad", false],
  };
  const VERIF = {
    valid: ["verified", "chip-ok"],
    catch_all: ["catch-all", "chip-warn"],
    unknown: ["unverified", "chip-muted"],
    invalid: ["bounces", "chip-bad"],
  };
  const inProgress = (t) => STATUS[t.status]?.[2];
  const displayName = (t) => t.confirmed_name || t.name || "(unnamed)";
  const displayTitle = (t) => t.confirmed_title || t.title || "";
  const displayCompany = (t) => t.confirmed_company || t.company || "";
  const bestCand = (t) => (t.emails || []).find((e) => e.email === t.best_email) || null;
  const pct = (x) => `${Math.round((x || 0) * 100)}%`;

  async function loadList(id) {
    let data;
    try { data = await api(`/api/lists/${id}`); } catch (e) { view.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
    current = data;
    renderList();
    const busy = data.status === "parsing" || data.targets.some(inProgress);
    if (busy) pollTimer = setTimeout(() => loadList(id), 3000);
  }

  function renderList() {
    const l = current;
    const ts = l.targets;
    $("#crumbs").innerHTML = `<a href="#/">Lists</a> / ${esc(l.name)}`;
    const done = ts.filter((t) => t.status === "done").length;
    const errs = ts.filter((t) => t.status === "error").length;
    const busy = ts.filter(inProgress).length;
    view.innerHTML = `
      <div class="page-head">
        <h1 contenteditable="true" spellcheck="false" id="list-name">${esc(l.name)}</h1>
        <span class="meta">${ts.length} people · ${done} done${busy ? ` · ${busy} in progress` : ""}${errs ? ` · <span style="color:var(--bad)">${errs} errors</span>` : ""}${l.status === "parsing" ? " · <span class='chip chip-info pulse'><span class='dot'></span>parsing your list…</span>" : ""}${l.status === "error" ? ` · <span style="color:var(--bad)">${esc(l.error)}</span>` : ""}</span>
        <div class="actions">
          <button class="btn btn-sm" id="add-people">+ Add people</button>
          ${errs ? `<button class="btn btn-sm" id="retry-errors">Retry errors</button>` : ""}
          <a class="btn btn-sm" href="/api/lists/${l.id}/export.csv" id="export">Export CSV</a>
          <button class="btn btn-sm btn-ghost btn-danger" id="delete-list">Delete</button>
        </div>
      </div>
      <div class="context-box"><b>Context:</b> <span id="ctx-text" contenteditable="true" spellcheck="false">${esc(l.context || "")}</span>${l.context ? "" : "<span style='opacity:.6'> (click to add what you're reaching out about — feeds the hooks)</span>"}</div>
      ${ts.length ? renderTable(ts) : `<div class="empty">${l.status === "parsing" ? "Parsing your list…" : "No people parsed from this list."}</div>`}`;

    $("#add-people").onclick = () => newListModal(l.id);
    $("#delete-list").onclick = async () => {
      if (!confirm(`Delete "${l.name}" and all ${ts.length} rows?`)) return;
      await api(`/api/lists/${l.id}`, { method: "DELETE" });
      location.hash = "#/";
    };
    const retry = $("#retry-errors");
    if (retry) retry.onclick = async () => { await api(`/api/lists/${l.id}/rerun?only_errors=true`, { method: "POST" }); loadList(l.id); };
    const nameEl = $("#list-name");
    nameEl.onblur = async () => {
      const name = nameEl.textContent.trim();
      if (name && name !== l.name) { await api(`/api/lists/${l.id}`, { method: "PATCH", body: { name } }); l.name = name; }
    };
    nameEl.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); nameEl.blur(); } };
    const ctxEl = $("#ctx-text");
    ctxEl.onblur = async () => {
      const context = ctxEl.textContent.trim();
      if (context !== (l.context || "")) { await api(`/api/lists/${l.id}`, { method: "PATCH", body: { context } }); l.context = context; toast("Context saved — re-run rows to refresh hooks"); }
    };
    // export needs the password header; fetch as blob when auth is on
    if (password()) {
      $("#export").onclick = async (e) => {
        e.preventDefault();
        const res = await fetch(`/api/lists/${l.id}/export.csv`, { headers: { Authorization: `Bearer ${password()}` } });
        const blob = await res.blob();
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob); a.download = `${l.name}.csv`; a.click();
      };
    }
    bindRows();
  }

  function renderTable(ts) {
    return `<table class="grid"><thead><tr>
      <th>#</th><th>Person</th><th>Email</th><th>Research</th><th>Links</th><th>Status</th><th>Outreach</th>
    </tr></thead><tbody>${ts.map((t, i) => renderRow(t, i)).join("")}</tbody></table>`;
  }

  function renderRow(t, i) {
    const [label, cls, pulse] = STATUS[t.status] || [t.status, "chip-muted", false];
    const best = bestCand(t);
    const r = t.research || {};
    const conf = t.identity_confidence;
    const lowConf = t.status === "done" && conf != null && conf < 0.5;
    const others = (t.emails || []).filter((e) => e.email !== t.best_email).slice(0, 2);
    const links = (t.links || []);
    const articles = links.filter((x) => x.kind === "article");
    const main = links.filter((x) => x.kind !== "article");
    return `<tr class="row" data-id="${t.id}">
      <td class="num">${i + 1}</td>
      <td class="person">
        <div class="name">${t.linkedin_url ? `<a href="${esc(t.linkedin_url)}" target="_blank" rel="noopener">${esc(displayName(t))}</a>` : esc(displayName(t))}</div>
        <div class="sub">${esc([displayTitle(t), displayCompany(t)].filter(Boolean).join(" · "))}</div>
        ${t.location ? `<div class="loc">${esc(t.location)}</div>` : ""}
        ${lowConf ? `<div class="warn" title="${esc(t.identity_notes || "")}">⚠ low identity confidence (${pct(conf)})</div>` : ""}
        ${t.hints ? `<div class="loc" title="From your list">“${esc(t.hints.slice(0, 90))}${t.hints.length > 90 ? "…" : ""}”</div>` : ""}
      </td>
      <td class="email">${renderEmailCell(t, best, others)}</td>
      <td class="research">${renderResearchCell(t, r)}</td>
      <td class="links"><div class="linkrow">${main.map((x) => `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.label)}</a>`).join("")}
        ${articles.slice(0, 3).map((x) => `<a class="article" href="${esc(x.url)}" target="_blank" rel="noopener" title="${esc(x.label)}">↗ ${esc(x.label.slice(0, 28))}${x.label.length > 28 ? "…" : ""}</a>`).join("")}</div></td>
      <td class="status">
        <span class="chip ${cls} ${pulse ? "pulse" : ""}"><span class="dot"></span>${label}</span>
        ${t.status === "error" ? `<div class="err">${esc(t.error || "")}</div>` : ""}
        <div style="margin-top:6px;display:flex;gap:4px">
          <button class="btn btn-sm btn-ghost act-open">Details</button>
          ${pulse ? "" : `<button class="btn btn-sm btn-ghost act-rerun" title="Re-run enrichment">↻</button>`}
        </div>
      </td>
      <td class="outreach">
        <select class="outreach-sel ${t.outreach_status}">
          ${["todo", "drafted", "sent", "replied", "skip"].map((s) => `<option value="${s}" ${s === t.outreach_status ? "selected" : ""}>${s}</option>`).join("")}
        </select>
        ${t.notes ? `<div class="loc" style="margin-top:4px">${esc(t.notes.slice(0, 60))}</div>` : ""}
      </td>
    </tr>`;
  }

  function renderEmailCell(t, best, others) {
    if (!t.emails?.length) {
      if (inProgress(t) && t.status !== "researching") return `<span class="conf">…</span>`;
      if (t.status === "done" || t.status === "researching") {
        const why = t.company_domain ? "No candidates" : "No company domain found";
        return `<span class="conf">${why}</span>`;
      }
      return "";
    }
    const v = VERIF[best?.verification] || VERIF.unknown;
    const note = (t.domain_checks || {}).note;
    return `<div class="mail"><span>${esc(best?.email || "")}</span><button class="copy" title="Copy" data-copy="${esc(best?.email || "")}">⧉</button>
        <span class="chip ${v[1]}" title="${esc(note || "")}">${v[0]} · ${pct(best?.confidence)}</span></div>
      ${others.length ? `<div class="mail-alt">alt: ${others.map((e) => `<a data-copy="${esc(e.email)}" title="Copy">${esc(e.email)}</a> <span class="conf">${pct(e.confidence)}</span>`).join(" · ")}</div>` : ""}
      ${t.email_pattern ? `<div class="conf">pattern ${esc(t.email_pattern)}${best?.source === "found_on_web" ? " · found on web" : best?.source === "hunter" ? " · hunter" : ""}</div>` : ""}`;
  }

  function renderResearchCell(t, r) {
    if (!r || !Object.keys(r).length) {
      return inProgress(t) ? `<span class="conf">…</span>` : "";
    }
    const hooks = (r.hooks || []).slice(0, 3);
    const bio = (r.bio || [])[0] || r.company_summary || "";
    return `${bio ? `<div style="margin-bottom:4px;font-size:12.5px;color:var(--muted)">${esc(bio)}</div>` : ""}
      ${hooks.length ? `<ul class="hooks">${hooks.map((h) => `<li>${esc(h)}</li>`).join("")}</ul>` : ""}
      ${r.caveats ? `<div class="caveat">${esc(r.caveats)}</div>` : ""}`;
  }

  function bindRows() {
    view.querySelectorAll("[data-copy]").forEach((el) => (el.onclick = (e) => { e.stopPropagation(); copy(el.dataset.copy); }));
    view.querySelectorAll(".act-open").forEach((b) => (b.onclick = () => openDrawer(b.closest("tr").dataset.id)));
    view.querySelectorAll(".act-rerun").forEach((b) => (b.onclick = async () => {
      const id = b.closest("tr").dataset.id;
      await api(`/api/targets/${id}/rerun`, { method: "POST" });
      loadList(current.id);
    }));
    view.querySelectorAll(".outreach-sel").forEach((s) => (s.onchange = async () => {
      const id = s.closest("tr").dataset.id;
      await api(`/api/targets/${id}`, { method: "PATCH", body: { outreach_status: s.value } });
      s.className = `outreach-sel ${s.value}`;
      const t = current.targets.find((x) => x.id === id); if (t) t.outreach_status = s.value;
    }));
    view.querySelectorAll("tr.row td.research, tr.row td.person").forEach((td) => (td.onclick = (e) => {
      if (e.target.closest("a, button, select")) return;
      openDrawer(td.closest("tr").dataset.id);
    }));
  }

  // ---- drawer ------------------------------------------------------------
  function closeDrawer() { drawer.classList.add("hidden"); drawer.innerHTML = ""; }
  async function openDrawer(id) {
    let t = current?.targets.find((x) => x.id === id);
    if (!t) t = await api(`/api/targets/${id}`);
    const r = t.research || {};
    const [label, cls] = STATUS[t.status] || [t.status, "chip-muted"];
    const li = (arr) => (arr || []).map((x) => `<li>${esc(x)}</li>`).join("") || "<li class='conf'>—</li>";
    drawer.classList.remove("hidden");
    drawer.innerHTML = `
      <button class="btn btn-sm btn-ghost close" id="d-close">✕</button>
      <h2>${esc(displayName(t))}</h2>
      <div class="sub">${esc([displayTitle(t), displayCompany(t), t.location].filter(Boolean).join(" · "))}</div>
      <div class="toolbar">
        <span class="chip ${cls}">${label}</span>
        ${t.identity_confidence != null ? `<span class="chip ${t.identity_confidence >= 0.7 ? "chip-ok" : t.identity_confidence >= 0.5 ? "chip-warn" : "chip-bad"}" title="${esc(t.identity_notes || "")}">identity ${pct(t.identity_confidence)}</span>` : ""}
        <span class="spacer"></span>
        <button class="btn btn-sm" id="d-rerun">↻ Re-run</button>
        <button class="btn btn-sm btn-ghost btn-danger" id="d-delete">Delete row</button>
      </div>
      ${t.identity_notes ? `<div class="conf" style="margin-top:6px">${esc(t.identity_notes)}</div>` : ""}

      <h4>Links</h4>
      <div class="linkrow">${(t.links || []).map((x) => `<a class="${x.kind === "article" ? "article" : ""}" href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.label)}</a>`).join("") || "<span class='conf'>—</span>"}</div>

      <h4>Email candidates ${t.email_pattern ? `<span class="conf">· pattern ${esc(t.email_pattern)}</span>` : ""}</h4>
      ${(t.domain_checks || {}).note ? `<div class="conf" style="margin-bottom:6px">${esc(t.company_domain || "")} — ${esc(t.domain_checks.note)}</div>` : ""}
      <table class="cands">${(t.emails || []).map((e) => {
        const v = VERIF[e.verification] || VERIF.unknown;
        return `<tr class="${e.email === t.best_email ? "best" : ""}"><td>${esc(e.email)}</td><td>${pct(e.confidence)}</td>
          <td><span class="chip ${v[1]}">${v[0]}</span></td><td class="conf">${esc(e.source)}${e.evidence?.length ? ` · ${e.evidence.map((u) => (/^https?:/.test(u) ? `<a href="${esc(u)}" target="_blank" rel="noopener">src</a>` : esc(u))).join(", ")}` : ""}</td>
          <td><button class="btn btn-sm btn-ghost" data-copy="${esc(e.email)}">copy</button>${e.email !== t.best_email ? `<button class="btn btn-sm btn-ghost d-setbest" data-email="${esc(e.email)}">use</button>` : ""}</td></tr>`;
      }).join("") || "<tr><td class='conf'>No candidates</td></tr>"}</table>

      <h4>Who they are</h4><ul>${li(r.bio)}</ul>
      <h4>Company</h4><div>${esc(r.company_summary || "—")}</div>
      <h4>Recent</h4><ul class="recent">${(r.recent || []).map((x) => `<li>${esc(x.text)} ${x.url ? `<a href="${esc(x.url)}" target="_blank" rel="noopener">↗</a>` : ""} ${x.date ? `<small>${esc(x.date)}</small>` : ""}</li>`).join("") || "<li class='conf'>—</li>"}</ul>
      <h4>Hooks</h4><ul>${li(r.hooks)}</ul>
      <h4>Talking points</h4><ul>${li(r.talking_points)}</ul>
      ${r.caveats ? `<h4>Caveats</h4><div class="caveat" style="color:var(--warn)">${esc(r.caveats)}</div>` : ""}

      <h4>My notes</h4>
      <textarea id="d-notes" placeholder="Anything you want to remember (saved on blur)">${esc(t.notes || "")}</textarea>

      <h4>Inputs (edit, then re-run · domain & LinkedIn are kept on re-run; clear to re-detect)</h4>
      <div class="field-grid">
        <div><label>Name</label><input type="text" id="f-name" value="${esc(t.name)}"></div>
        <div><label>Company</label><input type="text" id="f-company" value="${esc(t.company)}"></div>
        <div><label>Title</label><input type="text" id="f-title" value="${esc(t.title)}"></div>
        <div><label>Company domain</label><input type="text" id="f-domain" value="${esc(t.company_domain || "")}" placeholder="acme.com"></div>
        <div style="grid-column:1/-1"><label>LinkedIn URL</label><input type="text" id="f-linkedin" value="${esc(t.linkedin_url || "")}"></div>
        <div style="grid-column:1/-1"><label>Hints</label><input type="text" id="f-hints" value="${esc(t.hints)}"></div>
      </div>
      <div class="toolbar"><button class="btn btn-sm" id="d-save">Save inputs</button><button class="btn btn-sm btn-primary" id="d-save-rerun">Save & re-run</button></div>
      <h4>Original line</h4><div class="conf">${esc(t.raw_line || "—")}</div>
      ${(t.sources || []).length ? `<h4>Sources consulted</h4><ul>${t.sources.slice(0, 20).map((s) => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title || s.url)}</a></li>`).join("")}</ul>` : ""}
    `;
    $("#d-close").onclick = closeDrawer;
    drawer.querySelectorAll("[data-copy]").forEach((el) => (el.onclick = () => copy(el.dataset.copy)));
    drawer.querySelectorAll(".d-setbest").forEach((b) => (b.onclick = async () => {
      await api(`/api/targets/${t.id}`, { method: "PATCH", body: { best_email: b.dataset.email } });
      await loadList(current.id); openDrawer(t.id);
    }));
    $("#d-notes").onblur = async () => {
      const notes = $("#d-notes").value;
      if (notes !== (t.notes || "")) { await api(`/api/targets/${t.id}`, { method: "PATCH", body: { notes } }); t.notes = notes; toast("Notes saved"); }
    };
    const saveInputs = async () => {
      const body = {
        name: $("#f-name").value.trim(), company: $("#f-company").value.trim(), title: $("#f-title").value.trim(),
        hints: $("#f-hints").value.trim(), company_domain: $("#f-domain").value.trim(), linkedin_url: $("#f-linkedin").value.trim(),
      };
      await api(`/api/targets/${t.id}`, { method: "PATCH", body });
    };
    $("#d-save").onclick = async () => { await saveInputs(); toast("Saved"); loadList(current.id); };
    $("#d-save-rerun").onclick = async () => { await saveInputs(); await api(`/api/targets/${t.id}/rerun`, { method: "POST" }); closeDrawer(); loadList(current.id); };
    $("#d-rerun").onclick = async () => { await api(`/api/targets/${t.id}/rerun`, { method: "POST" }); closeDrawer(); loadList(current.id); };
    $("#d-delete").onclick = async () => {
      if (!confirm(`Remove ${displayName(t)} from this list?`)) return;
      await api(`/api/targets/${t.id}`, { method: "DELETE" }); closeDrawer(); loadList(current.id);
    };
  }

  // ---- boot --------------------------------------------------------------
  loadProviders();
  route();
})();
