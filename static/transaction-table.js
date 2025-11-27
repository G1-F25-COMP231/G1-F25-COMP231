// Sidebar toggle
const toggleBtn = document.getElementById("toggleSidebar");
const sidebar = document.getElementById("sidebar");

toggleBtn.addEventListener("click", () => {
  sidebar.classList.toggle("hidden");
});

// Live table search
const searchInput = document.getElementById("searchInput");
const rows = document.querySelectorAll(".tx-table tbody tr");

searchInput.addEventListener("input", () => {
  const term = searchInput.value.toLowerCase();

  rows.forEach(row => {
    const text = row.innerText.toLowerCase();
    row.style.display = text.includes(term) ? "" : "none";
  });
});
