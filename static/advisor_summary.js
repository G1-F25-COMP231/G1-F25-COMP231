console.log("[advisor_summary.js] Loaded");

let lineChart;
let pieChart;

// Simple money formatter
function formatMoney(n) {
  const num = Number(n || 0);
  return `$${num.toFixed(2)}`;
}

document.addEventListener("DOMContentLoaded", () => {
  initAdvisorSummary();
});

/**
 * Initialize: load clients, hook up buttons, pre-select from URL if present.
 */
function initAdvisorSummary() {
  const loadBtn = document.getElementById("loadSummaryBtn");
  const timeFilter = document.getElementById("timeFilter");

  // Load advisor's clients into dropdown
  loadAdvisorClients().then(() => {
    // If page was opened from "View Summary" link, try to pre-select that client
    const params = new URLSearchParams(window.location.search);
    const clientParam = params.get("client"); // link id (from clients_col)

    const clientSelect = document.getElementById("clientSelect");
    if (clientParam && clientSelect) {
      const opt = clientSelect.querySelector(`option[value="${clientParam}"]`);
      if (opt) {
        clientSelect.value = clientParam;
        reloadSummary();
      }
    }
  });

  if (loadBtn) {
    loadBtn.addEventListener("click", () => {
      reloadSummary();
    });
  }

  if (timeFilter) {
    timeFilter.addEventListener("change", () => {
      const clientSelect = document.getElementById("clientSelect");
      if (clientSelect && clientSelect.value) {
        reloadSummary();
      }
    });
  }
}

/**
 * Fill <select id="clientSelect"> with advisor's clients.
 * Expects /api/advisor/clients to return { ok: true, clients: [ { _id, user_id, fullName, email, ... } ] }
 */
function loadAdvisorClients() {
  const clientSelect = document.getElementById("clientSelect");
  if (!clientSelect) return Promise.resolve();

  return fetch("/api/advisor/clients")
    .then((res) => res.json())
    .then((data) => {
      const clients = Array.isArray(data) ? data : data.clients || [];

      if (!Array.isArray(clients) || clients.length === 0) {
        clientSelect.innerHTML =
          '<option value="">No clients available</option>';
        return;
      }

      clientSelect.innerHTML = '<option value="">Select a client…</option>';

      clients.forEach((c) => {
        const opt = document.createElement("option");
        const name = c.full_name || c.fullName || "Unknown";
        const email = c.email || "";

        // value is the client-link id (clients_col _id)
        opt.value = c._id;
        // keep user_id in data attribute if we ever want it
        if (c.user_id) opt.dataset.userId = c.user_id;

        opt.textContent = email ? `${name} (${email})` : name;
        clientSelect.appendChild(opt);
      });
    })
    .catch((err) => {
      console.error("Error loading advisor clients:", err);
    });
}

/**
 * Load summary for selected client + time range.
 * If no Plaid data, show "No data available" in both chart cards.
 */
function reloadSummary() {
  const clientSelect = document.getElementById("clientSelect");
  const timeFilter = document.getElementById("timeFilter");

  if (!clientSelect || !clientSelect.value) {
    alert("Please select a client first.");
    return;
  }

  const clientLinkId = clientSelect.value; // clients_col _id
  const range = timeFilter ? timeFilter.value : "month";

  fetch(
    `/api/advisor/summary?client=${encodeURIComponent(
      clientLinkId
    )}&range=${encodeURIComponent(range)}`
  )
    .then((res) => res.json())
    .then((data) => {
      // If backend says no data (no Plaid), show the "No data" state
      if (!data || data.ok === false || data.hasData === false) {
        showNoDataState();
        return;
      }

      hideNoDataState();

      renderLineChart(data.income || [], data.expenses || [], data.labels || []);
      renderPieChart(data.categoryBreakdown || {});
      updateTransactionsTable(data.transactions || []);
    })
    .catch((err) => {
      console.error("Error loading summary:", err);
      showNoDataState();
    });
}

/* ==========================
   NO DATA STATE HANDLING
   ========================== */
