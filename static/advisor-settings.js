// Sidebar toggle
const toggleBtn = document.getElementById("toggleSidebar");
const sidebar = document.getElementById("sidebar");

toggleBtn.addEventListener("click", () => {
  sidebar.classList.toggle("hidden");
});

// Save client settings
document.getElementById("saveBtn").addEventListener("click", () => {
  alert("✅ Client settings saved successfully!");
});
