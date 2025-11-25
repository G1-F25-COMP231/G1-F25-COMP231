console.log("[advisor-settings.js] Loaded");

// ===============================
// DOM ELEMENT REFERENCES (SAFE)
// ===============================
const sidebar = document.getElementById("sidebar");
const toggleSidebarBtn = document.getElementById("toggleSidebar");

const clientSelect = document.getElementById("clientSelect");

const totalBudget = document.getElementById("totalBudget");
const groceries = document.getElementById("groceries");
const dining = document.getElementById("dining");
const transport = document.getElementById("transport");
const bills = document.getElementById("bills");

const viewOverview = document.getElementById("viewOverview");
const viewCategory = document.getElementById("viewCategory");
const viewSavings = document.getElementById("viewSavings");
const viewAI = document.getElementById("viewAI");
const viewBills = document.getElementById("viewBills");

const advisorNotes = document.getElementById("advisorNotes");
const saveBtn = document.getElementById("saveBtn");

// ===============================
// SIDEBAR TOGGLE
// ===============================
toggleSidebarBtn?.addEventListener("click", () => {
  sidebar?.classList.toggle("hidden");
});

// ===============================
// PAGE READY
// ===============================
document.addEventListener("DOMContentLoaded", () => {
  console.log("[advisor-settings.js] DOM Ready");
  loadClients();

  if (clientSelect) {
    clientSelect.addEventListener("change", () => {
      if (clientSelect.value) {
        loadClientSettings(clientSelect.value);
      }
    });
  }
});

// ===============================
// LOAD ALL CLIENTS
// ===============================
function loadClients() {
  fetch("/api/advisor/clients")
    .then(res => res.json())
    .then(data => {
      if (!data.ok) {
        console.error("Error loading clients:", data);
        return;
      }

      clientSelect.innerHTML = `<option value="">Select a client...</option>`;

      data.clients.forEach(c => {
        const opt = document.createElement("option");
        opt.value = c._id;
        opt.textContent = `${c.full_name} (${c.email})`;
        clientSelect.appendChild(opt);
      });
    })
    .catch(err => console.error("Network error loading clients:", err));
}

// ===============================
// LOAD SETTINGS FOR SELECTED CLIENT
// ===============================
function loadClientSettings(client_id) {
  fetch(`/api/advisor/get_client_settings/${client_id}`)
    .then(res => res.json())
    .then(data => {
      if (!data.ok) {
        console.error("Error loading client settings:", data);
        return;
      }

      const s = data.settings || {};

      totalBudget.value = s.total_budget || "";

      groceries.value = s.categories?.groceries || "";
      dining.value = s.categories?.dining || "";
      transport.value = s.categories?.transport || "";
      bills.value = s.categories?.bills || "";

      viewOverview.checked = s.dashboard?.overview ?? true;
      viewCategory.checked = s.dashboard?.category ?? true;
      viewSavings.checked = s.dashboard?.savings ?? true;
      viewAI.checked = s.dashboard?.ai ?? false;
      viewBills.checked = s.dashboard?.bills ?? false;

      advisorNotes.value = s.notes || "";
    })
    .catch(err => console.error("Network error loading settings:", err));
}

// ===============================
// SAVE SETTINGS BUTTON
// ===============================
saveBtn?.addEventListener("click", () => {
  if (!clientSelect.value) return alert("Please select a client first.");

  const payload = {
    client_id: clientSelect.value,
    total_budget: Number(totalBudget.value),
    categories: {
      groceries: Number(groceries.value),
      dining: Number(dining.value),
      transport: Number(transport.value),
      bills: Number(bills.value)
    },
    dashboard: {
      overview: viewOverview.checked,
      category: viewCategory.checked,
      savings: viewSavings.checked,
      ai: viewAI.checked,
      bills: viewBills.checked
    },
    notes: advisorNotes.value
  };

  fetch("/api/advisor/save_client_settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  })
    .then(res => res.json())
    .then(data => {
      if (data.ok) {
        alert("✔ Client settings saved!");
      } else {
        alert("❌ Error saving: " + data.message);
      }
    })
    .catch(err => {
      console.error("Save error:", err);
      alert("❌ Network error saving settings");
    });
});
