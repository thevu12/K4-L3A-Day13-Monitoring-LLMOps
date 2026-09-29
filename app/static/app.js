const state = {
  dashboard: null,
  currentView: "overview",
  logCorrelationId: "",
  refreshTimer: null,
};

const palette = {
  blue: "#2674d9",
  blueFill: "rgba(38, 116, 217, 0.12)",
  teal: "#16857f",
  tealFill: "rgba(22, 133, 127, 0.10)",
  amber: "#bd7b16",
  violet: "#7357c7",
  orange: "#d67430",
  red: "#c34444",
  grid: "#e7ebee",
  muted: "#8e99a4",
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

function setText(selector, value) {
  const element = $(selector);
  if (element) element.textContent = value;
}

function number(value, digits = 0) {
  return Number(value || 0).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function timeLabel(value) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? "--"
    : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("is-visible");
  window.setTimeout(() => toast.classList.remove("is-visible"), 2600);
}

function switchView(viewName) {
  state.currentView = viewName;
  $$("[data-view]").forEach((view) => {
    const active = view.dataset.view === viewName;
    view.hidden = !active;
    view.classList.toggle("is-visible", active);
  });
  $$("[data-view-target]").forEach((button) => {
    const active = button.dataset.viewTarget === viewName;
    button.classList.toggle("is-active", active);
    if (button.getAttribute("role") === "tab") {
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
    }
  });
  if (viewName === "requests") loadLogs();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`Unexpected response (${response.status})`);
  }
  if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
  return payload;
}

async function refreshDashboard(silent = false) {
  const button = $("#refresh-button");
  button.classList.add("is-loading");
  try {
    const data = await fetchJson("/api/dashboard?minutes=60");
    state.dashboard = data;
    renderDashboard(data);
    if (!silent) showToast("Dashboard refreshed from sanitized logs");
  } catch (error) {
    setText("#last-updated", "Dashboard unavailable");
    setText("#footer-health", "API unavailable");
    showToast(error.message);
  } finally {
    button.classList.remove("is-loading");
  }
}

function setStatus(selector, label, bad = false) {
  const element = $(selector);
  element.textContent = label;
  element.classList.toggle("is-bad", bad);
}

function renderDashboard(data) {
  const summary = data.summary;
  const panels = data.panels;
  setText("#last-updated", `Updated ${timeLabel(data.generated_at)} · ${data.window_minutes}m window`);
  setText("#tracing-state", data.tracing_enabled ? "Tracing on" : "Tracing off");
  setText("#summary-requests", number(summary.requests));
  setText("#summary-rate", `${number(summary.traffic_per_minute, 2)} / min`);
  setText("#summary-latency", `${number(summary.latency_p95)} ms`);
  setText("#summary-errors", `${number(summary.error_rate_pct, 2)}%`);
  setText("#summary-retrieval", `Retrieval ${number(summary.retrieval_success_rate_pct, 1)}%`);
  setText("#summary-quality", number(summary.quality_avg, 2));

  setText("#latency-p50", `${number(panels.latency.p50)} ms`);
  setText("#latency-p95", `${number(panels.latency.p95)} ms`);
  setText("#latency-p99", `${number(panels.latency.p99)} ms`);
  setText("#latency-ttft", `${number(panels.latency.ttft_p95)} ms`);
  setStatus("#latency-status", panels.latency.p95 <= 3000 ? "Within SLO" : "Above SLO", panels.latency.p95 > 3000);

  setText("#traffic-count", number(panels.traffic.count));
  setText("#traffic-rate", number(panels.traffic.rate_per_minute, 2));
  setText("#traffic-status", `${data.window_minutes}m`);

  setText("#error-rate-value", `${number(panels.errors.error_rate_pct, 2)}%`);
  setText("#failed-count", number(panels.errors.breakdown.reduce((total, item) => total + item.count, 0)));
  setText("#retrieval-ring-value", `${number(panels.errors.retrieval_success_rate_pct, 1)}%`);
  $("#retrieval-ring").style.setProperty("--ring", `${Math.min(100, panels.errors.retrieval_success_rate_pct)}%`);
  setStatus("#errors-status", panels.errors.error_rate_pct <= 2 ? "Healthy" : "Investigate", panels.errors.error_rate_pct > 2);
  renderBreakdown(panels.errors.breakdown);

  setText("#cost-total", `$${number(panels.cost.total_usd, 4)}`);
  setText("#tokens-input", number(panels.tokens.input_total));
  setText("#tokens-output", number(panels.tokens.output_total));
  setText("#quality-value", number(panels.quality.avg, 2));
  $("#quality-fill").style.width = `${Math.min(100, panels.quality.avg * 100)}%`;
  setStatus("#quality-status", panels.quality.avg >= 0.75 ? "Target met" : "Below target", panels.quality.avg < 0.75 && data.has_data);

  setText("#slo-target", `${number(data.slo.target_percent, 1)}%`);
  setText("#slo-budget", `${number(data.slo.error_budget_percent, 1)}%`);
  setText("#slo-window", data.slo.window);
  $("#slo-progress-fill").style.width = `${Math.min(100, data.slo.target_percent)}%`;

  renderRecentRequests(data.requests.slice(0, 7));
  renderAlerts(data.alerts);
  drawLineChart("latency-chart", panels.latency.series, [
    { key: "p95", color: palette.blue, fill: palette.blueFill },
    { key: "p50", color: palette.teal },
    { key: "ttft", color: palette.amber },
  ]);
  drawBarChart("traffic-chart", panels.traffic.series, [
    { key: "value", color: palette.blue },
    { key: "errors", color: palette.red },
  ]);
  drawLineChart("cost-chart", panels.cost.series, [{ key: "value", color: palette.teal, fill: palette.tealFill }]);
  drawBarChart("tokens-chart", panels.tokens.series, [
    { key: "input", color: palette.violet },
    { key: "output", color: palette.orange },
  ]);
  drawLineChart("quality-chart", panels.quality.series, [{ key: "value", color: palette.blue, fill: palette.blueFill }], 1);
  setText("#footer-health", data.has_data ? "Local API · live" : "Local API · no window data");
  if (window.lucide) window.lucide.createIcons();
}

