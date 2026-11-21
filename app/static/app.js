const state = {
  token: sessionStorage.getItem("eai_token") || "",
  user: null,
  projects: [],
  projectId: sessionStorage.getItem("eai_project") || "",
  conversationId: null,
  lastAnswer: null,
  library: [],
  mentions: [],
  mentionItems: [],
  mentionIndex: 0,
};

const PROMPTS = {
  en: [
    ["What shell-side design pressure applies to HX-2201, and which document governs?", "qa"],
    ["Compare corrosion allowance across the specification, the datasheet, and the vendor offer.", "compare"],
    ["The vendor offers a higher tube-side design pressure. Which value governs?", "compare"],
    ["The channel cover is weeping after a thermal cycle. What should I consider?", "troubleshoot"],
    ["Which TEMA type does the project require, and what does AES mean?", "qa"],
    ["Which edition of ASME Section VIII applies to this exchanger?", "qa"],
  ],
  fa: [
    ["فشار طراحی سمت پوسته برای HX-2201 چقدر است و کدام سند حاکم است؟", "qa"],
    ["اضافه ضخامت خوردگی را بین مشخصات، دیتاشیت و پیشنهاد فروشنده مقایسه کن.", "compare"],
    ["فروشنده فشار طراحی سمت لوله بالاتری پیشنهاد داده است. کدام مقدار حاکم است؟", "compare"],
    ["پوشش کانال بعد از یک چرخه حرارتی نشتی دارد. چه ملاحظاتی را باید ببینم؟", "troubleshoot"],
    ["پروژه چه نوع TEMA می‌خواهد و AES یعنی چه؟", "qa"],
    ["کدام ویرایش ASME Section VIII برای این مبدل حاکم است؟", "qa"],
  ],
};

function $(id) { return document.getElementById(id); }

function setError(name, text) {
  const node = document.querySelector(`.form-error[data-for="${name}"]`);
  if (node) node.textContent = text || "";
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.token) headers.set("Authorization", `Bearer ${state.token}`);
  headers.set("X-Lang", currentLang);
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
    const raw = typeof detail === "string" ? detail : detail && detail.message ? detail.message : response.statusText;
    const error = new Error(translateError(raw) || t("requestFailed"));
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
  window.scrollTo(0, 0);
}

function showAdmin() {
  $("auth").hidden = true;
  $("shell").hidden = true;
  $("admin").hidden = false;
  window.scrollTo(0, 0);
}

function signedIn(token, user) {
  state.token = token;
  state.user = user;
  sessionStorage.setItem("eai_token", token);
  renderUser();
  showApp();
  window.scrollTo(0, 0);
  refreshLibrary();
}

function renderUser() {
  const user = state.user;
  if (!user) return;
  const credits = user.credits || {};
  const label = user.is_anonymous ? t("trialSession") : user.email;
  $("who").textContent = label;
  $("credits").textContent = t("credits", { n: credits.balance ?? "—", plan: user.plan });
  $("open-admin").hidden = user.role !== "admin";
  const locked = user.is_anonymous || user.plan === "trial";
  $("upload-form").hidden = locked;
  $("standard-form").hidden = locked;
  refreshDrive();
}

async function refreshDrive() {
  if (!state.token) return;
  try {
    const status = await api("/api/drive/status");
    state.drive = status;
    const button = $("connect-drive");
    button.hidden = !status.available;
    button.textContent = status.connected ? t("disconnectDrive") : t("connectDrive");
    const hint = $("drive-hint");
    if (hint) hint.hidden = !(status.required && !status.connected);
  } catch {
    /* The library still works when Drive status cannot be read. */
  }
}

