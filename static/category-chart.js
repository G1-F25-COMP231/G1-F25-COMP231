// Sidebar toggle
const toggleBtn = document.getElementById("toggleSidebar");
const sidebar = document.getElementById("sidebar");

toggleBtn.addEventListener("click", () => {
  sidebar.classList.toggle("hidden");
});

// Example data
const data = {
  labels: ["Dining", "Groceries", "Transport", "Bills", "Shopping"],
  datasets: [{
    label: "Spending",
    data: [412, 280, 54, 190, 120],
    backgroundColor: [
      "#00ffff",
      "#00b3b3",
      "#38d9ff",
      "#4ce0d2",
      "#75f5e3"
    ],
    borderColor: "#0a192f",
    borderWidth: 2,
  }]
};

const ctx = document.getElementById("categoryChart");
new Chart(ctx, {
  type: "pie",
  data: data,
  options: {
    responsive: true,
    plugins: {
      legend: {
        labels: {
          color: "#e0e6ed",
          font: { size: 14 }
        }
      }
    }
  }
});

// Summary calculations (static example)
document.getElementById("highestCategory").innerText = "Dining ($412)";
document.getElementById("lowestCategory").innerText = "Transport ($54)";
