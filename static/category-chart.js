// ============================
// SIDEBAR TOGGLE
// ============================
const toggleBtn = document.getElementById("toggleSidebar");
const sidebar = document.getElementById("sidebar");

if (toggleBtn) {
  toggleBtn.addEventListener("click", () => {
    sidebar.classList.toggle("hidden");
  });
}

// ============================
// LOAD CATEGORY BREAKDOWN
// ============================
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

    renderCategoryChart(labels, dataValues);
    updateSummary(breakdown);

  } catch (err) {
    console.error("Failed to load category breakdown:", err);
  }
}

// ============================
// RENDER PIE CHART (Chart.js)
// ============================
let categoryChartInstance = null;

function renderCategoryChart(labels, dataValues) {
  const ctx = document.getElementById("dashboardCategoryChart");

  if (!ctx) {
    console.error("Canvas #dashboardCategoryChart not found");
    return;
  }

  // Destroy previous chart to avoid duplicates
  if (categoryChartInstance) {
    categoryChartInstance.destroy();
  }

  const colors = [
    "#00ffff",
    "#00b3b3",
    "#38d9ff",
    "#4ce0d2",
    "#75f5e3",
    "#009999",
    "#66fff2"
  ];

  categoryChartInstance = new Chart(ctx, {
    type: "pie",
    data: {
      labels: labels,
      datasets: [
        {
          label: "Spending",
          data: dataValues,
          backgroundColor: colors.slice(0, labels.length),
          borderColor: "#0a192f",
          borderWidth: 2,
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false, // 🔥 Prevent giant overflow
      plugins: {
        legend: {
          position: "top",
          labels: {
            color: "#e0e6ed",
            font: { size: 13 }
          }
        }
      },
      layout: {
        padding: 10
      }
    }
  });
}

// ============================
// SUMMARY (HIGHEST/LOWEST)
// ============================
function updateSummary(breakdown) {
  if (breakdown.length === 0) return;

  const highest = breakdown[0];
  const lowest = breakdown[breakdown.length - 1];

  const highestEl = document.getElementById("highestCategory");
  const lowestEl = document.getElementById("lowestCategory");

  if (highestEl)
    highestEl.innerText = `${highest.category} ($${highest.total})`;

  if (lowestEl)
    lowestEl.innerText = `${lowest.category} ($${lowest.total})`;
}

// ============================
// INIT
// ============================
loadCategoryData();
