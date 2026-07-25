/* admin.js — Admin dashboard: stats, priority breakdown, audit log, ticket management */

const API_BASE = "/api";

const alertBox = document.getElementById("alert-box");
const ticketListEl = document.getElementById("ticket-list");
const historyListEl = document.getElementById("history-list");
const categoryListEl = document.getElementById("category-list");
const workloadListEl = document.getElementById("workload-list");
const priorityBarsEl = document.getElementById("priority-bars");
const auditListEl = document.getElementById("audit-list");
const filterStatus = document.getElementById("filter-status");
const filterPriority = document.getElementById("filter-priority");
const refreshBtn = document.getElementById("refresh-btn");
const dailyReportBtn = document.getElementById("daily-report-btn");

let allTickets = [];

// ---------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------
function showAlert(type, html) {
  alertBox.className = `alert alert-${type} show`;
  alertBox.innerHTML = html;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function formatDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function priorityBadge(priority) {
  const cls = { LOW: "badge-low", MEDIUM: "badge-medium", HIGH: "badge-high" }[priority] || "";
  return `<span class="badge ${cls}">${priority}</span>`;
}

function statusBadge(status) {
  const cls = status === "RESOLVED" ? "badge-resolved" : "badge-open";
  return `<span class="badge ${cls}">${status}</span>`;
}

const ACTION_CLASS = {
  "Ticket Created": "action-created",
  "Ticket Assigned": "action-assigned",
  "Ticket Resolved": "action-resolved",
  "Assignment Failed": "action-high",
};

// ---------------------------------------------------------------------
// Dashboard stats
// ---------------------------------------------------------------------
async function loadStats() {
  try {
    const res = await fetch(`${API_BASE}/dashboard/stats?recent_logs=20`);
    if (!res.ok) throw new Error("Failed to load stats");
    const stats = await res.json();

    document.getElementById("stat-total").textContent = stats.total_tickets;
    document.getElementById("stat-open").textContent = stats.open_tickets;
    document.getElementById("stat-resolved").textContent = stats.resolved_tickets;

    const rate =
      stats.total_tickets > 0
        ? Math.round((stats.resolved_tickets / stats.total_tickets) * 100)
        : 0;
    document.getElementById("stat-rate").textContent = `${rate}%`;

    renderPriorityBars(stats.tickets_by_priority, stats.total_tickets);
    renderCategoryBreakdown(stats.tickets_by_category || {});
    renderAgentWorkload(stats.agent_workload || []);
    renderAuditLogs(stats.recent_audit_logs);
    renderHistory(stats.recent_tickets || []);
  } catch (err) {
    showAlert("error", "Could not load dashboard stats. Is the backend running?");
  }
}

function renderPriorityBars(byPriority, total) {
  const order = ["LOW", "MEDIUM", "HIGH"];
  const cls = { LOW: "low", MEDIUM: "medium", HIGH: "high" };

  priorityBarsEl.innerHTML = order
    .map((p) => {
      const count = byPriority[p] || 0;
      const pct = total > 0 ? Math.round((count / total) * 100) : 0;
      return `
        <div class="priority-bar-row">
          <div>${priorityBadge(p)}</div>
          <div class="priority-bar-track">
            <div class="priority-bar-fill ${cls[p]}" style="width:${pct}%"></div>
          </div>
          <div class="priority-bar-count">${count}</div>
        </div>`;
    })
    .join("");
}

function renderAuditLogs(logs) {
  if (!logs || logs.length === 0) {
    auditListEl.innerHTML = `<div class="empty-state">No audit activity yet.</div>`;
    return;
  }

  auditListEl.innerHTML = logs
    .map(
      (log) => `
      <div class="audit-row">
        <div class="ts mono">${formatDate(log.timestamp)}</div>
        <div class="tid">#${log.ticket_id}</div>
        <div class="action ${ACTION_CLASS[log.action] || ""}">${escapeHtml(log.action)}</div>
        <div class="details">${escapeHtml(log.details || "")}</div>
      </div>`
    )
    .join("");
}

// ---------------------------------------------------------------------
// Ticket management table
// ---------------------------------------------------------------------
function renderTickets() {
  const statusFilter = filterStatus.value;
  const priorityFilter = filterPriority.value;

  let tickets = allTickets;
  if (statusFilter) tickets = tickets.filter((t) => t.status === statusFilter);
  if (priorityFilter) tickets = tickets.filter((t) => t.priority === priorityFilter);

  if (tickets.length === 0) {
    ticketListEl.innerHTML = `<div class="empty-state">No tickets match these filters.</div>`;
    return;
  }

  ticketListEl.innerHTML = tickets
    .map(
      (t) => `
      <div class="ticket-row">
        <div class="ticket-id mono">#${t.id}</div>
        <div class="ticket-main">
          <div class="title">${escapeHtml(t.title)}</div>
          <div class="meta">${escapeHtml(t.customer_name)} · ${escapeHtml(t.customer_email)} · ${formatDate(t.created_at)}</div>
          <div class="meta small">${escapeHtml(t.category || "Other")} · ${escapeHtml(t.channel || "web_app")}</div>
        </div>
        <div>${priorityBadge(t.priority)}</div>
        <div>${statusBadge(t.status)}</div>
        <div class="ticket-assignee">
          ${
            t.assigned_agent_name
              ? `<span class="level-tag">${t.assigned_level}</span><br/>${escapeHtml(t.assigned_agent_name)}`
              : "Unassigned"
          }
          ${
            t.status === "OPEN"
              ? `<br/><button class="btn btn-ghost btn-sm section-gap" style="margin-top:6px;" data-resolve="${t.id}">Mark resolved</button>`
              : ""
          }
        </div>
      </div>`
    )
    .join("");

  document.querySelectorAll("[data-resolve]").forEach((btn) => {
    btn.addEventListener("click", () => resolveTicket(btn.getAttribute("data-resolve"), btn));
  });
}

async function resolveTicket(id, btn) {
  btn.disabled = true;
  btn.textContent = "Resolving…";
  try {
    const res = await fetch(`${API_BASE}/tickets/${id}/resolve`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const body = await res.json();
    if (!res.ok) {
      showAlert("error", body.detail || `Could not resolve ticket #${id}.`);
      btn.disabled = false;
      btn.textContent = "Mark resolved";
      return;
    }
    showAlert("success", `Ticket <span class="ticket-ref">#${id}</span> marked resolved. Customer notified.`);
    await loadAll();
  } catch (err) {
    showAlert("error", "Could not reach the server.");
    btn.disabled = false;
    btn.textContent = "Mark resolved";
  }
}

async function loadTickets() {
  try {
    const res = await fetch(`${API_BASE}/tickets`);
    if (!res.ok) throw new Error("Failed to load tickets");
    allTickets = await res.json();
    renderTickets();
  } catch (err) {
    ticketListEl.innerHTML = `<div class="empty-state">Could not load tickets. Is the backend running?</div>`;
  }
}

async function sendDailyReport() {
  try {
    dailyReportBtn.disabled = true;
    dailyReportBtn.textContent = "Sending…";
    const res = await fetch(`${API_BASE}/dashboard/daily-report`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    const body = await res.json();
    if (!res.ok) {
      showAlert("error", body.detail || "Could not send end-of-day report.");
      return;
    }
    showAlert("success", `End-of-day report sent to ${body.admin_email}.`);
  } catch (err) {
    showAlert("error", "Could not send end-of-day report.");
  } finally {
    dailyReportBtn.disabled = false;
    dailyReportBtn.textContent = "Send end-of-day report";
  }
}

function renderCategoryBreakdown(categories) {
  const rows = Object.entries(categories || {});
  if (rows.length === 0) {
    categoryListEl.innerHTML = `<div class="empty-state">No category data yet.</div>`;
    return;
  }

  categoryListEl.innerHTML = rows
    .map(
      ([category, count]) => `
      <div class="dashboard-item">
        <div>${escapeHtml(category)}</div>
        <div class="badge badge-low">${count}</div>
      </div>`
    )
    .join("");
}

function renderAgentWorkload(workload) {
  if (!workload || workload.length === 0) {
    workloadListEl.innerHTML = `<div class="empty-state">No agent workload data yet.</div>`;
    return;
  }

  workloadListEl.innerHTML = workload
    .map(
      (w) => `
      <div class="dashboard-item">
        <div>
          <strong>${escapeHtml(w.agent_name || "Unknown")}</strong><br />
          ${escapeHtml(w.assigned_level || "-")}
        </div>
        <div class="badge badge-medium">${w.open_tickets}</div>
      </div>`
    )
    .join("");
}

function renderHistory(tickets) {
  if (!tickets || tickets.length === 0) {
    historyListEl.innerHTML = `<div class="empty-state">No recent ticket history available.</div>`;
    return;
  }

  historyListEl.innerHTML = tickets
    .map(
      (t) => `
      <div class="ticket-row">
        <div class="ticket-id mono">#${t.id}</div>
        <div class="ticket-main">
          <div class="title">${escapeHtml(t.title)}</div>
          <div class="meta">${escapeHtml(t.customer_name)} · ${escapeHtml(t.customer_email)} · ${formatDate(t.created_at)}</div>
          <div class="meta small">${escapeHtml(t.category || "Other")} · ${escapeHtml(t.channel || "web_app")}</div>
        </div>
        <div>${priorityBadge(t.priority)}</div>
        <div>${statusBadge(t.status)}</div>
        <div class="ticket-assignee">
          ${
            t.assigned_agent_name
              ? `<span class="level-tag">${t.assigned_level}</span><br/>${escapeHtml(t.assigned_agent_name)}`
              : "Unassigned"
          }
        </div>
      </div>`
    )
    .join("");
}

async function loadAll() {
  await Promise.all([loadStats(), loadTickets()]);
}

filterStatus.addEventListener("change", renderTickets);
filterPriority.addEventListener("change", renderTickets);
dailyReportBtn.addEventListener("click", sendDailyReport);
refreshBtn.addEventListener("click", loadAll);

loadAll();