function renderBreakdown(items) {
  const container = $("#error-breakdown");
  container.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("span");
    empty.className = "empty-inline";
    empty.textContent = "No errors in window";
    container.append(empty);
    return;
  }
  items.slice(0, 3).forEach((item) => {
    const row = document.createElement("div");
    row.className = "breakdown-row";
    const label = document.createElement("span");
    label.textContent = item.name;
    const count = document.createElement("strong");
    count.textContent = number(item.count);
    row.append(label, count);
    container.append(row);
  });
}

function renderRecentRequests(rows) {
  const body = $("#recent-requests-body");
  body.replaceChildren();
  if (!rows.length) {
    body.append(emptyRow(5, "No request outcomes in this window."));
    return;
  }
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    const idCell = document.createElement("td");
    const idButton = document.createElement("button");
    idButton.type = "button";
    idButton.className = "mono-button";
    idButton.textContent = row.correlation_id;
    idButton.addEventListener("click", () => openRequestLogs(row.correlation_id));
    idCell.append(idButton);
    const feature = cell(row.feature);
    const result = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = `status-badge${row.status === "error" ? " error" : ""}`;
    badge.textContent = row.status === "error" ? row.error_type || "error" : "success";
    result.append(badge);
    tr.append(idCell, feature, result, cell(row.latency_ms == null ? "--" : `${number(row.latency_ms)} ms`), cell(timeLabel(row.ts)));
    body.append(tr);
  });
}

function renderAlerts(alerts) {
  const container = $("#alert-list");
  container.replaceChildren();
  setText("#alert-count", `${alerts.length} rules`);
  alerts.forEach((alert) => {
    const item = document.createElement("div");
    item.className = "alert-item";
    const icon = document.createElement("div");
    icon.className = `alert-icon${alert.threshold_breached ? " active" : ""}`;
    const iconElement = document.createElement("i");
    iconElement.setAttribute("data-lucide", alert.threshold_breached ? "siren" : "circle-check");
    icon.append(iconElement);
    const copy = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = alert.name;
    const detail = document.createElement("span");
    detail.textContent = `${alert.condition} · fires after ${alert.duration} · ${alert.owner}`;
    copy.append(title, detail);
    const stateLabel = document.createElement("small");
    stateLabel.textContent = alert.threshold_breached ? "Threshold breach" : "Normal";
    item.append(icon, copy, stateLabel);
    container.append(item);
  });
}

function cell(value) {
  const td = document.createElement("td");
  td.textContent = value == null ? "--" : String(value);
  return td;
}

function emptyRow(span, message) {
  const row = document.createElement("tr");
  const td = document.createElement("td");
  td.colSpan = span;
  td.className = "empty-cell";
  td.textContent = message;
  row.append(td);
  return row;
}

