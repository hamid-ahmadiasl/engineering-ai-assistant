const state = {
  token: sessionStorage.getItem("eai_token") || "",
  user: null,
  projects: [],
  projectId: sessionStorage.getItem("eai_project") || "",
  conversationId: null,
  lastAnswer: null,
};

const PROMPTS = [
  ["What shell-side design pressure applies to HX-2201, and which document governs?", "qa"],
  ["Compare corrosion allowance across the specification, the datasheet, and the vendor offer.", "compare"],
  ["The vendor offers a higher tube-side design pressure. Which value governs?", "compare"],
  ["The channel cover is weeping after a thermal cycle. What should I consider?", "troubleshoot"],
  ["Which TEMA type does the project require, and what does AES mean?", "qa"],
  ["Which edition of ASME Section VIII applies to this exchanger?", "qa"],
];

const BLOCK_LABEL = {
  explicit_requirement: "Explicit requirement",
  engineering_recommendation: "Engineering recommendation",
  ai_interpretation: "AI interpretation",
};

function $(id) { return document.getElementById(id); }

function setError(name, text) {
  const node = document.querySelector(`.form-error[data-for="${name}"]`);
  if (node) node.textContent = text || "";
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.token) headers.set("Authorization", `Bearer ${state.token}`);
  if (options.json) {
    headers.set("Content-Type", "application/json");
    options.body = JSON.stringify(options.json);
  }
  const response = await fetch(path, { ...options, headers });
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
  if (!response.ok) {
    const detail = data && data.detail;
    const message = typeof detail === "string" ? detail : detail && detail.message ? detail.message : response.statusText;
    const error = new Error(message || "Request failed");
    error.status = response.status;
    error.payload = data;
    throw error;
  }
  return data;
}

function showAuth() {
  $("auth").hidden = false;
  $("shell").hidden = true;
  $("admin").hidden = true;
}

function showApp() {
  $("auth").hidden = true;
  $("shell").hidden = false;
  $("admin").hidden = true;
}

function showAdmin() {
  $("auth").hidden = true;
  $("shell").hidden = true;
  $("admin").hidden = false;
}

function signedIn(token, user) {
  state.token = token;
  state.user = user;
  sessionStorage.setItem("eai_token", token);
  renderUser();
  showApp();
  refreshLibrary();
}

function renderUser() {
  const user = state.user;
  if (!user) return;
  const credits = user.credits || {};
  const label = user.is_anonymous ? "Trial session" : user.email;
  $("who").textContent = label;
  $("credits").textContent = `${credits.balance ?? "—"} credits · ${user.plan}`;
  $("open-admin").hidden = user.role !== "admin";
  const upload = $("upload-form");
  upload.hidden = user.is_anonymous || user.plan === "trial";
}

async function refreshLibrary() {
  const [projects, kb] = await Promise.all([api("/api/projects"), api("/api/kb/documents")]);
  state.projects = projects.projects;
  const select = $("project");
  select.innerHTML = "";
  const global = document.createElement("option");
  global.value = "";
  global.textContent = "Global knowledge only";
  select.appendChild(global);
  for (const project of state.projects) {
    const option = document.createElement("option");
    option.value = project.id;
    option.textContent = `${project.code} — ${project.name}`;
    select.appendChild(option);
  }
  if (!state.projects.some((p) => p.id === state.projectId)) {
    const demo = state.projects.find((p) => p.code === "HX-2201");
    state.projectId = demo ? demo.id : "";
  }
  select.value = state.projectId;
  sessionStorage.setItem("eai_project", state.projectId);
  renderDocs(kb.documents);
}

async function renderDocs(kbDocuments) {
  const kb = $("kb-docs");
  kb.innerHTML = "";
  for (const doc of kbDocuments) kb.appendChild(docItem(doc));
  const list = $("project-docs");
  list.innerHTML = "";
  if (!state.projectId) {
    list.innerHTML = `<li><span>Select a project to see its files. Global notes stay available.</span></li>`;
    return;
  }
  const data = await api(`/api/projects/${state.projectId}/documents`);
  if (!data.documents.length) {
    list.innerHTML = `<li><span>No project files yet.</span></li>`;
    return;
  }
  for (const doc of data.documents) list.appendChild(docItem(doc));
}

