const state = {
  token: sessionStorage.getItem("eai_token") || "",
  user: null,
  projects: [],
  projectId: sessionStorage.getItem("eai_project") || "",
  conversationId: null,
  scopes: JSON.parse(localStorage.getItem("eai_scopes") || "null") || { global: true, projectIds: [], fresh: true },
  editingProject: null,
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
  $("library-form").hidden = locked;
  $("new-project").hidden = locked;
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
    const pill = $("drive-pill");
    if (pill) {
      pill.hidden = !status.available;
      pill.textContent = status.connected ? t("driveOn") : t("driveOff");
      pill.classList.toggle("on", !!status.connected);
    }
    const hint = $("drive-hint");
    if (hint) hint.hidden = !(status.required && !status.connected);
  } catch {
    /* The library still works when Drive status cannot be read. */
  }
}

function projectCaption(project) {
  const code = project.code || "";
  let name = (project.name || "").trim();
  if (name.toLowerCase().startsWith(code.toLowerCase())) {
    name = name.slice(code.length).replace(/^[\s—\-–:]+/, "").trim();
  }
  return name ? `${code} — ${name}` : code;
}

function scopeIcon(path) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", "14");
  svg.setAttribute("height", "14");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.8");
  const node = document.createElementNS("http://www.w3.org/2000/svg", "path");
  node.setAttribute("d", path);
  svg.appendChild(node);
  return svg;
}

function scopeRow({ checked, text, onToggle, actions }) {
  const row = document.createElement("div");
  row.className = "scope-row";
  const label = document.createElement("label");
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = checked;
  input.addEventListener("change", onToggle);
  const span = document.createElement("span");
  span.className = "scope-text";
  span.textContent = text;
  span.title = text;
  label.append(input, span);
  row.appendChild(label);
  row.addEventListener("click", (event) => {
    if (event.target.closest(".scope-actions") || event.target.closest("label")) return;
    input.click();
  });
  if (actions) {
    const box = document.createElement("div");
    box.className = "scope-actions";
    const rename = document.createElement("button");
    rename.type = "button";
    rename.className = "icon-btn";
    rename.title = t("renameProject");
    rename.setAttribute("aria-label", t("renameProject"));
    rename.appendChild(scopeIcon("M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"));
    rename.addEventListener("click", (event) => {
      event.stopPropagation();
      openProjectModal(actions);
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "icon-btn";
    remove.title = t("deleteProject");
    remove.setAttribute("aria-label", t("deleteProject"));
    remove.appendChild(scopeIcon("M4 7h16M9 7V5h6v2m-8 0 1 13h8l1-13"));
    remove.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteProject(actions);
    });
    box.append(rename, remove);
    row.appendChild(box);
  }
  return row;
}

