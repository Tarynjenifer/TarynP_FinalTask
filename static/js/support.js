const API_BASE = "/api";

const alertBox = document.getElementById("alert-box");
const ticketListEl = document.getElementById("ticket-list");
const filterLevel = document.getElementById("filter-level");
const filterStatus = document.getElementById("filter-status");
const refreshBtn = document.getElementById("refresh-btn");

let allTickets = [];

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

function renderTickets() {
  const levelFilter = filterLevel.value;
  const statusFilter = filterStatus.value;

  let tickets = allTickets;
  if (levelFilter) tickets = tickets.filter((t) => t.assigned_level === levelFilter);
  if (statusFilter) tickets = tickets.filter((t) => t.status === statusFilter);

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
          ${t.assigned_agent_name ? `<span class="level-tag">${t.assigned_level}</span><br/>${escapeHtml(t.assigned_agent_name)}` : "Unassigned"}
          ${t.status === "OPEN" ? `<br/><button class="btn btn-ghost btn-sm section-gap" style="margin-top:6px;" data-resolve="${t.id}">Mark resolved</button>` : ""}
        </div>
      </div>`
    )
    .join("");

  document.querySelectorAll("[data-resolve]").forEach((btn) => {
    btn.addEventListener("click", () => resolveTicket(btn.getAttribute("data-resolve"), btn));
  });
}

async function loadTickets() {
  try {
    const levelParam = filterLevel.value ? `?level=${encodeURIComponent(filterLevel.value)}` : "";
    const statusParam = filterStatus.value ? `${levelParam ? "&" : "?"}status=${encodeURIComponent(filterStatus.value)}` : "";
    const res = await fetch(`${API_BASE}/support/tickets${levelParam}${statusParam}`);
    if (!res.ok) throw new Error("Failed to load tickets");
    allTickets = await res.json();
    renderTickets();
  } catch (err) {
    ticketListEl.innerHTML = `<div class="empty-state">Could not load tickets. Is the backend running?</div>`;
  }
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
    await loadTickets();
  } catch (err) {
    showAlert("error", "Could not reach the server.");
    btn.disabled = false;
    btn.textContent = "Mark resolved";
  }
}

filterLevel.addEventListener("change", loadTickets);
filterStatus.addEventListener("change", loadTickets);
refreshBtn.addEventListener("click", loadTickets);

loadTickets();