function docItem(doc) {
  const li = document.createElement("li");
  const rev = doc.revision ? `Rev ${doc.revision}` : "No revision";
  const edition = doc.edition ? ` · ${doc.edition}` : "";
  li.innerHTML = `<strong></strong><span></span>`;
  li.querySelector("strong").textContent = doc.title;
  li.querySelector("span").textContent = `${doc.doc_type} · ${rev}${edition} · ${doc.filename}`;
  return li;
}

function renderPrompts() {
  const host = $("prompts");
  host.innerHTML = "";
  for (const [text, mode] of PROMPTS) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = text;
    button.addEventListener("click", () => {
      $("question").value = text;
      document.querySelector(`input[name="mode"][value="${mode}"]`).checked = true;
      $("composer").requestSubmit();
    });
    host.appendChild(button);
  }
}

function addUserBubble(text) {
  const node = document.createElement("div");
  node.className = "bubble user";
  node.textContent = text;
  $("messages").appendChild(node);
  node.scrollIntoView({ block: "end" });
}

function addAnswer(answer) {
  state.lastAnswer = answer;
  const node = document.createElement("article");
  node.className = "bubble assistant";
  const mode = document.createElement("p");
  mode.className = "meta";
  mode.textContent = `${answer.mode} · ${answer.generator === "llm" ? "language model, grounded on the excerpts" : "extractive, quoted from the excerpts"}`;
  node.appendChild(mode);
  for (const block of answer.blocks || []) {
    const wrap = document.createElement("div");
    wrap.className = `block ${block.kind}`;
    const kind = document.createElement("div");
    kind.className = `kind ${block.kind}`;
    kind.textContent = BLOCK_LABEL[block.kind] || block.kind;
    const text = document.createElement("div");
    text.textContent = block.text;
    wrap.appendChild(kind);
    wrap.appendChild(text);
    const cites = document.createElement("div");
    for (const cid of block.citation_ids || []) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "cite-chip";
      chip.textContent = cid;
      chip.addEventListener("click", () => focusCitation(cid));
      cites.appendChild(chip);
    }
    wrap.appendChild(cites);
    node.appendChild(wrap);
  }
  if ((answer.limitations || []).length) {
    const limits = document.createElement("div");
    limits.className = "limitations";
    for (const item of answer.limitations) {
      const p = document.createElement("p");
      p.textContent = item;
      limits.appendChild(p);
    }
    node.appendChild(limits);
  }
  $("messages").appendChild(node);
  node.scrollIntoView({ block: "end" });
  renderEvidence(answer);
  if (answer.credits) {
    state.user.credits = answer.credits;
    renderUser();
  }
}

