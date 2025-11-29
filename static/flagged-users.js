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
    row.style.display = row.innerText.toLowerCase().includes(term) ? "" : "none";
  });
});

// Risk filter
const riskFilter = document.getElementById("riskFilter");

riskFilter.addEventListener("change", () => {
  const level = riskFilter.value;

  rows.forEach(row => {
    if (level === "all") {
      row.style.display = "";
      return;
    }

    const rowRisk = row.dataset.risk;
    row.style.display = (rowRisk === level) ? "" : "none";
  });
});
