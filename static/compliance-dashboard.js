// Sidebar toggle
const toggleBtn = document.getElementById("toggleSidebar");
const sidebar = document.getElementById("sidebar");

toggleBtn.addEventListener("click", () => {
  sidebar.classList.toggle("hidden");
});

// Risk Chart
const ctx = document.getElementById("riskChart");

new Chart(ctx, {
  type: "pie",
  data: {
    labels: ["Low", "Medium", "High", "Critical"],
    datasets: [{
      data: [48, 22, 18, 12],
      backgroundColor: [
        "#00ffff",
        "#ffd166",
        "#ff9f43",
        "#ff6b6b"
      ],
      borderColor: "#0a192f",
      borderWidth: 2
    }]
  },
  options: {
    plugins: {
      legend: {
        labels: { color:"#e0e6ed", font:{ size:14 } }
      }
    }
  }
});
