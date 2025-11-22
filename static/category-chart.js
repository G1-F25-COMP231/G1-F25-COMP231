// Sidebar toggle
const toggleBtn = document.getElementById("toggleSidebar");
const sidebar = document.getElementById("sidebar");

toggleBtn.addEventListener("click", () => {
  sidebar.classList.toggle("hidden");
});

// -------------------------------
// Fetch Category Breakdown
// -------------------------------
async function loadCategoryData() {
  try {
    const res = await fetch("/api/category-breakdown");
    const breakdown = await res.json();

    if (!Array.isArray(breakdown)) {
      console.error("Invalid category data:", breakdown);
      return;
    }

    const labels = breakdown.map(x => x.category);
    const dataValues = breakdown.map(x => x.total);

    renderChart(labels, dataValues);
    updateSummary(breakdown);

  } catch (err) {
    console.error("Failed to load category breakdown:", err);
  }
}

// -------------------------------
// Render Chart.js Pie Chart
// -------------------------------
function renderChart(labels, dataValues) {
  const colors = [
    "#00ffff",
    "#00b3b3",
    "#38d9ff",
    "#4ce0d2",
    "#75f5e3",
    "#009999",
    "#66fff2"
  ];

  const ctx = document.getElementById("categoryChart");

  new Chart(ctx, {
    type: "pie",
    data: {
      labels: labels,
      datasets: [{
        label: "Spending",
        data: dataValues,
        backgroundColor: colors.slice(0, labels.length),
        borderColor: "#0a192f",
        borderWidth: 2,
      }]
    },
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
}

// -------------------------------
// Summary Section
// -------------------------------
function updateSummary(breakdown) {
  if (breakdown.length === 0) return;

  const highest = breakdown[0];
  const lowest = breakdown[breakdown.length - 1];

  document.getElementById("highestCategory").innerText =
    `${highest.category} ($${highest.total})`;

  document.getElementById("lowestCategory").innerText =
    `${lowest.category} ($${lowest.total})`;
}

loadCategoryData();
