//-------------------------------------
// Sidebar Toggle
//-------------------------------------
const toggleBtn = document.getElementById("toggleSidebar");
const sidebar = document.getElementById("sidebar");

if (toggleBtn) {
  toggleBtn.addEventListener("click", () => {
    sidebar.classList.toggle("hidden");
  });
}

//-------------------------------------
// Live Search
//-------------------------------------
const searchInput = document.getElementById("searchInput");

if (searchInput) {
  searchInput.addEventListener("input", () => {
    const term = searchInput.value.toLowerCase();
    const rows = document.querySelectorAll(".tx-table tbody tr");

    rows.forEach(row => {
      const text = row.innerText.toLowerCase();
      row.style.display = text.includes(term) ? "" : "none";
    });
  });
}

//-------------------------------------
// Fetch Transactions + Render Table
//-------------------------------------
const tableBody = document.querySelector(".tx-table tbody");

async function loadTransactions() {
  try {
    const res = await fetch("/api/transactions?limit=200");
    const data = await res.json();

    const txs = data.transactions || [];

    if (!txs.length) {
      tableBody.innerHTML = `
        <tr>
          <td colspan="5" style="text-align:center;color:#8ea6c1;">
            No transactions available.
          </td>
        </tr>`;
      return;
    }

    renderRows(txs);
    autoFlagTransactions(txs);  // Story #72 — Flag Logic Auto-Run

  } catch (err) {
    console.error("Failed to load transactions:", err);
    tableBody.innerHTML = `
      <tr>
        <td colspan="5" style="text-align:center;color:#8ea6c1;">
          Failed to load transactions.
        </td>
      </tr>`;
  }
}

function renderRows(txs) {
  const rowHTML = txs
    .map((tx) => {
      const amount = Number(tx.amount).toFixed(2);
      const riskTag = detectRisk(tx);

      return `
        <tr>
          <td>${tx.date}</td>
          <td>${tx.name || "Unknown"}</td>
          <td>${tx.category || "Uncategorized"}</td>
          <td style="color:${tx.amount < 0 ? "#ff8080" : "#5df2a9"}">$${amount}</td>
          <td class="${riskTag.class}">${riskTag.label}</td>
        </tr>
      `;
    })
    .join("");

  tableBody.innerHTML = rowHTML;
}

//-------------------------------------
// Risk Detector (client-side mirror)
//-------------------------------------
function detectRisk(tx) {
  const amt = Number(tx.amount);
  const name = (tx.name || "").toLowerCase();

  if (amt >= 5000) return { label: "Critical", class: "risk-critical" };
  if (amt >= 2000) return { label: "High", class: "risk-high" };
  if (["crypto", "casino", "bet", "gamble"].some(k => name.includes(k)))
    return { label: "Critical", class: "risk-critical" };
  if (amt >= 500) return { label: "Medium", class: "risk-medium" };
  return { label: "Low", class: "risk-low" };
}

//-------------------------------------
// Auto-Flag All Transactions (Story #72)
//-------------------------------------
async function autoFlagTransactions(txs) {
  for (const tx of txs) {
    await fetch("/api/compliance/flag_transaction", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transaction: tx })
    });
  }
  console.log("Flag scan completed.");
}

//-------------------------------------
// Export Actions (CSV/PDF)
//-------------------------------------
document.getElementById("exportCSV").addEventListener("click", () => {
  window.location.href = "/api/compliance/export_csv";
});

document.getElementById("exportPDF").addEventListener("click", () => {
  window.location.href = "/api/compliance/export_pdf";
});

//-------------------------------------
// Start Page
//-------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  loadTransactions();
});