function placeScopeMenu() {
  const button = $("scope-button");
  const menu = $("scope-menu");
  if (!button || !menu || menu.hidden) return;
  if (menu.parentElement !== document.body) document.body.appendChild(menu);
  const rect = button.getBoundingClientRect();
  const width = Math.min(340, window.innerWidth - 16);
  menu.style.top = `${Math.min(rect.bottom + 6, window.innerHeight - 16)}px`;
  menu.style.width = `${Math.max(rect.width, Math.min(width, 320))}px`;
  const rtl = document.documentElement.dir === "rtl";
  if (rtl) {
    menu.style.left = "auto";
    menu.style.right = `${Math.max(8, window.innerWidth - rect.right)}px`;
  } else {
    menu.style.right = "auto";
    menu.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - width - 8))}px`;
  }
}

function selectedProjects() {
  const ids = new Set(state.scopes.projectIds);
  return state.projects.filter((project) => ids.has(project.id));
}

function saveScopes() {
  const known = new Set(state.projects.map((project) => project.id));
  state.scopes.projectIds = state.scopes.projectIds.filter((id) => known.has(id));
  if (!state.scopes.global && !state.scopes.projectIds.length) state.scopes.global = true;
  localStorage.setItem("eai_scopes", JSON.stringify(state.scopes));
  state.projectId = state.scopes.projectIds[0] || "";
  renderScope();
}

function toggleGlobal() {
  if (state.scopes.global && !state.scopes.projectIds.length) {
    renderScope();
    return;
  }
  state.scopes.global = !state.scopes.global;
  saveScopes();
  refreshLibrary();
}

function toggleProject(id) {
  const ids = new Set(state.scopes.projectIds);
  if (ids.has(id)) ids.delete(id);
  else ids.add(id);
  state.scopes.projectIds = [...ids];
  saveScopes();
  refreshLibrary();
}

function renderScope() {
  const chips = $("scope-chips");
  const menu = $("scope-menu");
  if (!chips || !menu) return;
  chips.innerHTML = "";
  const addChip = (label, onRemove) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", onRemove);
    chips.appendChild(button);
  };
  if (state.scopes.global) addChip(t("generalChip"), toggleGlobal);
  for (const project of selectedProjects()) addChip(project.code, () => toggleProject(project.id));
  menu.innerHTML = "";
  menu.appendChild(scopeRow({
    checked: state.scopes.global,
    text: t("generalKnowledge"),
    onToggle: toggleGlobal,
  }));
  for (const project of state.projects) {
    const text = projectCaption(project);
    menu.appendChild(scopeRow({
      checked: state.scopes.projectIds.includes(project.id),
      text,
      onToggle: () => toggleProject(project.id),
      actions: project.role === "owner" || project.role === "admin" ? project : null,
    }));
  }
  const empty = !state.projects.length;
  $("no-projects").hidden = !empty;
  const chatEmpty = $("chat-empty-project");
  if (chatEmpty) chatEmpty.hidden = !empty;
  $("general-library").hidden = !state.scopes.global;
  $("standards-section").hidden = !state.scopes.projectIds.length;
  $("documents-section").hidden = !state.scopes.projectIds.length;
  $("scope-button").textContent = chips.children.length ? t("chooseScopes") : t("chooseScopes");
}

async function refreshLibrary() {
  const [projects, kb] = await Promise.all([api("/api/projects"), api("/api/kb/documents")]);
  state.projects = projects.projects;
  if (state.scopes.fresh) {
    const demo = state.projects.find((project) => project.code === "HX-2201");
    if (demo && !state.scopes.projectIds.length) state.scopes.projectIds = [demo.id];
    delete state.scopes.fresh;
  }
  saveScopes();
  await renderDocs(kb.documents);
}

async function renderDocs(kbDocuments) {
  const kb = $("kb-docs");
  kb.innerHTML = "";
  const globalDocs = state.scopes.global ? kbDocuments.map((doc) => ({ ...doc, scope: doc.scope || "global" })) : [];
  for (const doc of globalDocs) kb.appendChild(docItem(doc, false));
  const libraryHost = $("library-docs");
  libraryHost.innerHTML = "";
  let personal = [];
  if (state.scopes.global && state.user && !state.user.is_anonymous) {
    personal = (await api("/api/library/documents")).documents.map((doc) => ({ ...doc, scope: "personal" }));
    if (!personal.length) libraryHost.innerHTML = `<li><span>${t("noProjectFiles")}</span></li>`;
    for (const doc of personal) libraryHost.appendChild(docItem(doc, true));
  }
  const standards = $("standard-docs");
  const list = $("project-docs");
  standards.innerHTML = "";
  list.innerHTML = "";
  const chosen = selectedProjects();
  if (!chosen.length) {
    state.library = [...personal, ...globalDocs];
    return;
  }
  const projectDocs = [];
  const standardDocs = [];
  for (const project of chosen) {
    const data = await api(`/api/projects/${project.id}/documents`);
    for (const doc of data.documents) {
      const labeled = chosen.length > 1 ? { ...doc, title: `${project.code} · ${doc.title}` } : doc;
      if (doc.doc_type === "standard") standardDocs.push(labeled);
      else projectDocs.push(labeled);
    }
  }
  state.library = [...standardDocs, ...projectDocs, ...personal, ...globalDocs];
  if (!standardDocs.length) standards.innerHTML = `<li><span>${t("noStandards")}</span></li>`;
  for (const doc of standardDocs) standards.appendChild(docItem(doc, true));
  if (!projectDocs.length) list.innerHTML = `<li><span>${t("noProjectFiles")}</span></li>`;
  for (const doc of projectDocs) list.appendChild(docItem(doc, true));
}

function docItem(doc, canDelete) {
  const li = document.createElement("li");
  const icon = document.createElement("span");
  icon.className = "doc-ico";
  icon.textContent = doc.doc_type === "standard" ? "§" : "▣";
  const body = document.createElement("div");
  const strong = document.createElement("strong");
  strong.textContent = doc.title;
  if (doc.edition) {
    const edition = document.createElement("span");
    edition.className = "edition-badge";
    edition.textContent = doc.edition;
    strong.appendChild(edition);
  }
  const meta = document.createElement("span");
  const editionText = doc.edition ? `${t("edition")} ${doc.edition}` : "";
  const rev = doc.doc_type === "standard"
    ? (doc.revision ? `${t("partDivision")} ${doc.revision}` : "")
    : (doc.revision ? `${t("revisionWord")} ${doc.revision}` : "");
  meta.textContent = [doc.doc_type, editionText, rev, doc.filename].filter(Boolean).join(" · ");
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
    badge.className = "meta";
    badge.textContent = t("sourceMissing");
    body.appendChild(badge);
  }
  body.append(strong, meta, actions);
  li.append(icon, body);
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
  if (!window.confirm(t("confirmDelete"))) return;
  const path = doc.scope === "personal"
    ? `/api/library/documents/${doc.id}`
    : `/api/projects/${doc.project_id}/documents/${doc.id}`;
  await api(path, { method: "DELETE" });
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

let stickToBottom = true;

function threadHasMessages() {
  return !!$("messages").querySelector(".bubble");
}

function nearBottom() {
  const scroller = $("messages");
  return scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 80;
}

function scrollThread(force) {
  const scroller = $("messages");
  const jump = $("jump-latest");
  if (force || stickToBottom) {
    scroller.scrollTop = scroller.scrollHeight;
    stickToBottom = true;
    if (jump) jump.hidden = true;
  } else if (jump) {
    jump.hidden = false;
  }
}

function syncEmpty() {
  const started = threadHasMessages();
  const empty = $("empty-state");
  const row = $("prompt-row");
  const prompts = $("prompts");
  if (empty) empty.hidden = started;
  if (prompts && row) {
    prompts.classList.toggle("compact", started);
    const slot = started ? row : empty;
    if (slot && prompts.parentElement !== slot) slot.appendChild(prompts);
    row.hidden = !started;
  }
}

function bubbleShell(kind, label) {
  const node = document.createElement("div");
  node.className = `bubble ${kind}`;
  const row = document.createElement("div");
  row.className = "bubble-row";
  const avatar = document.createElement("span");
  avatar.className = "avatar";
  avatar.textContent = label;
  const body = document.createElement("div");
  body.className = "bubble-body";
  row.append(avatar, body);
  node.appendChild(row);
  return { node, body };
}

function addUserBubble(text) {
  const { node, body } = bubbleShell("user", "You");
  node.dir = hasPersian(text) ? "rtl" : "ltr";
  body.textContent = text;
  $("messages").appendChild(node);
  syncEmpty();
  scrollThread(true);
}

function addAnswer(answer) {
  state.lastAnswer = answer;
  const { node, body } = bubbleShell("assistant", "AI");
  const answerFa = answer.answer_language === "fa" || (answer.blocks || []).some((block) => hasPersian(block.text));
  node.dir = answerFa ? "rtl" : "ltr";
  const mode = document.createElement("p");
  mode.className = "meta";
  mode.textContent = `${t(answer.mode) || answer.mode} · ${answer.generator === "llm" ? t("llmNote") : t("extractiveNote")}`;
  body.appendChild(mode);
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
    body.appendChild(wrap);
  }
  if ((answer.limitations || []).length) {
    const limits = document.createElement("div");
    limits.className = "limitations";
    for (const item of answer.limitations) {
      const p = document.createElement("p");
      p.textContent = item;
      limits.appendChild(p);
    }
    body.appendChild(limits);
  }
  $("messages").appendChild(node);
  syncEmpty();
  scrollThread(false);
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
    const label = citation.store === "global" || citation.store === "personal" ? t("generalKnowledge") : citation.store_label;
    const where = label ? ` · ${label}` : "";
    card.querySelector("strong").textContent = `${citation.citation_id} · ${citation.source_document}${where}`;
    const badge = card.querySelector(".badge");
    badge.textContent = t(citation.statement_class) || citation.statement_label || citation.statement_class;
    badge.classList.add(citation.statement_class);
    const chips = document.createElement("div");
    chips.className = "chips";
    const bits = [
      citation.source_file,
      `${t("clause")} ${citation.clause || citation.section || "—"}`,
      `${t("page")} ${citation.page || "—"}`,
      citation.revision ? `${t("revisionWord")} ${citation.revision}` : "",
      citation.edition ? `${t("edition")} ${citation.edition}` : "",
    ].filter(Boolean);
    for (const bit of bits) {
      const chip = document.createElement("span");
      chip.className = "mono";
      chip.textContent = bit;
      chips.appendChild(chip);
    }
    card.querySelector(".meta").replaceWith(chips);
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

$("scope-button").addEventListener("click", () => {
  const menu = $("scope-menu");
  menu.hidden = !menu.hidden;
  $("scope-button").setAttribute("aria-expanded", menu.hidden ? "false" : "true");
  if (!menu.hidden) placeScopeMenu();
});
window.addEventListener("resize", placeScopeMenu);

async function submitUpload(event, errorName, extra) {
  event.preventDefault();
  setError(errorName, "");
  const target = state.scopes.projectIds[0];
  if (!target) {
    setError(errorName, t("uploadNeedProject"));
    return;
  }
  const form = new FormData(event.target);
  for (const [key, value] of Object.entries(extra || {})) form.set(key, value);
  event.target.classList.add("uploading");
  try {
    await api(`/api/projects/${target}/documents`, { method: "POST", body: form });
    event.target.reset();
    const kb = await api("/api/kb/documents");
    await renderDocs(kb.documents);
  } catch (error) {
    setError(errorName, error.message);
  } finally {
    event.target.classList.remove("uploading");
  }
}

$("upload-form").addEventListener("submit", (event) => submitUpload(event, "upload"));
$("standard-form").addEventListener("submit", (event) => submitUpload(event, "standard", { doc_type: "standard" }));
$("library-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  setError("library", "");
  const form = new FormData(event.target);
  event.target.classList.add("uploading");
  try {
    await api("/api/library/documents", { method: "POST", body: form });
    event.target.reset();
    const kb = await api("/api/kb/documents");
    await renderDocs(kb.documents);
  } catch (error) {
    setError("library", error.message);
  } finally {
    event.target.classList.remove("uploading");
  }
});

function openProjectModal(project) {
  state.editingProject = project || null;
  const form = $("project-form");
  form.code.value = project ? project.code : "";
  form.name.value = project ? project.name : "";
  form.equipment.value = project ? (project.equipment || "") : "";
  form.description.value = project ? (project.description || "") : "";
  $("project-modal-title").textContent = project ? t("renameProject") : t("newProject");
  setError("project", "");
  $("project-modal").showModal();
}

async function deleteProject(project) {
  if (!window.confirm(t("confirmDeleteProject"))) return;
  await api(`/api/projects/${project.id}`, { method: "DELETE" });
  state.scopes.projectIds = state.scopes.projectIds.filter((id) => id !== project.id);
  $("scope-menu").hidden = true;
  await refreshLibrary();
}

$("new-project").addEventListener("click", () => openProjectModal(null));
$("new-project-empty").addEventListener("click", () => openProjectModal(null));
$("new-project-chat").addEventListener("click", () => openProjectModal(null));
$("project-cancel").addEventListener("click", () => $("project-modal").close());
$("project-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  setError("project", "");
  const data = Object.fromEntries(new FormData(event.target));
  try {
    if (state.editingProject) {
      await api(`/api/projects/${state.editingProject.id}`, { method: "PATCH", json: data });
    } else {
      const created = await api("/api/projects", { method: "POST", json: data });
      state.scopes.projectIds = [...new Set([...state.scopes.projectIds, created.id])];
    }
    $("project-modal").close();
    await refreshLibrary();
  } catch (error) {
    setError("project", error.message);
  }
});

function growQuestion() {
  const box = $("question");
  box.style.height = "auto";
  const max = 24 * 6 + 22;
  box.style.height = `${Math.min(box.scrollHeight, max)}px`;
}

$("question").addEventListener("input", () => {
  growQuestion();
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
  if (event.key === "Enter" && !event.shiftKey && (menu.hidden || !state.mentionItems.length)) {
    event.preventDefault();
    $("composer").requestSubmit();
    return;
  }
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
  if ((event.key === "Enter" && !event.shiftKey) || event.key === "Tab") {
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
  $("typing").hidden = false;
  try {
    const answer = await api("/api/chat", {
      method: "POST",
      json: {
        message,
        mode,
        project_id: state.scopes.projectIds.length === 1 ? state.scopes.projectIds[0] : null,
        scopes: { global: state.scopes.global, project_ids: state.scopes.projectIds },
        conversation_id: state.conversationId,
        document_ids: state.mentions.map((item) => item.id),
      },
    });
    state.conversationId = answer.conversation_id;
    addAnswer(answer);
    $("question").value = "";
    $("question").style.height = "auto";
  } catch (error) {
    setError("chat", error.message);
  } finally {
    $("typing").hidden = true;
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

document.querySelectorAll("[data-auth-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    const tab = button.dataset.authTab;
    $("login-form").hidden = tab !== "login";
    $("register-form").hidden = tab !== "register";
    document.querySelectorAll("[data-auth-tab]").forEach((item) => item.classList.toggle("active", item === button));
  });
});

document.querySelectorAll("[data-theme-set]").forEach((button) => {
  const sync = () => button.setAttribute("aria-pressed", document.documentElement.dataset.theme === "light" ? "true" : "false");
  sync();
  button.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("eai_theme", next);
    document.querySelectorAll("[data-theme-set]").forEach((item) => item.setAttribute("aria-pressed", next === "light" ? "true" : "false"));
  });
});

function setSheet(name, open) {
  document.body.classList.toggle("nav-open", name === "nav" && open);
  document.body.classList.toggle("evidence-open", name === "evidence" && open);
  if (!open) {
    document.body.classList.remove("nav-open", "evidence-open");
  }
}
$("open-sidebar").addEventListener("click", () => setSheet("nav", true));
$("close-sidebar").addEventListener("click", () => setSheet("nav", false));
$("open-evidence").addEventListener("click", () => setSheet("evidence", true));
$("close-evidence").addEventListener("click", () => setSheet("evidence", false));
$("sheet-backdrop").addEventListener("click", () => setSheet("", false));

function bindSplitter(el, key, store, min, max, fallback) {
  if (!el) return;
  const read = () => {
    const raw = getComputedStyle(document.documentElement).getPropertyValue(key);
    const value = parseInt(raw, 10);
    return Number.isFinite(value) ? value : fallback;
  };
  const write = (value) => {
    const next = Math.min(max, Math.max(min, Math.round(value)));
    document.documentElement.style.setProperty(key, `${next}px`);
    localStorage.setItem(store, String(next));
    el.setAttribute("aria-valuemin", String(min));
    el.setAttribute("aria-valuemax", String(max));
    el.setAttribute("aria-valuenow", String(next));
  };
  const saved = parseInt(localStorage.getItem(store) || "", 10);
  write(Number.isFinite(saved) ? saved : fallback);
  let dragging = false;
  let startX = 0;
  let startW = 0;
  const rtlSign = () => (document.documentElement.dir === "rtl" ? -1 : 1);
  const direction = key === "--side-w" ? 1 : -1;
  el.addEventListener("pointerdown", (event) => {
    if (window.matchMedia("(max-width: 980px)").matches) return;
    dragging = true;
    startX = event.clientX;
    startW = read();
    el.setPointerCapture(event.pointerId);
  });
  el.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    write(startW + (event.clientX - startX) * direction * rtlSign());
  });
  el.addEventListener("pointerup", () => { dragging = false; });
  el.addEventListener("pointercancel", () => { dragging = false; });
  el.addEventListener("dblclick", () => write(fallback));
  el.addEventListener("keydown", (event) => {
    const step = event.shiftKey ? 32 : 16;
    const sign = direction * rtlSign();
    if (event.key === "ArrowRight") write(read() + step * sign);
    else if (event.key === "ArrowLeft") write(read() - step * sign);
    else if (event.key === "Home") write(min);
    else if (event.key === "End") write(max);
    else if (event.key === "Enter") write(fallback);
    else return;
    event.preventDefault();
  });
}
bindSplitter($("split-side"), "--side-w", "eai_side_w", 220, 480, 300);
bindSplitter($("split-evidence"), "--evidence-w", "eai_evidence_w", 240, 560, 340);
$("messages").addEventListener("scroll", () => {
  stickToBottom = nearBottom();
  const jump = $("jump-latest");
  if (jump) jump.hidden = stickToBottom || !threadHasMessages();
});
$("jump-latest").addEventListener("click", () => scrollThread(true));

document.querySelectorAll("form.upload").forEach((form) => {
  const input = form.querySelector('input[type="file"]');
  form.addEventListener("dragover", (event) => {
    event.preventDefault();
    form.classList.add("drag");
  });
  form.addEventListener("dragleave", () => form.classList.remove("drag"));
  form.addEventListener("drop", (event) => {
    event.preventDefault();
    form.classList.remove("drag");
    if (input && event.dataTransfer.files.length) input.files = event.dataTransfer.files;
  });
});

boot();