function renderEvidence(answer) {
  const host = $("evidence-body");
  host.innerHTML = "";
  const conflicts = answer.conflicts || [];
  if (!conflicts.length && !(answer.citations || []).length) {
    host.innerHTML = `<p class="empty">No citation was returned.</p>`;
    return;
  }
  for (const conflict of conflicts) {
    const card = document.createElement("article");
    card.className = "conflict";
    const gov = conflict.governing || {};
    card.innerHTML = `<header><strong></strong><span class="badge"></span></header><p></p><p class="meta"></p>`;
    card.querySelector("strong").textContent = conflict.label;
    const badge = card.querySelector(".badge");
    badge.textContent = conflict.status;
    badge.classList.add(conflict.status);
    card.querySelector("p").textContent = `${conflict.why || ""} ${conflict.implication || ""}`;
    const lines = (conflict.observed || []).map((item) => `${item.role}: ${item.value} — ${item.document} rev ${item.revision || "—"}, ${item.clause || "section"} p.${item.page || "—"}`);
    card.querySelector(".meta").textContent = `Governing: ${gov.value || "—"} in ${gov.document || "—"}. ${lines.join(" · ")}`;
    host.appendChild(card);
  }
  for (const citation of answer.citations || []) {
    const card = document.createElement("article");
    card.className = "citation";
    card.id = `cit-${citation.citation_id}`;
    card.innerHTML = `<header><strong></strong><span class="badge"></span></header><p class="meta"></p><p class="excerpt"></p>`;
    card.querySelector("strong").textContent = `${citation.citation_id} · ${citation.source_document}`;
    const badge = card.querySelector(".badge");
    badge.textContent = citation.statement_label || citation.statement_class;
    badge.classList.add(citation.statement_class);
    const rev = citation.revision ? `rev ${citation.revision}` : "revision not stated";
    const edition = citation.edition ? `, edition ${citation.edition}` : "";
    card.querySelector(".meta").textContent = `${citation.source_file} · clause ${citation.clause || citation.section || "—"} · page ${citation.page || "—"} · ${rev}${edition} · ${citation.store}`;
    card.querySelector(".excerpt").textContent = citation.excerpt;
    if (citation.corpus_label) {
      const note = document.createElement("p");
      note.className = "meta";
      note.textContent = citation.corpus_label;
      card.appendChild(note);
    }
    host.appendChild(card);
  }
}

function focusCitation(cid) {
  const node = document.getElementById(`cit-${cid}`);
  if (!node) return;
  document.querySelectorAll(".citation.active").forEach((el) => el.classList.remove("active"));
  node.classList.add("active");
  node.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function boot() {
  renderPrompts();
  if (!state.token) {
    showAuth();
    return;
  }
  try {
    state.user = await api("/api/me");
    renderUser();
    showApp();
    await refreshLibrary();
  } catch {
    sessionStorage.removeItem("eai_token");
    state.token = "";
    showAuth();
  }
}

$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  setError("login", "");
  const data = Object.fromEntries(new FormData(event.target));
  try {
    const result = await api("/api/auth/login", { method: "POST", json: data });
    signedIn(result.token, result.user);
  } catch (error) {
    setError("login", error.message);
  }
});

$("register-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  setError("register", "");
  const data = Object.fromEntries(new FormData(event.target));
  try {
    const result = await api("/api/auth/register", { method: "POST", json: data });
    signedIn(result.token, result.user);
  } catch (error) {
    setError("register", error.message);
  }
});

$("trial").addEventListener("click", async () => {
  try {
    const result = await api("/api/auth/trial", { method: "POST" });
    signedIn(result.token, result.user);
  } catch (error) {
    setError("login", error.message);
  }
});

$("logout").addEventListener("click", () => {
  sessionStorage.removeItem("eai_token");
  state.token = "";
  state.user = null;
  showAuth();
});

$("project").addEventListener("change", () => {
  state.projectId = $("project").value;
  state.conversationId = null;
  sessionStorage.setItem("eai_project", state.projectId);
  $("messages").innerHTML = "";
  $("evidence-body").innerHTML = `<p class="empty">Citations for the next answer will land here.</p>`;
  api("/api/kb/documents").then((kb) => renderDocs(kb.documents));
});

$("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  setError("upload", "");
  if (!state.projectId) {
    setError("upload", "Select a project before uploading.");
    return;
  }
  const form = new FormData(event.target);
  try {
    await api(`/api/projects/${state.projectId}/documents`, { method: "POST", body: form });
    event.target.reset();
    const kb = await api("/api/kb/documents");
    await renderDocs(kb.documents);
  } catch (error) {
    setError("upload", error.message);
  }
});