function prepareCanvas(id) {
  const canvas = document.getElementById(id);
  if (!canvas) return null;
  const bounds = canvas.getBoundingClientRect();
  const ratio = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
  canvas.width = Math.max(1, Math.floor(bounds.width * ratio));
  canvas.height = Math.max(1, Math.floor(bounds.height * ratio));
  const context = canvas.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  return { context, width: bounds.width, height: bounds.height };
}

function chartRange(data, lines, fixedMax) {
  const values = data.flatMap((point) => lines.map((line) => Number(point[line.key] || 0)));
  return Math.max(fixedMax || 0, ...values, 1);
}

function drawGrid(context, width, height) {
  context.strokeStyle = palette.grid;
  context.lineWidth = 1;
  for (let index = 1; index <= 3; index += 1) {
    const y = Math.round((height / 4) * index) + 0.5;
    context.beginPath();
    context.moveTo(0, y);
    context.lineTo(width, y);
    context.stroke();
  }
}

function drawLineChart(id, data, lines, fixedMax) {
  const prepared = prepareCanvas(id);
  if (!prepared) return;
  const { context, width, height } = prepared;
  context.clearRect(0, 0, width, height);
  drawGrid(context, width, height);
  const max = chartRange(data, lines, fixedMax);
  const xFor = (index) => (data.length <= 1 ? width / 2 : (index / (data.length - 1)) * width);
  const yFor = (value) => height - 8 - (Number(value || 0) / max) * (height - 16);
  lines.forEach((line) => {
    const points = data.map((point, index) => ({ x: xFor(index), y: yFor(point[line.key]) }));
    if (line.fill && points.length) {
      context.beginPath();
      context.moveTo(points[0].x, height);
      points.forEach((point) => context.lineTo(point.x, point.y));
      context.lineTo(points[points.length - 1].x, height);
      context.closePath();
      context.fillStyle = line.fill;
      context.fill();
    }
    context.beginPath();
    points.forEach((point, index) => index === 0 ? context.moveTo(point.x, point.y) : context.lineTo(point.x, point.y));
    context.strokeStyle = line.color;
    context.lineWidth = 2;
    context.lineJoin = "round";
    context.lineCap = "round";
    context.stroke();
  });
}

function drawBarChart(id, data, bars) {
  const prepared = prepareCanvas(id);
  if (!prepared) return;
  const { context, width, height } = prepared;
  context.clearRect(0, 0, width, height);
  drawGrid(context, width, height);
  const max = chartRange(data, bars);
  const slot = width / Math.max(1, data.length);
  const groupWidth = Math.min(slot * 0.68, 26);
  const barWidth = Math.max(2, groupWidth / bars.length - 2);
  data.forEach((point, pointIndex) => {
    bars.forEach((bar, barIndex) => {
      const value = Number(point[bar.key] || 0);
      const barHeight = (value / max) * (height - 9);
      const x = pointIndex * slot + (slot - groupWidth) / 2 + barIndex * (barWidth + 2);
      context.fillStyle = bar.color;
      context.fillRect(x, height - barHeight, barWidth, barHeight);
    });
  });
}

async function loadLogs() {
  const params = new URLSearchParams({ limit: "200" });
  const query = $("#log-query").value.trim();
  const event = $("#log-event").value;
  const level = $("#log-level").value;
  if (query) params.set("query", query);
  if (event) params.set("event", event);
  if (level) params.set("level", level);
  if (state.logCorrelationId) params.set("correlation_id", state.logCorrelationId);
  try {
    const data = await fetchJson(`/api/logs?${params}`);
    renderLogs(data.records);
    setText("#log-count", `${number(data.count)} records${state.logCorrelationId ? " · filtered ID" : ""}`);
  } catch (error) {
    const body = $("#logs-body");
    body.replaceChildren(emptyRow(8, error.message));
  }
}

