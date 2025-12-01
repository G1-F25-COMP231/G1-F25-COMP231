// Sidebar toggle
const btn = document.getElementById("toggleSidebar");
const sidebar = document.getElementById("sidebar");

btn.addEventListener("click", () => {
  sidebar.classList.toggle("hidden");
});