$("composer").addEventListener("submit", async (event) => {
  event.preventDefault();
  setError("chat", "");
  const message = $("question").value.trim();
  if (!message) return;
  const mode = document.querySelector('input[name="mode"]:checked').value;
  addUserBubble(message);
  $("send").disabled = true;
  try {
    const answer = await api("/api/chat", {
      method: "POST",
      json: {
        message,
        mode,
        project_id: state.projectId || null,
        conversation_id: state.conversationId,
      },
    });
    state.conversationId = answer.conversation_id;
    addAnswer(answer);
    $("question").value = "";
  } catch (error) {
    setError("chat", error.message);
  } finally {
    $("send").disabled = false;
  }
});

$("open-admin").addEventListener("click", async () => {
  showAdmin();
  await loadAdmin();
});
$("close-admin").addEventListener("click", () => showApp());

async function loadAdmin() {
  const [users, codes, usage, billing] = await Promise.all([
    api("/api/admin/users"),
    api("/api/admin/codes"),
    api("/api/admin/usage"),
    api("/api/billing/status"),
  ]);
  const host = $("users");
  host.innerHTML = "";
  for (const user of users.users) {
    const row = document.createElement("div");
    row.className = "user-row";
    const name = document.createElement("div");
    name.textContent = `${user.email} · ${user.role}${user.is_anonymous ? " · trial" : ""}`;
    const plan = document.createElement("select");
    for (const value of ["free", "pro", "trial", "admin"]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      if (value === user.plan) option.selected = true;
      plan.appendChild(option);
    }
    plan.addEventListener("change", async () => {
      await api(`/api/admin/users/${user.id}/plan`, { method: "POST", json: { plan: plan.value } });
      await loadAdmin();
    });
    const balance = document.createElement("div");
    balance.textContent = `${user.credits.balance} left`;
    const actions = document.createElement("div");
    actions.className = "row-actions";
    const amount = document.createElement("input");
    amount.type = "number";
    amount.value = "20";
    amount.style.width = "70px";
    const add = document.createElement("button");
    add.type = "button";
    add.className = "ghost small";
    add.textContent = "Top up";
    add.addEventListener("click", async () => {
      await api(`/api/admin/users/${user.id}/credits`, { method: "POST", json: { amount: Number(amount.value), mode: "topup" } });
      await loadAdmin();
    });
    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "ghost small";
    reset.textContent = "Reset month";
    reset.addEventListener("click", async () => {
      await api(`/api/admin/users/${user.id}/credits`, { method: "POST", json: { amount: 0, mode: "reset" } });
      await loadAdmin();
    });
    actions.append(amount, add, reset);
    row.append(name, plan, balance, actions);
    host.appendChild(row);
  }
  const codeList = $("codes");
  codeList.innerHTML = "";
  for (const code of codes.codes) {
    const li = document.createElement("li");
    li.textContent = `${code.code} · ${code.credit_amount} credits · ${code.uses}/${code.max_uses}${code.revoked ? " · revoked" : ""}`;
    if (!code.revoked) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "ghost small";
      button.textContent = "Revoke";
      button.addEventListener("click", async () => {
        await api(`/api/admin/codes/${code.id}/revoke`, { method: "POST" });
        await loadAdmin();
      });
      li.appendChild(button);
    }
    codeList.appendChild(li);
  }
  $("usage").textContent = (usage.totals || []).map((row) => `${row.kind}: ${row.events} events, ${row.credits} credits`).join("\n") || "No usage yet.";
  $("billing-state").textContent = billing.enabled ? "Stripe checkout is enabled." : "Stripe checkout is disabled.";
}

$("code-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  setError("code", "");
  const data = Object.fromEntries(new FormData(event.target));
  data.credit_amount = Number(data.credit_amount || 0);
  data.max_uses = Number(data.max_uses || 1);
  data.expires_in_days = data.expires_in_days ? Number(data.expires_in_days) : null;
  data.plan = data.plan || null;
  data.grants_signup = true;
  try {
    const code = await api("/api/admin/codes", { method: "POST", json: data });
    const box = $("new-code");
    box.hidden = false;
    box.textContent = code.code;
    await loadAdmin();
  } catch (error) {
    setError("code", error.message);
  }
});

boot();
