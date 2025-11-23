console.log("[advisor_clients.js] Loaded");

document.addEventListener("DOMContentLoaded", () => {
  initAddClientModal();
  loadClients();
});

/* ==========================================
   LOAD CLIENT LIST
   ========================================== */
function loadClients() {
  fetch("/api/advisor/clients")
    .then(res => res.json())
    .then(data => {
      // Support either: [ {...} ] or { ok: true, clients: [ {...} ] }
      const clients = Array.isArray(data) ? data : (data.clients || []);

      if (!Array.isArray(clients)) {
        console.error("Invalid clients response:", data);
        return;
      }

      const tbody = document.getElementById("clientsTableBody");
      if (!tbody) {
        console.error("#clientsTableBody not found");
        return;
      }

      tbody.innerHTML = "";

      clients.forEach(client => {
        const tr = document.createElement("tr");

        const priorityRaw = client.priority || "low";
        const priority = String(priorityRaw).toLowerCase();
        const status = client.status || "Pending";

        const tagClass =
          priority === "high" ? "priority-high" :
          priority === "medium" ? "priority-medium" :
          "priority-low";

        tr.innerHTML = `
          <td>${client.full_name || client.fullName || "Unknown"}</td>
          <td>${client.email || ""}</td>
          <td>${status}</td>
          <td><span class="priority-tag ${tagClass}">${priority}</span></td>
          <td>
            <button class="view-btn" onclick="viewClientSummary('${client._id}')">
              View Summary
            </button>
          </td>
        `;

        tbody.appendChild(tr);
      });
    })
    .catch(err => console.error("Error loading clients:", err));
}

function viewClientSummary(id) {
  window.location.href = `/advisor_summary?client=${id}`;
}

/* ==========================================
   ADD CLIENT MODAL
   ========================================== */
function initAddClientModal() {
  const openBtn = document.getElementById("addClientBtn");
  const modal = document.getElementById("addClientModal");
  const form = document.getElementById("addClientForm");
  const emailInput = document.getElementById("addClientEmail");
  const cancelBtn = document.getElementById("cancelAddClientBtn");
  const messageEl = document.getElementById("addClientMessage");

  if (!openBtn || !modal || !form || !emailInput || !cancelBtn || !messageEl) {
    console.warn("[advisor_clients.js] Modal elements not found");
    return;
  }

  const openModal = () => {
    modal.style.display = "flex";
    messageEl.textContent = "";
    messageEl.style.color = "#b8c4d1";
    emailInput.value = "";
    emailInput.focus();
  };

  const closeModal = () => {
    modal.style.display = "none";
  };

  openBtn.addEventListener("click", e => {
    e.preventDefault();
    openModal();
  });

  cancelBtn.addEventListener("click", e => {
    e.preventDefault();
    closeModal();
  });

  // Close when clicking backdrop
  modal.addEventListener("click", e => {
    if (e.target === modal) {
      closeModal();
    }
  });

  form.addEventListener("submit", e => {
    e.preventDefault();
    const email = emailInput.value.trim();
    if (!email) return;

    messageEl.textContent = "Sending...";
    messageEl.style.color = "#b8c4d1";

    fetch("/api/advisor/add_client", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email })
    })
      .then(res => res.json())
      .then(data => {
        if (!data.ok) {
          messageEl.textContent =
            data.message || "No user with that email was found.";
          messageEl.style.color = "#ff6b6b"; // error color
          return;
        }

        messageEl.textContent =
          data.message || "Successfully sent to client.";
        messageEl.style.color = "#6bff95"; // success color

        // Short delay then close + refresh list
        setTimeout(() => {
          closeModal();
          loadClients();
        }, 600);
      })
      .catch(err => {
        console.error("Error adding client:", err);
        messageEl.textContent = "Something went wrong. Please try again.";
        messageEl.style.color = "#ff6b6b";
      });
  });
}
