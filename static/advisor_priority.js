console.log("[advisor_priority.js] Loaded");

let selectedPriority = null;
let advisorClients = []; // cache of /api/advisor/clients

document.addEventListener("DOMContentLoaded", () => {
  initPriorityPage();
});

/**
 * Initialize page:
 * - set up priority option click handlers
 * - load advisor clients into dropdown
 */
function initPriorityPage() {
  // Hook up click handlers for priority options
  document.querySelectorAll(".priority-option").forEach((opt) => {
    opt.addEventListener("click", () => {
      selectedPriority = opt.dataset.level;

      document
        .querySelectorAll(".priority-option")
        .forEach((o) => o.classList.remove("selected"));

      opt.classList.add("selected");
    });
  });

  // Load advisor clients into select
  loadAdvisorClientsIntoDropdown();
}

/**
 * Fill <select id="clientSelect"> with the advisor's clients.
 * Uses /api/advisor/clients (same as advisor_summary.js).
 */
function loadAdvisorClientsIntoDropdown() {
  const clientSelect = document.getElementById("clientSelect");
  if (!clientSelect) return;

  fetch("/api/advisor/clients")
    .then((res) => res.json())
    .then((data) => {
      const clients = Array.isArray(data) ? data : data.clients || [];

      advisorClients = clients; // keep for later (to read existing priority)

      if (!Array.isArray(clients) || clients.length === 0) {
        clientSelect.innerHTML =
          '<option value="">No clients available</option>';
        return;
      }

      clientSelect.innerHTML = '<option value="">Select a client…</option>';

      clients.forEach((c) => {
        const opt = document.createElement("option");
        const name = c.full_name || c.fullName || "Unknown";
        const email = c.email || "";
        const priorityRaw = (c.priority || "low").toString().toLowerCase();

        opt.value = c._id; // clients_col _id (link id)
        opt.dataset.priority = priorityRaw;
        opt.textContent = email ? `${name} (${email})` : name;

        clientSelect.appendChild(opt);
      });

      // When the selected client changes, reflect their current priority in the UI
      clientSelect.addEventListener("change", (e) => {
        const selectedOpt = e.target.selectedOptions[0];
        if (!selectedOpt || !selectedOpt.dataset.priority) {
          clearPrioritySelection();
          return;
        }
        const currentPriority = selectedOpt.dataset.priority;
        applyPrioritySelection(currentPriority);
      });
    })
    .catch((err) => {
      console.error("[advisor_priority] Error loading clients:", err);
    });
}

/**
 * Clears the visual selection of priority options.
 */
function clearPrioritySelection() {
  selectedPriority = null;
  document
    .querySelectorAll(".priority-option")
    .forEach((o) => o.classList.remove("selected"));
}

/**
 * Visually selects the given priority ("low" | "medium" | "high")
 * and sets selectedPriority.
 */
function applyPrioritySelection(priorityLevel) {
  const level = (priorityLevel || "").toLowerCase();
  selectedPriority = level;

  document
    .querySelectorAll(".priority-option")
    .forEach((o) => o.classList.remove("selected"));

  const match = document.querySelector(
    `.priority-option[data-level="${level}"]`
  );
  if (match) {
    match.classList.add("selected");
  }
}

/**
 * Called from the "Save Priority" button in the HTML.
 * Sends the chosen priority + selected client to /api/advisor/set_priority.
 */
async function savePriority() {
  console.log("[advisor_priority] Save clicked. Selected:", selectedPriority);

  const clientSelect = document.getElementById("clientSelect");
  if (!clientSelect || !clientSelect.value) {
    alert("Please select a client first.");
    return;
  }

  if (!selectedPriority) {
    alert("Please choose a priority level first.");
    return;
  }

  const clientId = clientSelect.value; // clients_col _id

  try {
    const res = await fetch("/api/advisor/set_priority", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        client_id: clientId,
        priority: selectedPriority,
      }),
    });

    const data = await res.json();
    console.log("[advisor_priority] Server response:", data);

    if (!data.ok) {
      alert(data.message || "Failed to update priority.");
      return;
    }

    alert("Priority updated!");
  } catch (err) {
    console.error("[advisor_priority] Network/Server error:", err);
    alert("Error updating priority. Please try again.");
  }
}
