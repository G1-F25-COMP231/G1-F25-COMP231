console.log("[advisor_clients.js] Loaded");

document.addEventListener("DOMContentLoaded", () => {
  loadClients();
});

function loadClients() {
  fetch("/api/advisor/clients")
    .then(res => res.json())
    .then(data => {
      if (!Array.isArray(data)) {
        console.error("Invalid clients response:", data);
        return;
      }

      const tbody = document.getElementById("clientsTableBody");
      tbody.innerHTML = "";

      data.forEach(client => {
        const tr = document.createElement("tr");

        const priority = client.priority || "low";
        const tagClass =
          priority === "high" ? "priority-high"
            : priority === "medium" ? "priority-medium"
            : "priority-low";

        tr.innerHTML = `
          <td>${client.full_name || "Unknown"}</td>
          <td>${client.email}</td>
          <td>${client.status || "Active"}</td>
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
