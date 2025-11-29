// Sidebar toggle
const toggleBtn = document.getElementById("toggleSidebar");
const sidebar = document.getElementById("sidebar");

toggleBtn.addEventListener("click", () => {
  sidebar.classList.toggle("hidden");
});

// Search filter
const searchBox = document.getElementById("searchInput");
const rows = document.querySelectorAll(".flag-user-table tbody tr");

searchBox.addEventListener("input", () => {
  const term = searchBox.value.toLowerCase();
  rows.forEach(row => {
    const visible = row.innerText.toLowerCase().includes(term);
    row.style.display = visible ? "" : "none";
  });
});

// Risk filter
const riskFilter = document.getElementById("riskFilter");

riskFilter.addEventListener("change", () => {
  const level = riskFilter.value;

  rows.forEach(row => {
    const rowRisk = row.dataset.risk;

    const match =
      level === "all" ||
      rowRisk === level;

    row.style.display = match ? "" : "none";
  });
});

// Export CSV
document.querySelector(".export-btn").addEventListener("click", () => {
  let csv = "User ID,Name,Email,Flagged Tx,Risk,Last Activity\n";

  rows.forEach(row => {
    const cols = row.querySelectorAll("td");
    const line = Array.from(cols).map(td => td.innerText).join(",");
    csv += line + "\n";
  });

  const blob = new Blob([csv], { type: "text/csv" });
  const url = window.URL.createObjectURL(blob);

  const a = document.createElement("a");
  a.href = url;
  a.download = "flagged-users.csv";
  a.click();
});

document.querySelectorAll(".view-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    const userId = btn.getAttribute("data-user");
    window.location.href = `/compliance/user/${userId}`;
  });
});