async function refreshLibrary() {
  const [projects, kb] = await Promise.all([api("/api/projects"), api("/api/kb/documents")]);
  state.projects = projects.projects;
  const select = $("project");
  select.innerHTML = "";
  const global = document.createElement("option");
  global.value = "";
  global.textContent = t("globalOnly");
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
  const globalDocs = kbDocuments.map((doc) => ({ ...doc, scope: doc.scope || "global" }));
  for (const doc of globalDocs) kb.appendChild(docItem(doc, false));
  const standards = $("standard-docs");
  const list = $("project-docs");
  standards.innerHTML = "";
  list.innerHTML = "";
  if (!state.projectId) {
    standards.innerHTML = `<li><span>${t("selectProject")}</span></li>`;
    list.innerHTML = `<li><span>${t("selectProject")}</span></li>`;
    state.library = globalDocs;
    return;
  }
  const data = await api(`/api/projects/${state.projectId}/documents`);
  const projectDocs = data.documents.filter((doc) => doc.doc_type !== "standard");
  const standardDocs = data.documents.filter((doc) => doc.doc_type === "standard");
  state.library = [...standardDocs, ...projectDocs, ...globalDocs];
  if (!standardDocs.length) standards.innerHTML = `<li><span>${t("noStandards")}</span></li>`;
  for (const doc of standardDocs) standards.appendChild(docItem(doc, true));
  if (!projectDocs.length) list.innerHTML = `<li><span>${t("noProjectFiles")}</span></li>`;
  for (const doc of projectDocs) list.appendChild(docItem(doc, true));
}

function docItem(doc, canDelete) {
  const li = document.createElement("li");
  const strong = document.createElement("strong");
  strong.textContent = doc.title;
  const meta = document.createElement("span");
  const edition = doc.edition ? `${t("edition")} ${doc.edition}` : "";
  const rev = doc.doc_type === "standard"
    ? (doc.revision ? `${t("partDivision")} ${doc.revision}` : "")
    : (doc.revision ? `${t("revisionWord")} ${doc.revision}` : "");
  meta.textContent = [doc.doc_type, edition, rev, doc.filename].filter(Boolean).join(" · ");
  const actions = document.createElement("div");
  actions.className = "doc-actions";
  const mention = document.createElement("button");
  mention.type = "button";
  mention.className = "ghost small";
  mention.textContent = t("mention");
  mention.addEventListener("click", () => insertMention(doc));
  actions.appendChild(mention);
  if (canDelete) {
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "ghost small";
    remove.textContent = t("deleteDoc");
    remove.addEventListener("click", () => deleteDocument(doc));
    actions.appendChild(remove);
  }
  if (doc.storage === "temporary") {
    const badge = document.createElement("span");
    badge.textContent = t("temporaryFile");
    li.appendChild(badge);
  }
  if (doc.status === "source_missing") {
    const badge = document.createElement("span");
    badge.textContent = t("sourceMissing");
    li.appendChild(badge);
  }
  li.append(strong, meta, actions);
  return li;
}

function mentionToken(doc) {
  const source = `${doc.title || ""} ${doc.edition || ""}`.trim();
  const latin = source.replace(/[^A-Za-z0-9]+/g, "-").replace(/^-|-$/g, "");
  const base = latin.length >= 3 ? latin : (doc.title || doc.filename || "file").replace(/\s+/g, "-");
  return base.slice(0, 48);
}

function foldMatch(value) {
  return (value || "")
    .replace(/[يى]/g, "ی")
    .replace(/ك/g, "ک")
    .replace(/\u200c/g, " ")
    .replace(/[۰-۹]/g, (digit) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(digit)))
    .replace(/[٠-٩]/g, (digit) => String("٠١٢٣٤٥٦٧٨٩".indexOf(digit)))
    .toLowerCase();
}

function activeMention() {
  const box = $("question");
  const pos = box.selectionStart;
  const before = box.value.slice(0, pos);
  const at = before.lastIndexOf("@");
  if (at < 0) return null;
  if (at > 0 && !/\s/.test(before[at - 1])) return null;
  const query = before.slice(at + 1);
  if (query.includes("\n") || query.length > 60) return null;
  return { at, query, pos };
}

function closeMention() {
  $("mention-menu").hidden = true;
  state.mentionItems = [];
  state.mentionIndex = 0;
}

function renderMentionMenu(items) {
  const menu = $("mention-menu");
  menu.innerHTML = "";
  state.mentionItems = items;
  if (!items.length) {
    menu.hidden = true;
    return;
  }
  state.mentionIndex = Math.min(state.mentionIndex, items.length - 1);
  items.forEach((doc, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", index === state.mentionIndex ? "true" : "false");
    const edition = doc.edition ? ` · ${doc.edition}` : "";
    button.textContent = `${doc.title}${edition} — ${doc.filename}`;
    button.addEventListener("mousedown", (event) => {
      event.preventDefault();
      insertMention(doc);
    });
    menu.appendChild(button);
  });
  menu.hidden = false;
}

