/* Vespera Search Suite — SOC Dashboard edition.
 * Чипы-переключатели, динамический ввод, live-лог терминала, результаты, история, тема.
 */
"use strict";

const $ = (id) => document.getElementById((id || "").replace(/^#/, ""));
const escapeHtml = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// =====================================================================
// Конфигурация чипов
// =====================================================================
const CHIPS = [
  { id: "username", label: "Username", icon: "🧑", kind: "text",
    placeholder: "ray228a", hint: "Никнейм: латиница, цифры, _, -, .",
    validate: (v) => ({ ok: /^[A-Za-z0-9_.\-]{1,64}$/.test(v), err: "Никнейм должен быть от 1 до 64 символов: латиница, цифры, _, -, ." }) },
  { id: "email", label: "Email", icon: "✉️", kind: "text",
    placeholder: "user@example.com", hint: "user@example.com",
    validate: (v) => ({ ok: /^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$/.test(v), err: "Введите корректный email (user@example.com)" }) },
  { id: "phone", label: "Телефон", icon: "📞", kind: "text",
    placeholder: "+79001234567", hint: "Номер с кодом страны (+7...)",
    validate: (v) => ({ ok: /^\+[0-9\s\-()]{7,15}$/.test(v), err: "Введите номер в формате +79001234567" }) },
  { id: "social", label: "ФИО + Город", icon: "👥", kind: "social",
    placeholder: "Иванов Иван", hint: "Введите ФИО (и город, если есть)",
    validate: (v) => ({ ok: v.length >= 2, err: "Введите ФИО (минимум 2 символа)" }) },
  { id: "photo", label: "Фото", icon: "📸", kind: "file", accept: "image/*", maxMB: 10,
    validate: () => ({ ok: !!state.file, err: "Загрузите фото (JPG, PNG, WEBP до 10 МБ)" }) },
  { id: "metadata", label: "Метаданные", icon: "📄", kind: "file", accept: "*/*", maxMB: 25,
    validate: () => ({ ok: !!state.file, err: "Загрузите файл (до 25 МБ)" }) },
];

const state = {
  type: "username",
  selected: new Set(["username"]),
  file: null,
  logs: [],
  result: null,
  ws: null,
  phase: "idle",
  values: { username: "", email: "", phone: "", fio: "", city: "" },
  startedAt: performance.now(),
};

const FILE_ICONS = (t) => (t.startsWith("image/") ? "🖼" : "📄");

// =====================================================================
// Helpers
// =====================================================================
function toast(msg, isErr = false) {
  const t = document.createElement("div");
  t.className = isErr ? "toast toast-error" : "toast";
  t.textContent = msg;
  $("toasts").appendChild(t);
  setTimeout(() => t.remove(), 2600);
}

function updateUptime() {
  const el = $("uptime");
  if (!el) return;
  const sec = Math.floor((performance.now() - state.startedAt) / 1000);
  el.textContent = `● онлайн ${Math.floor(sec / 60)}m ${sec % 60}s`;
}

// =====================================================================
// Chips
// =====================================================================
function renderChips() {
  const host = $("chips");
  host.replaceChildren();
  for (const chip of CHIPS) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip" + (state.selected.has(chip.id) ? " active" : " inactive");
    b.dataset.chip = chip.id;
    b.innerHTML = `<span class="chip-icon">${chip.icon}</span><span class="chip-label">${chip.label}</span>`;
    chip.el = b;
    b.addEventListener("click", () => selectChip(chip.id));
    host.appendChild(b);
  }
}

function selectChip(id) {
  const c = CHIPS.find((c) => c.id === id);
  if (!c) return;
  if (state.selected.has(id)) state.selected.delete(id);
  else state.selected.add(id);
  state.type = id;
  c.el.classList.toggle("active", state.selected.has(id));
  updateInputArea();
  updateValidation();
}

// =====================================================================
// Input area (dynamic: text / dual / file)
// =====================================================================
function currentValue() {
  const info = CHIPS.find((c) => c.id === state.type);
  if (info.kind === "file") return state.file ? state.file.name : "";
  if (info.kind === "social") {
    const fio = $("#fio-input") ? $("#fio-input").value : state.values.fio || "";
    const city = $("#city-input") ? $("#city-input").value : state.values.city || "";
    return `${fio.trim()} ${city.trim()}`.trim();
  }
  return ($("#value-input") ? $("#value-input").value : state.values[info.id] || "").trim();
}

function saveValues(inputs) {
  for (const [key, el] of Object.entries(inputs)) {
    const type = el.id === "fio-input" ? "fio" : el.id === "city-input" ? "city" : el.id;
    el.addEventListener("input", () => { state.values[type] = el.value; updateValidation(); });
    state.values[type] = el.value;
  }
}

function updateInputArea() {
  const info = CHIPS.find((c) => c.id === state.type);
  const area = $("input-area");
  area.replaceChildren();

  if (info.kind === "file") {
    area.appendChild(buildFileZone());
    updateValidation();
    return;
  }

  const inputs = {};
  if (info.kind === "social") {
    const row = document.createElement("div");
    row.className = "dual-row";
    const fio = document.createElement("input");
    fio.className = "form-input"; fio.id = "fio-input"; fio.type = "text";
    fio.placeholder = "ФИО, например Иванов Иван";
    fio.value = state.values.fio || "";
    const city = document.createElement("input");
    city.className = "form-input"; city.id = "city-input"; city.type = "text";
    city.placeholder = "Город (необязательно)";
    city.value = state.values.city || "";
    row.append(fio, city);
    area.appendChild(row);
    inputs.fio = fio; inputs.city = city;
  } else {
    const el = document.createElement("input");
    el.className = "form-input"; el.id = "value-input"; el.type = "text";
    el.placeholder = info.placeholder;
    el.value = state.values[info.id] || "";
    inputs.value = el;
    area.appendChild(el);
  }
  saveValues(inputs);

  const hint = document.createElement("div");
  hint.className = "field-hint";
  hint.textContent = info.hint;
  area.appendChild(hint);

  updateValidation();
}

function buildFileZone() {
  const info = CHIPS.find((c) => c.id === state.type);
  const zone = document.createElement("div");
  zone.className = "dropzone";

  const fileInput = document.createElement("input");
  fileInput.id = "file-input";
  fileInput.type = "file"; fileInput.style.display = "none";
  fileInput.accept = info.accept || "*/*";
  fileInput.addEventListener("change", async (e) => {
    if (e.target.files && e.target.files.length) await pickFile(e.target.files[0]);
  });
  zone.appendChild(fileInput);
  zone.addEventListener("click", () => fileInput.click());
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("drag-over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
  zone.addEventListener("drop", async (e) => {
    e.preventDefault(); zone.classList.remove("drag-over");
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
      await pickFile(e.dataTransfer.files[0]);
    }
  });

  const dzIcon = document.createElement("span");
  dzIcon.className = "dz-icon";
  const dzTitle = document.createElement("div");
  dzTitle.className = "dz-title";
  const dzHint = document.createElement("div");
  dzHint.className = "dz-hint";
  zone.append(dzIcon, dzTitle, dzHint);

  const refresh = () => {
    dzIcon.textContent = state.file ? "📁" : "☁️";
    dzTitle.textContent = state.file ? "Файл выбран" : "Перетащите файл сюда или кликните для выбора";
    dzHint.textContent = state.file
      ? `${state.file.name} · ${((state.file.size / 1024 / 1024).toFixed(1))} МБ`
      : `JPG, PNG, WEBP · до ${info.maxMB || 10} МБ`;
    if (state.file && !zone.querySelector(".file-preview")) {
      const p = document.createElement("div");
      p.className = "file-preview";
      p.innerHTML = `
        <span class="fp-icon">${FILE_ICONS(state.file.type)}</span>
        <span class="fp-name">${escapeHtml(state.file.name)}</span>
        <span class="fp-size">${((state.file.size / 1024 / 1024).toFixed(1))} МБ</span>
        <button type="button" class="fp-remove">✕</button>`;
      p.querySelector(".fp-remove").addEventListener("click", (e) => {
        e.stopPropagation();
        state.file = null;
        updateInputArea();
      });
      zone.appendChild(p);
    }
  };
  refresh();
  return zone;
}

async function pickFile(file) {
  if (!file) return;
  const info = CHIPS.find((c) => c.id === state.type);
  const maxMB = info.maxMB || 25;
  const sizeMB = file.size / 1024 / 1024;
  if (sizeMB > maxMB) {
    state.file = null;
    toast(`Файл слишком большой (${sizeMB.toFixed(1)} МБ). Максимум: ${maxMB} МБ`, true);
    updateInputArea(); updateValidation();
    return;
  }
  state.file = file;
  toast(`Файл «${file.name}» загружен (${sizeMB.toFixed(1)} МБ)`);
  updateInputArea(); updateValidation();
}

function updateValidation() {
  const info = CHIPS.find((c) => c.id === state.type);
  const v = currentValue();
  const res = info.validate(v);
  const btn = $("search-btn");
  btn.disabled = !res.ok || state.phase !== "idle";
  clearError();
  document.querySelectorAll(".form-input").forEach((el) => el.classList.toggle("invalid", !res.ok));
  if (!res.ok) showError(res.err);
}

function clearError() { $("search-error").hidden = true; $("search-error").textContent = ""; }
function showError(msg) {
  $("search-error").textContent = msg;
  $("search-error").hidden = false;
}

// =====================================================================
// Search flow
// =====================================================================
function startSearch() {
  if (state.phase === "loading") return; // пока сейчас сканируем — игнорируем повторный клик
  const info = CHIPS.find((c) => c.id === state.type);
  const v = currentValue();
  const { ok, err } = info.validate(v);
  if (!ok) { showError(err); return; }
  clearError();

  state.phase = "loading";
  state.result = null;
  state.logs = [];
  showTerminal(true);
  showProgress(true, "Сканируем источники…");
  setSearchButtonState(true);
  renderTerminalLine(`[search] ${info.label}: «${v.slice(0, 40)}»`);

  const conn = VesperaSearch.connect(info.id, v, {
    onLog: (ev) => {
      state.logs.push(ev);
      const cls = ev.status === "ok" ? "s-ok" : ev.status === "error" ? "s-error" : ev.status === "progress" ? "s-progress" : "";
      renderTerminalLine(`[${ev.module}] ${ev.status}${ev.detail ? " — " + ev.detail : ""}`, cls);
      showProgress(true, `[${ev.module}] ${ev.status}${ev.detail ? " — " + ev.detail : ""}`);
    },
    onResult: (result) => finishSearch(result),
    onError: (ev) => stopSearch(ev.message || "Ошибка поиска"),
    onClose: () => { if (state.phase === "loading") stopSearch("Соединение с сервером потеряно"); },
  });
  state.ws = conn.ws;
}

function finishSearch(result) {
  const s = result?.summary || {};
  state.phase = s.total_found ? "results" : "empty";
  state.result = result;
  if (state.ws) { state.ws.close(); state.ws = null; }
  showTerminal(false);
  showProgress(false);
  setSearchButtonState(false);
  if (state.phase === "results") {
    renderResults(result);
  } else {
    showEmptyState();
  }
  toast(state.phase === "results" ? `Найдено: ${s.total_found}` : "По запросу ничего не найдено", false);
  saveHistory({
    id: result?.id, type: result?.query?.type, value: result?.query?.value,
    summary: s, ts: new Date().toISOString(),
  });
  updateUptime();
}

function stopSearch(msg) {
  if (state.phase !== "loading") return;
  state.phase = "idle";
  if (state.ws) { state.ws.close(); state.ws = null; }
  showTerminal(false);
  showProgress(false);
  setSearchButtonState(false);
  if (msg) showError(msg);
}

// Terminal (live-log)
function renderTerminalLine(text, cls = "") {
  const el = document.createElement("div");
  el.className = "log-line" + (cls ? " " + cls : "");
  el.textContent = text;
  const body = $("terminal-lines");
  body.appendChild(el);
  body.scrollTop = body.scrollHeight;
}
function showTerminal(show) { $("terminal").hidden = !show; }
function showProgress(show, text = "Сканируем источники…") {
  $("progress-row").hidden = !show;
  $("progress-text").textContent = text;
}
function setSearchButtonState(loading) {
  $("search-btn").disabled = loading;
  $("stop-btn").hidden = !loading;
  if (!loading) $("stop-btn").disabled = false;
}
$("stop-btn").addEventListener("click", () => {
  if (state.ws) state.ws.close();
});

// =====================================================================
// Results rendering
// =====================================================================
function confRank(item) { return { high: 3, medium: 2, low: 1, info: 0 }[item.confidence] ?? 0; }
function confClass(c) { return { high: "badge-high", medium: "badge-medium", low: "badge-low", info: "badge-info" }[c] || "badge-info"; }

function flattenResults(result) {
  const out = [];
  for (const [type, arr] of Object.entries(result.results || {})) {
    for (const it of arr || []) out.push({ ...it, type });
  }
  return out;
}

function renderResults(result) {
  const grid = $("results-grid");
  grid.replaceChildren();
  const items = flattenResults(result).sort((a, b) => confRank(b) - confRank(a));
  if (Array.isArray(result.key_info) && result.key_info.length) {
    grid.appendChild(renderKeyInfo(result.key_info));
  }
  items.forEach((item, i) => grid.appendChild(renderCard(item, i)));
  const s = result.summary || {};
  const parts = [`Найдено: ${s.total_found || 0}`];
  if (s.sources_used) parts.push(`Источников: ${s.sources_used}`);
  if (s.high_confidence && s.high_confidence.length) parts.push(`Надёжных: ${s.high_confidence.length}`);
  $("summary-text").textContent = parts.join(" · ");
  $("results-toolbar").hidden = false;
  $("empty-state").hidden = true;
  renderGraph(result);
}

function renderGraph(result) {
  const container = $("cy");
  if (!container) return;
  if (typeof cytoscape === "undefined") { toast("Cytoscape не загружен", true); return; }
  const gd = result.graph_data || { nodes: [], edges: [] };
  if (gd.nodes.length < 2) { container.hidden = true; return; }
  container.hidden = false;
  try {
    const cy = cytoscape({
      container,
      elements: { nodes: gd.nodes, edges: gd.edges },
      style: [
        { selector: "node", style: {
          backgroundColor: "#334155", color: "#fff", fontSize: 11, label: "data(label)",
          width: 44, height: 32, borderWidth: 1, borderColor: "#fff",
          textValign: "top", textHAlign: "center"
        }},
        { selector: "node[type='query']", style: { width: 60, backgroundColor: "#3b82f4", label: "" } },
        { selector: "node[type='category']", style: { backgroundColor: "#10b981", width: 40 } },
        { selector: "edge", style: { lineColor: "#475569", width: 1.2, targetArrowShape: "triangle", targetArrowColor: "#475569" } },
      ],
      layout: { name: "breadthfirst", directed: true, roots: "#root", padding: 6, spacingFactor: 1.5 },
    });
    cy.on("tap", "node", (evt) => {
      const url = evt.target.data("url");
      if (url) window.open(url, "_blank");
    });
    toast(`Граф: ${gd.nodes.length} узлов, ${gd.edges.length} связей`);
  } catch (e) {
    container.hidden = true;
    toast("Ошибка графа: " + e.message, true);
  }
}

function renderKeyInfo(keyInfo) {
  const card = document.createElement("article");
  card.className = "result-card key-info";

  const h = document.createElement("h3");
  h.className = "key-info-title";
  h.textContent = "Ключевая информация";
  card.appendChild(h);

  for (const it of keyInfo) {
    const row = document.createElement("div");
    row.className = "key-info-row";
    const label = document.createElement("span");
    label.className = "key-info-label";
    label.textContent = it.title || "";
    const value = document.createElement("span");
    value.className = "key-info-value";
    const parts = [];
    if (it.value) parts.push(String(it.value));
    if (it.carrier && it.carrier !== "Неизвестно") parts.push(`Оператор: ${it.carrier}`);
    if (it.line_type) parts.push(String(it.line_type));
    if (it.valid === false) parts.push("невалиден");
    if (it.valid === true) parts.push("✓ валидный");
    value.textContent = parts.join(" · ");
    row.append(label, value);
    if (it.url) {
      const link = document.createElement("a");
      link.className = "key-info-link";
      link.href = it.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "Перейти ↗";
      row.append(link);
    }
    card.appendChild(row);
  }
  return card;
}

function renderCard(item, index) {
  const card = document.createElement("article");
  card.className = "result-card";
  card.style.animationDelay = `${Math.min(index * 25, 250)}ms`;

  const badge = document.createElement("span");
  badge.className = "card-badge " + confClass(item.confidence || "info");
  badge.textContent = item.confidence || "info";

  const link = document.createElement("a");
  link.className = "card-link";
  link.href = item.url || "#"; link.target = "_blank"; link.rel = "noopener noreferrer";
  link.textContent = item.title || item.source || "Без названия";

  const source = document.createElement("div");
  source.className = "card-source";
  source.textContent = item.source || "";

  const snippet = item.snippet ? document.createElement("p") : null;
  if (snippet) { snippet.className = "card-snippet"; snippet.textContent = item.snippet; }

  const actions = document.createElement("div");
  actions.className = "card-actions";
  const openBtn = document.createElement("a");
  openBtn.className = "btn-xs";
  openBtn.href = item.url || "#"; openBtn.target = "_blank";
  openBtn.textContent = "Открыть ↗";
  const copyBtn = document.createElement("button");
  copyBtn.className = "copy-link";
  copyBtn.textContent = "🔗 Копировать";
  copyBtn.addEventListener("click", () => { navigator.clipboard.writeText(item.url || ""); toast("URL скопирован"); });
  actions.append(openBtn, copyBtn);

  card.append(badge, link, source, snippet, actions);
  return card;
}

function showEmptyState() {
  $("results-toolbar").hidden = true;
  $("empty-state").hidden = false;
  $("results-grid").innerHTML = "";
}

// =====================================================================
// Export
// =====================================================================
function downloadBlob(blob, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 500);
}
function exportJSON() {
  if (!state.result) return;
  downloadBlob(new Blob([JSON.stringify(state.result, null, 2)], { type: "application/json" }), `vespera_${state.result.query?.type || "search"}.json`);
  toast("JSON сохранён");
}
function exportCSV() {
  if (!state.result) return;
  const rows = [["source", "url", "title", "snippet", "confidence", "verified", "type"]];
  for (const item of flattenResults(state.result)) {
    rows.push([item.source, item.url || "", item.title || "", (item.snippet || "").replace(/\n/g, " "), item.confidence || "", String(item.verified), item.type]);
  }
  const csv = rows.map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n");
  downloadBlob(new Blob([csv], { type: "text/csv" }), `vespera_${state.result.query?.type || "search"}.csv`);
  toast("CSV сохранён");
}

