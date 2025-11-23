console.log("[advisor_summary.js] Loaded");

let lineChart;
let pieChart;

document.addEventListener("DOMContentLoaded", () => {
  reloadSummary();
});

function reloadSummary() {
  const filter = document.getElementById("timeFilter").value;
  const clientId = new URLSearchParams(window.location.search).get("client");

  fetch(`/api/advisor/summary?client=${clientId}&range=${filter}`)
    .then(res => res.json())
    .then(data => {
      if (!data) {
        console.error("No summary data received.");
        return;
      }

      renderLineChart(data.income, data.expenses, data.labels);
      renderPieChart(data.categoryBreakdown);
    })
    .catch(err => console.error("Error loading summary:", err));
}

/* ==========================
   LINE CHART
   ========================== */
function renderLineChart(income, expenses, labels) {
  const ctx = document.getElementById("lineChart").getContext("2d");

  if (lineChart) lineChart.destroy();

  lineChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Income",
          data: income,
          borderWidth: 3,
          tension: 0.3
        },
        {
          label: "Expenses",
          data: expenses,
          borderWidth: 3,
          tension: 0.3
        }
      ]
    },
    options: {
      responsive: true,
      plugins: {
        legend: { labels: { color: "#fff" } }
      },
      scales: {
        x: { ticks: { color: "#ccc" } },
        y: { ticks: { color: "#ccc" } }
      }
    }
  });
}

/* ==========================
   PIE CHART
   ========================== */
function renderPieChart(breakdown) {
  const ctx = document.getElementById("pieChart").getContext("2d");

  if (pieChart) pieChart.destroy();

  pieChart = new Chart(ctx, {
    type: "pie",
    data: {
      labels: Object.keys(breakdown),
      datasets: [
        {
          data: Object.values(breakdown)
        }
      ]
    },
    options: {
      responsive: true,
      plugins: {
        legend: { labels: { color: "#fff" } }
      }
    }
  });
}