function filterMentions(query) {
  const needle = foldMatch(query.trim());
  return state.library.filter((doc) => {
    const haystack = foldMatch(`${doc.title} ${doc.filename} ${doc.edition} ${doc.revision}`);
    return !needle || haystack.includes(needle);
  }).slice(0, 8);
}

function insertMention(doc) {
  const token = mentionToken(doc);
  if (!state.mentions.some((item) => item.id === doc.id)) {
    state.mentions.push({ id: doc.id, token, title: doc.title });
  }
  const box = $("question");
  const found = activeMention();
  if (found) {
    box.value = `${box.value.slice(0, found.at)}@${token} ${box.value.slice(found.pos)}`;
  } else if (!box.value.includes(`@${token}`)) {
    const gap = box.value && !/\s$/.test(box.value) ? " " : "";
    box.value = `${box.value}${gap}@${token} `;
  }
  closeMention();
  renderChips();
  box.focus();
}

function renderChips() {
  const host = $("mention-chips");
  host.innerHTML = "";
  for (const item of state.mentions) {
    const chip = document.createElement("span");
    chip.className = "mention-chip";
    chip.textContent = `@${item.token}`;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.setAttribute("aria-label", t("removeMention"));
    remove.textContent = "×";
    remove.addEventListener("click", () => {
      state.mentions = state.mentions.filter((row) => row.id !== item.id);
      renderChips();
    });
    chip.appendChild(remove);
    host.appendChild(chip);
  }
}

async function deleteDocument(doc) {
  if (!state.projectId || !window.confirm(t("confirmDelete"))) return;
  await api(`/api/projects/${state.projectId}/documents/${doc.id}`, { method: "DELETE" });
  state.mentions = state.mentions.filter((item) => item.id !== doc.id);
  renderChips();
  const kb = await api("/api/kb/documents");
  await renderDocs(kb.documents);
}

