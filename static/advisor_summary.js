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
    // Pre-select if ?client=<id>
    const params = new URLSearchParams(window.location.search);
    const clientParam = params.get("client");

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
 */
function loadAdvisorClients() {
  const clientSelect = document.getElementById("clientSelect");
  if (!clientSelect) return Promise.resolve();

  return fetch("/api/advisor/clients")
    .then((res) => res.json())
    .then((clients) => {
      clients = Array.isArray(clients) ? clients : [];

      if (!clients.length) {
        clientSelect.innerHTML =
          '<option value="">No clients available</option>';
        return;
      }

      clientSelect.innerHTML = '<option value="">Select a client…</option>';

      clients.forEach((c) => {
        const opt = document.createElement("option");
        const name = c.full_name || c.fullName || "Unknown";
        const email = c.email || "";

        opt.value = c._id; // client link id
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
 */
function reloadSummary() {
  const clientSelect = document.getElementById("clientSelect");
  const timeFilter = document.getElementById("timeFilter");

  if (!clientSelect || !clientSelect.value) {
    alert("Please select a client first.");
    return;
  }

  const clientLinkId = clientSelect.value;
  const range = timeFilter ? timeFilter.value : "month";

  // -------------------------
  // 1) Load main summary data
  // -------------------------
  fetch(
    `/api/advisor/summary?client=${encodeURIComponent(
      clientLinkId
    )}&range=${encodeURIComponent(range)}`
  )
    .then((res) => res.json())
    .then((data) => {
      if (!data || data.ok === false || data.hasData === false) {
        showNoDataState();
      } else {
        hideNoDataState();
        renderLineChart(data.income || [], data.expenses || [], data.labels || []);
        renderPieChart(data.categoryBreakdown || {});
        updateTransactionsTable(data.transactions || []);
      }
    })
    .catch((err) => {
      console.error("Error loading summary:", err);
      showNoDataState();
    });

  // -------------------------
  // 2) Check overspending
  // -------------------------
  checkOverspending(clientLinkId, range);

  // -------------------------
  // 3) Load alert summary
  // -------------------------
  loadAlertSummary(clientLinkId);
}

/* ==========================
   OVEREPENDING CHECK + BANNER
   ========================== */
function checkOverspending(linkId, timeFilter) {
  fetch("/api/advisor/check_overspending", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      client_id: linkId,
      time_filter: timeFilter,
    }),
  })
    .then((res) => res.json())
    .then((data) => {
      if (!data.ok) return;
      if (data.overspending) {
        showOverspendingBanner(data.total_spent, data.budget_limit);
      } else {
        hideOverspendingBanner();
      }
    })
    .catch((err) => console.error("Overspending error:", err));
}

function showOverspendingBanner(spent, limit) {
  const banner = document.getElementById("overspendingBanner");
  if (!banner) return;

  banner.innerHTML = `⚠️ Overspending Alert: Spent $${spent.toFixed(
    2
  )} (Limit: $${limit})`;
  banner.style.display = "block";
}

function hideOverspendingBanner() {
  const banner = document.getElementById("overspendingBanner");
  if (!banner) return;
  banner.style.display = "none";
}

/* ==========================
   ALERT SUMMARY MODULE
   ========================== */
function loadAlertSummary(clientLinkId) {
  fetch(`/api/advisor/alert_summary/${clientLinkId}`)
    .then((res) => res.json())
    .then((data) => {
      const tbody = document.getElementById("alertSummaryTableBody");
      if (!tbody) return;

      tbody.innerHTML = "";

      if (!data.alerts || !data.alerts.length) {
        tbody.innerHTML = `
          <tr>
            <td colspan="4" style="text-align:center; color:#b8c4d1;">
              No alerts recorded.
            </td>
          </tr>
        `;
        return;
      }

      data.alerts.forEach((a) => {
        const dateStr = new Date(a.timestamp).toLocaleDateString();
        const row = document.createElement("tr");
        row.innerHTML = `
          <td>${dateStr}</td>
          <td>${a.type}</td>
          <td>$${a.spent.toFixed(2)}</td>
          <td>$${a.limit.toFixed(2)}</td>
        `;
        tbody.appendChild(row);
      });
    })
    .catch((err) => console.error("Alert Summary Error:", err));
}

/* ==========================
   NO DATA STATE
   ========================== */
function showNoDataState() {
  if (lineChart) {
    lineChart.destroy();
    lineChart = null;
  }
  if (pieChart) {
    pieChart.destroy();
    pieChart = null;
  }

  document.getElementById("lineChart").style.display = "none";
  document.getElementById("pieChart").style.display = "none";
  document.getElementById("lineChartNoData").style.display = "block";
  document.getElementById("pieChartNoData").style.display = "block";

  document.getElementById("clientTxTableBody").innerHTML = `
    <tr>
      <td colspan="4" style="text-align:center; color:#b8c4d1;">
        No transactions available.
      </td>
    </tr>
  `;
}

function hideNoDataState() {
  document.getElementById("lineChart").style.display = "block";
  document.getElementById("pieChart").style.display = "block";
  document.getElementById("lineChartNoData").style.display = "none";
  document.getElementById("pieChartNoData").style.display = "none";
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
      plugins: { legend: { labels: { color: "#fff" } } },
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
      plugins: { legend: { labels: { color: "#fff" } } },
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
          <td style="color:${color};">${formatMoney(amt)}</td>
        </tr>
      `;
    })
    .join("");
}