// =====================================================================
// History (localStorage)
// =====================================================================
const HISTORY_KEY = "vespera_history";
function loadHistory() {
  try { return JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]"); } catch { return []; }
}
function saveHistory(entry) {
  const arr = loadHistory();
  arr.unshift({ ...entry, created_at: new Date().toISOString() });
  localStorage.setItem(HISTORY_KEY, JSON.stringify(arr.slice(0, 50)));
  renderHistoryList();
}
function renderHistoryList() {
  const list = $("history-list");
  list.replaceChildren();
  const items = loadHistory();
  for (const it of items) {
    const li = document.createElement("li");
    li.className = "history-item";
    const details = document.createElement("details");
    details.classList.add("open");
    const summary = document.createElement("summary");
    const meta = document.createElement("span");
    meta.className = "h-meta";
    meta.textContent = new Date(it.created_at).toLocaleTimeString();
    const value = document.createElement("span");
    value.className = "h-value";
    value.textContent = `${it.type} · ${it.value}`;
    summary.append(meta, value);
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(it.result || { summary: it.summary }, null, 1).slice(0, 3500);
    details.append(summary, pre);
    li.appendChild(details);
    li.addEventListener("click", () => {
      if (state.phase === "loading") return;
      rerunHistory(it);
    });
    list.appendChild(li);
  }
  if (!list.children.length) {
    const li = document.createElement("li");
    li.className = "history-item";
    li.textContent = "Нет истории";
    list.appendChild(li);
  }
}
function rerunHistory(entry) {
  selectChip(entry.type || "username");
  const info = CHIPS.find((c) => c.id === state.type);
  if (info.kind === "social") {
    const parts = String(entry.value || "").split(" ");
    if ($("#fio-input")) $("#fio-input").value = parts.slice(0, 2).join(" ");
    if ($("#city-input")) $("#city-input").value = parts.slice(2).join(" ");
  } else if ($("#value-input")) {
    $("#value-input").value = entry.value || "";
  } else if (state.file) {
    state.file = null;
    updateInputArea();
  }
  updateInputArea();
  updateValidation();
  closeHistory();
  startSearch();
}
function clearHistory() {
  localStorage.removeItem(HISTORY_KEY);
  renderHistoryList();
  toast("История очищена");
}
function openHistory() { $("history-modal").hidden = false; renderHistoryList(); }
function closeHistory() { $("history-modal").hidden = true; }