function showNoDataState() {
  // Destroy charts if they exist
  if (lineChart) {
    lineChart.destroy();
    lineChart = null;
  }
  if (pieChart) {
    pieChart.destroy();
    pieChart = null;
  }

  const lineCanvas = document.getElementById("lineChart");
  const pieCanvas = document.getElementById("pieChart");
  const lineNoData = document.getElementById("lineChartNoData");
  const pieNoData = document.getElementById("pieChartNoData");

  if (lineCanvas) lineCanvas.style.display = "none";
  if (pieCanvas) pieCanvas.style.display = "none";
  if (lineNoData) lineNoData.style.display = "block";
  if (pieNoData) pieNoData.style.display = "block";

  const tbody = document.getElementById("clientTxTableBody");
  if (tbody) {
    tbody.innerHTML = `
      <tr>
        <td colspan="4" style="text-align:center; color:#b8c4d1;">
          No transactions available.
        </td>
      </tr>
    `;
  }
}

function hideNoDataState() {
  const lineCanvas = document.getElementById("lineChart");
  const pieCanvas = document.getElementById("pieChart");
  const lineNoData = document.getElementById("lineChartNoData");
  const pieNoData = document.getElementById("pieChartNoData");

  if (lineCanvas) lineCanvas.style.display = "block";
  if (pieCanvas) pieCanvas.style.display = "block";
  if (lineNoData) lineNoData.style.display = "none";
  if (pieNoData) pieNoData.style.display = "none";
}

/* ==========================
   LINE CHART
   ========================== */
function renderLineChart(income, expenses, labels) {
  const canvas = document.getElementById("lineChart");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  if (lineChart) lineChart.destroy();

  lineChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Income",
          data: income,
          borderColor: "#2afadf",
          backgroundColor: "rgba(42,250,223,0.15)",
          borderWidth: 3,
          tension: 0.3,
        },
        {
          label: "Expenses",
          data: expenses,
          borderColor: "#ff6b6b",
          backgroundColor: "rgba(255,107,107,0.15)",
          borderWidth: 3,
          tension: 0.3,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { labels: { color: "#fff" } },
      },
      scales: {
        x: {
          ticks: { color: "#ccc" },
          grid: { color: "rgba(255,255,255,0.06)" },
        },
        y: {
          ticks: { color: "#ccc" },
          grid: { color: "rgba(255,255,255,0.06)" },
        },
      },
    },
  });
}

/* ==========================
   PIE CHART
   ========================== */
function renderPieChart(breakdown) {
  const canvas = document.getElementById("pieChart");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  if (pieChart) pieChart.destroy();

  const labels = Object.keys(breakdown);
  const values = Object.values(breakdown);

  // If backend sent empty breakdown, show "No data" instead
  if (!labels.length) {
    showNoDataState();
    return;
  }

  hideNoDataState();

  pieChart = new Chart(ctx, {
    type: "pie",
    data: {
      labels,
      datasets: [
        {
          data: values,
          backgroundColor: [
            "#00ffff",
            "#00b3b3",
            "#38d9ff",
            "#4ce0d2",
            "#75f5e3",
            "#009999",
            "#66fff2",
            "#ff6b6b",
          ],
          borderColor: "#0a192f",
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { labels: { color: "#fff" } },
      },
    },
  });
}

/* ==========================
   TRANSACTIONS TABLE
   ========================== */
function updateTransactionsTable(transactions) {
  const tbody = document.getElementById("clientTxTableBody");
  if (!tbody) return;

  if (!transactions || !transactions.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="4" style="text-align:center; color:#b8c4d1;">
          No transactions available.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = transactions
    .map((tx) => {
      const date = tx.date || "";
      const merchant = tx.name || tx.merchant || "Unknown";
      const category = tx.category || "Other";
      const amt = Number(tx.amount || 0);
      const color = amt < 0 ? "#ff9f9f" : "#5df2a9";

      return `
        <tr>
          <td>${date}</td>
          <td>${merchant}</td>
          <td>${category}</td>
          <td style="color:${color};">
            ${formatMoney(amt)}
          </td>
        </tr>
      `;
    })
    .join("");
}