function renderLogs(records) {
  const body = $("#logs-body");
  body.replaceChildren();
  if (!records.length) {
    body.append(emptyRow(8, "No sanitized log records match these filters."));
    return;
  }
  records.forEach((record) => {
    const row = document.createElement("tr");
    const idCell = document.createElement("td");
    const idButton = document.createElement("button");
    idButton.type = "button";
    idButton.className = "mono-button";
    idButton.textContent = record.correlation_id || "--";
    idButton.title = "Filter by this correlation ID";
    idButton.addEventListener("click", () => openRequestLogs(record.correlation_id));
    idCell.append(idButton);
    const status = document.createElement("span");
    status.className = `status-badge${record.level === "error" ? " error" : ""}`;
    status.textContent = record.level || "--";
    const levelCell = document.createElement("td");
    levelCell.append(status);
    const actionCell = document.createElement("td");
    const copyButton = document.createElement("button");
    copyButton.type = "button";
    copyButton.className = "icon-button";
    copyButton.title = "Copy correlation ID";
    copyButton.setAttribute("aria-label", "Copy correlation ID");
    const icon = document.createElement("i");
    icon.setAttribute("data-lucide", "copy");
    copyButton.append(icon);
    copyButton.addEventListener("click", () => copyText(record.correlation_id || ""));
    actionCell.append(copyButton);
    row.append(
      cell(timeLabel(record.ts)),
      cell(record.event),
      levelCell,
      idCell,
      cell(record.feature || "--"),
      cell(record.latency_ms == null ? "--" : `${number(record.latency_ms)} ms`),
      cell(record.tool_success == null ? "--" : record.tool_success ? "success" : "failed"),
      actionCell,
    );
    body.append(row);
  });
  if (window.lucide) window.lucide.createIcons();
}

function openRequestLogs(correlationId) {
  state.logCorrelationId = correlationId || "";
  $("#log-query").value = correlationId || "";
  switchView("requests");
}

async function copyText(value) {
  try {
    await navigator.clipboard.writeText(value);
    showToast("Correlation ID copied");
  } catch {
    showToast("Clipboard is unavailable");
  }
}

async function submitChat(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector("button[type='submit']");
  submit.disabled = true;
  setText("#chat-status", "Sending request...");
  setText("#response-state", "Running");
  try {
    const formData = new FormData(form);
    const payload = Object.fromEntries(formData.entries());
    const data = await fetchJson("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    $("#chat-empty").hidden = true;
    $("#chat-result").hidden = false;
    setText("#chat-answer", data.answer);
    setText("#chat-correlation", data.correlation_id);
    setText("#chat-latency", `${number(data.latency_ms)} ms`);
    setText("#chat-ttft", `${number(data.ttft_ms)} ms`);
    setText("#chat-cost", `$${number(data.cost_usd, 5)}`);
    setText("#chat-quality", number(data.quality_score, 2));
    setText("#response-state", "Success");
    setText("#chat-status", "Request completed");
    $("#chat-correlation").onclick = () => openRequestLogs(data.correlation_id);
    await refreshDashboard(true);
  } catch (error) {
    setText("#response-state", "Failed");
    setText("#chat-status", error.message);
    showToast(error.message);
  } finally {
    submit.disabled = false;
  }
}

function clearLogFilters() {
  state.logCorrelationId = "";
  $("#log-query").value = "";
  $("#log-event").value = "";
  $("#log-level").value = "";
  loadLogs();
}

function configureAutoRefresh() {
  window.clearInterval(state.refreshTimer);
  if ($("#auto-refresh").checked) {
    state.refreshTimer = window.setInterval(() => refreshDashboard(true), 30000);
  }
}

function debounce(callback, delay = 250) {
  let timeout;
  return (...args) => {
    window.clearTimeout(timeout);
    timeout = window.setTimeout(() => callback(...args), delay);
  };
}

function init() {
  $$("[data-view-target]").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.viewTarget)));
  $("#refresh-button").addEventListener("click", () => refreshDashboard());
  $("#auto-refresh").addEventListener("change", configureAutoRefresh);
  $("#chat-form").addEventListener("submit", submitChat);
  $("#clear-log-filters").addEventListener("click", clearLogFilters);
  $("#log-query").addEventListener("input", debounce(() => {
    state.logCorrelationId = "";
    loadLogs();
  }));
  $("#log-event").addEventListener("change", loadLogs);
  $("#log-level").addEventListener("change", loadLogs);
  $("[role='tablist']").addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    const tabs = $$(".view-tab");
    const current = tabs.indexOf(document.activeElement);
    if (current < 0) return;
    event.preventDefault();
    let next = current;
    if (event.key === "ArrowRight") next = (current + 1) % tabs.length;
    if (event.key === "ArrowLeft") next = (current - 1 + tabs.length) % tabs.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = tabs.length - 1;
    tabs[next].focus();
    switchView(tabs[next].dataset.viewTarget);
  });
  window.addEventListener("resize", debounce(() => state.dashboard && renderDashboard(state.dashboard), 120));
  if (window.lucide) window.lucide.createIcons();
  configureAutoRefresh();
  refreshDashboard(true);
}

document.addEventListener("DOMContentLoaded", init);