// =====================================================================
// Examples (для пустого состояния)
// =====================================================================
function applyExample(chipId, value) {
  selectChip(chipId);
  const info = CHIPS.find((c) => c.id === chipId);
  if (info.kind === "social") {
    if ($("#fio-input")) $("#fio-input").value = value;
    state.values.fio = value;
  } else if ($("#value-input")) {
    $("#value-input").value = value;
    state.values[info.id] = value;
  }
  updateInputArea();
  updateValidation();
}
document.querySelectorAll("#examples .example-chip").forEach((b) => {
  b.addEventListener("click", () => { applyExample(b.dataset.chip, b.dataset.value); startSearch(); });
});

// =====================================================================
// Theme
// =====================================================================
function setTheme(dark) {
  document.body.classList.toggle("dark", dark);
  $("theme-toggle").textContent = dark ? "🌙" : "☀️";
}
function updateTheme() {
  setTheme(localStorage.getItem("vespera_theme") !== "light");
}

// =====================================================================
// Keyboard shortcuts
// =====================================================================
document.addEventListener("keydown", (e) => {
  if (e.key === "/" && !["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) {
    e.preventDefault();
    (document.querySelector("#value-input") || document.querySelector("#fio-input"))?.focus();
  }
  if (e.key === "Escape") (document.querySelector("#value-input") || document.querySelector("#fio-input"))?.blur();
});

// =====================================================================
// PTY terminal (vendored xterm)
// =====================================================================
let term = null;
let termWs = null;

function openTerminal() {
  $("pty-panel").hidden = false;
  const root = $("xterm-root");
  root.replaceChildren();
  const tryInit = (n) => {
    if (typeof Terminal === "undefined") {
      if (n < 5) setTimeout(() => tryInit(n + 1), 1500);
      else { $("pty-status").textContent = "xterm.js не загружен"; toast("xterm.js не загружен", true); }
      return;
    }
    startTerminal(root);
  };
  tryInit(0);
}

function startTerminal(root) {
  term = new Terminal({
    cursorBlink: true,
    fontFamily: "'JetBrains Mono', 'Courier New', monospace",
    fontSize: 13,
    scrollback: 2000,
    theme: { background: "#0A0F1A", foreground: "#E6EDF3", cursor: "#00FF9D" },
  });
  term.open(root);
  const ws = new WebSocket("ws://" + location.host + "/ws/terminal");
  termWs = ws;
  ws.binaryType = "arraybuffer";
  $("pty-status").textContent = "Подключение...";
  ws.onopen = () => { $("pty-status").textContent = "✅ Терминал готов"; term.focus(); };
  ws.onmessage = (ev) => { try { term.write(ev.data instanceof ArrayBuffer ? new TextDecoder().decode(ev.data) : ev.data); } catch { /* ignore */ } };
  ws.onclose = () => { $("pty-status").textContent = "❌ Терминал отключён"; try { term.writeln("\r\n[терминал закрыт]"); } catch { /* ignore */ } };
  ws.onerror = () => { $("pty-status").textContent = "⚠️ Ошибка соединения"; };
  term.onData((data) => { if (termWs && termWs.readyState === WebSocket.OPEN) termWs.send(data); });
  setTimeout(() => term && term.focus(), 300);
}

function closeTerminal() {
  if (termWs && termWs.readyState === WebSocket.OPEN) termWs.close();
  if (term) { try { term.dispose(); } catch { /* ignore */ } term = null; }
  $("pty-panel").hidden = true;
}

// =====================================================================
// AI Copilot (WebSocket → LLM, Markdown-чат)
// =====================================================================
let aiWs = null;
let aiMsgEl = null;

function scrollBottom() { const m = $("ai-messages"); m.scrollTop = m.scrollHeight; }

function renderMarkdown(text) {
  try {
    if (typeof marked === "undefined" || !marked.parse) return escapeHtml(text);
    const html = marked.parse(String(text), { gfm: true, breaks: true });
    if (typeof DOMPurify !== "undefined") return DOMPurify.sanitize(html);
    return html;
  } catch { return escapeHtml(text); }
}

function appendAi(text, isAI) {
  const div = document.createElement("div");
  div.className = isAI ? "flex justify-start" : "flex justify-end";
  const inner = document.createElement("div");
  inner.className = "px-4 py-2.5 rounded-xl text-sm" +
    (isAI ? " bg-slate-800/90 border border-slate-700 text-slate-200" : " bg-teal-600 text-white");
  if (isAI) {
    inner.innerHTML = renderMarkdown(text);
    inner.querySelectorAll("pre").forEach((pre) => {
      if (pre.dataset.copyBtn) return;
      pre.style.position = "relative";
      pre.dataset.copyBtn = "1";
      const btn = document.createElement("button");
      btn.textContent = "Copy";
      btn.addEventListener("click", () => {
        navigator.clipboard.writeText(pre.textContent || "");
        btn.textContent = "✓ Copied";
        setTimeout(() => { btn.textContent = "Copy"; }, 1500);
      });
      pre.appendChild(btn);
    });
  } else {
    inner.textContent = text;
  }
  div.appendChild(inner);
  $("ai-messages").appendChild(div);
  scrollBottom();
  if (isAI) aiMsgEl = inner;
}

function openAIChat() {
  $("ai-panel").hidden = false;
  appendAi("Привет! Я AI Copilot Vespera: опишите проблему (ошибки, зависания модулей), и я проанализирую логи.", true);
  const ws = new WebSocket("ws://" + location.host + "/ws/ai-chat");
  aiWs = ws;
  ws.onmessage = (ev) => {
    let data;
    try { data = JSON.parse(ev.data); } catch { return; }
    if (data.type === "welcome") { appendAi(data.message, true); return; }
    if (data.type === "chunk") { if (aiMsgEl) aiMsgEl.innerHTML = renderMarkdown(data.text); scrollBottom(); return; }
    if (data.type === "done") { aiMsgEl = null; return; }
    if (data.type === "error") { appendAi("⚠️ " + data.message, true); return; }
  };
  ws.onclose = () => appendAi("[AI Copilot отключён]", true);
}

function closeAIChat() {
  if (aiWs && aiWs.readyState === WebSocket.OPEN) aiWs.close();
  $("ai-panel").hidden = true;
  $("ai-messages").replaceChildren();
  aiMsgEl = null;
}

function aiSend() {
  const input = $("ai-input");
  const text = input.value.trim();
  if (!text) return;
  if (!aiWs || aiWs.readyState !== WebSocket.OPEN) { toast("AI Copilot не подключён", true); return; }
  appendAi(text, false);
  aiWs.send(JSON.stringify({ type: "chat", message: text }));
  input.value = "";
}

// =====================================================================
// Startup wiring
// =====================================================================
document.getElementById("search-form").addEventListener("submit", (e) => { e.preventDefault(); startSearch(); });
document.querySelectorAll("[data-export]").forEach((btn) => {
  btn.addEventListener("click", () => { (btn.dataset.export === "json" ? exportJSON : exportCSV)(); });
});

$("theme-toggle").addEventListener("click", () => setTheme(!document.body.classList.contains("dark")));
$("rerun-btn").addEventListener("click", () => { startSearch(); });
$("terminal-open").addEventListener("click", openTerminal);
$("pty-close").addEventListener("click", closeTerminal);
$("ai-open").addEventListener("click", openAIChat);
$("ai-close").addEventListener("click", closeAIChat);
$("ai-send").addEventListener("click", aiSend);
$("ai-input").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); aiSend(); } });
$("history-toggle").addEventListener("click", () => (historyModal().hidden ? openHistory() : closeHistory()));
$("history-close").addEventListener("click", closeHistory);
$("history-clear").addEventListener("click", clearHistory);
function historyModal() { return $("history-modal"); }
$("history-modal").addEventListener("click", (e) => { if (e.target.id === "history-modal") closeHistory(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && historyModal().hidden === false) closeHistory(); });

document.addEventListener("DOMContentLoaded", () => {
  renderChips();
  updateInputArea();
  updateValidation();
  (document.querySelector("#value-input") || document.querySelector("#fio-input"))?.focus();
  updateUptime();
});
