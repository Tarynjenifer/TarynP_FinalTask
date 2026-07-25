/* customer.js — Raise Ticket form + ticket lookup list */

const API_BASE = "/api";

const form = document.getElementById("ticket-form");
const submitBtn = document.getElementById("submit-btn");
const alertBox = document.getElementById("alert-box");
const ticketListEl = document.getElementById("ticket-list");
const filterEmail = document.getElementById("filter-email");
const filterStatus = document.getElementById("filter-status");
const refreshBtn = document.getElementById("refresh-btn");

let allTickets = [];

// ---------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------
function showAlert(type, html) {
  alertBox.className = `alert alert-${type} show`;
  alertBox.innerHTML = html;
}

function hideAlert() {
  alertBox.className = "alert";
}

function clearFieldErrors() {
  document.querySelectorAll(".field").forEach((f) => f.classList.remove("invalid"));
}

function setFieldError(fieldName) {
  const field = document.querySelector(`.field[data-field="${fieldName}"]`);
  if (field) field.classList.add("invalid");
}

function isValidEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
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

// ---------------------------------------------------------------------
// Client-side validation
// ---------------------------------------------------------------------
function validateForm(data) {
  clearFieldErrors();
  let valid = true;

  if (!data.customer_name.trim()) {
    setFieldError("customer_name");
    valid = false;
  }
  if (!isValidEmail(data.customer_email.trim())) {
    setFieldError("customer_email");
    valid = false;
  }
  if (!data.title.trim()) {
    setFieldError("title");
    valid = false;
  }
  if (!data.description.trim()) {
    setFieldError("description");
    valid = false;
  }
  return valid;
}

// ---------------------------------------------------------------------
// Submit ticket
// ---------------------------------------------------------------------
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  hideAlert();

  const data = {
    customer_name: document.getElementById("customer_name").value,
    customer_email: document.getElementById("customer_email").value,
    customer_id: document.getElementById("customer_id").value || undefined,
    title: document.getElementById("title").value,
    description: document.getElementById("description").value,
    category: document.getElementById("category").value,
    channel: document.getElementById("channel").value,
    priority: document.querySelector('input[name="priority"]:checked').value,
  };

  if (!validateForm(data)) {
    showAlert("error", "Please fix the highlighted fields before submitting.");
    return;
  }

  submitBtn.disabled = true;
  submitBtn.innerHTML = '<span class="spinner"></span> Submitting…';

  try {
    const res = await fetch(`${API_BASE}/tickets`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });

    const body = await res.json();

    if (!res.ok) {
      const message = body.detail
        ? typeof body.detail === "string"
          ? body.detail
          : "Please check your input and try again."
        : "Something went wrong. Please try again.";
      showAlert("error", message);
      return;
    }

    showAlert(
      "success",
      `Ticket <span class="ticket-ref">#${body.id}</span> created and routed to
       <strong>${body.assigned_level || "an engineer"}</strong>${
        body.assigned_agent_name ? " — " + body.assigned_agent_name : ""
      }. A confirmation email has been sent to <strong>${body.customer_email}</strong>.`
    );
    form.reset();
    document.getElementById("p-low").checked = true;
    loadTickets();
  } catch (err) {
    showAlert("error", "Could not reach the server. Please confirm the backend is running.");
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Submit ticket";
  }
});

// ---------------------------------------------------------------------
// Ticket list / lookup
// ---------------------------------------------------------------------
function renderTickets() {
  const emailFilter = filterEmail.value.trim().toLowerCase();
  const statusFilter = filterStatus.value;

  let tickets = allTickets;
  if (emailFilter) {
    tickets = tickets.filter((t) => t.customer_email.toLowerCase().includes(emailFilter));
  }
  if (statusFilter) {
    tickets = tickets.filter((t) => t.status === statusFilter);
  }

  if (tickets.length === 0) {
    ticketListEl.innerHTML = `<div class="empty-state">No tickets found. Raise one using the form.</div>`;
    return;
  }

  ticketListEl.innerHTML = tickets
    .map(
      (t) => `
      <div class="ticket-row">
        <div class="ticket-id mono">#${t.id}</div>
        <div class="ticket-main">
          <div class="title">${escapeHtml(t.title)}</div>
          <div class="meta">
            ${escapeHtml(t.customer_name)} · ${escapeHtml(t.customer_email)} · ${formatDate(t.created_at)}
          </div>
          <div class="meta small">
            ${escapeHtml(t.category || "Other")} · ${escapeHtml(t.channel || "web_app")}
          </div>
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

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
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

filterEmail.addEventListener("input", renderTickets);
filterStatus.addEventListener("change", renderTickets);
refreshBtn.addEventListener("click", loadTickets);

loadTickets();