function renderPrompts() {
  const host = $("prompts");
  host.innerHTML = "";
  for (const [text, mode] of PROMPTS[currentLang] || PROMPTS.en) {
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
  node.dir = hasPersian(text) ? "rtl" : "ltr";
  node.textContent = text;
  $("messages").appendChild(node);
  node.scrollIntoView({ block: "end" });
}

function addAnswer(answer) {
  state.lastAnswer = answer;
  const node = document.createElement("article");
  node.className = "bubble assistant";
  const answerFa = answer.answer_language === "fa" || (answer.blocks || []).some((block) => hasPersian(block.text));
  node.dir = answerFa ? "rtl" : "ltr";
  const mode = document.createElement("p");
  mode.className = "meta";
  mode.textContent = `${t(answer.mode) || answer.mode} · ${answer.generator === "llm" ? t("llmNote") : t("extractiveNote")}`;
  node.appendChild(mode);
  for (const block of answer.blocks || []) {
    const wrap = document.createElement("div");
    wrap.className = `block ${block.kind}`;
    const kind = document.createElement("div");
    kind.className = `kind ${block.kind}`;
    kind.textContent = t(block.kind) || block.kind;
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
    host.innerHTML = `<p class="empty">${t("noCitation")}</p>`;
    return;
  }
  for (const conflict of conflicts) {
    const card = document.createElement("article");
    card.className = "conflict";
    const gov = conflict.governing || {};
    card.innerHTML = `<header><strong></strong><span class="badge"></span></header><p></p><p class="meta"></p>`;
    card.querySelector("strong").textContent = currentLang === "fa" && conflict.label_fa ? conflict.label_fa : conflict.label;
    const badge = card.querySelector(".badge");
    badge.textContent = t(conflict.status) || conflict.status;
    badge.classList.add(conflict.status);
    card.querySelector("p").textContent = `${conflict.why || ""} ${conflict.implication || ""}`;
    const lines = (conflict.observed || []).map((item) => `${t(item.role) || item.role}: ${item.value} — ${item.document} ${t("revisionWord")} ${item.revision || "—"}, ${item.clause || t("clause")} ${t("page")} ${item.page || "—"}`);
    card.querySelector(".meta").textContent = `${t("governing")}: ${gov.value || "—"} — ${gov.document || "—"}. ${lines.join(" · ")}`;
    host.appendChild(card);
  }
  for (const citation of answer.citations || []) {
    const card = document.createElement("article");
    card.className = "citation";
    card.id = `cit-${citation.citation_id}`;
    card.innerHTML = `<header><strong></strong><span class="badge"></span></header><p class="meta"></p><p class="excerpt"></p>`;
    card.querySelector("strong").textContent = `${citation.citation_id} · ${citation.source_document}`;
    const badge = card.querySelector(".badge");
    badge.textContent = t(citation.statement_class) || citation.statement_label || citation.statement_class;
    badge.classList.add(citation.statement_class);
    const rev = citation.revision ? `${t("revisionWord")} ${citation.revision}` : "";
    const edition = citation.edition ? `${t("edition")} ${citation.edition}` : "";
    card.querySelector(".meta").textContent = `${citation.source_file} · ${t("clause")} ${citation.clause || citation.section || "—"} · ${t("page")} ${citation.page || "—"} · ${rev} ${edition} · ${citation.store}`;
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

$("connect-drive").addEventListener("click", async () => {
  if (state.drive && state.drive.connected) {
    await api("/api/drive/disconnect", { method: "POST" });
    await refreshDrive();
    return;
  }
  const result = await api("/api/drive/connect");
  if (result.url) window.location = result.url;
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
  state.mentions = [];
  renderChips();
  closeMention();
  sessionStorage.setItem("eai_project", state.projectId);
  $("messages").innerHTML = "";
  $("evidence-body").innerHTML = `<p class="empty">${t("nextEvidence")}</p>`;
  api("/api/kb/documents").then((kb) => renderDocs(kb.documents));
});

async function submitUpload(event, errorName, extra) {
  event.preventDefault();
  setError(errorName, "");
  if (!state.projectId) {
    setError(errorName, t("uploadNeedProject"));
    return;
  }
  const form = new FormData(event.target);
  for (const [key, value] of Object.entries(extra || {})) form.set(key, value);
  try {
    await api(`/api/projects/${state.projectId}/documents`, { method: "POST", body: form });
    event.target.reset();
    const kb = await api("/api/kb/documents");
    await renderDocs(kb.documents);
  } catch (error) {
    setError(errorName, error.message);
  }
}

$("upload-form").addEventListener("submit", (event) => submitUpload(event, "upload"));
$("standard-form").addEventListener("submit", (event) => submitUpload(event, "standard", { doc_type: "standard" }));

$("question").addEventListener("input", () => {
  const found = activeMention();
  if (!found) {
    closeMention();
    return;
  }
  state.mentionIndex = 0;
  renderMentionMenu(filterMentions(found.query));
});

$("question").addEventListener("keydown", (event) => {
  const menu = $("mention-menu");
  if (menu.hidden) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeMention();
    return;
  }
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    const step = event.key === "ArrowDown" ? 1 : -1;
    const count = state.mentionItems.length;
    if (!count) return;
    state.mentionIndex = (state.mentionIndex + step + count) % count;
    renderMentionMenu(state.mentionItems);
    return;
  }
  if (event.key === "Enter" || event.key === "Tab") {
    const doc = state.mentionItems[state.mentionIndex];
    if (!doc) return;
    event.preventDefault();
    insertMention(doc);
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
        document_ids: state.mentions.map((item) => item.id),
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
    add.textContent = t("topUp");
    add.addEventListener("click", async () => {
      await api(`/api/admin/users/${user.id}/credits`, { method: "POST", json: { amount: Number(amount.value), mode: "topup" } });
      await loadAdmin();
    });
    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "ghost small";
    reset.textContent = t("resetMonth");
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
      button.textContent = t("revoke");
      button.addEventListener("click", async () => {
        await api(`/api/admin/codes/${code.id}/revoke`, { method: "POST" });
        await loadAdmin();
      });
      li.appendChild(button);
    }
    codeList.appendChild(li);
  }
  $("usage").textContent = (usage.totals || []).map((row) => `${row.kind}: ${row.events} events, ${row.credits} credits`).join("\n") || t("noUsage");
  $("billing-state").textContent = billing.enabled ? t("stripeOn") : t("stripeOff");
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

window.onUiLang = () => {
  renderPrompts();
  renderUser();
  document.querySelectorAll(".kind").forEach((node) => {
    const kind = [...node.classList].find((name) => name !== "kind");
    if (kind) node.textContent = t(kind);
  });
  if (state.lastAnswer) renderEvidence(state.lastAnswer);
};

boot();
