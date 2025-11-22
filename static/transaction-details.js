// Sidebar toggle
const toggleBtnTD = document.getElementById("toggleSidebar");
const sidebarTD = document.getElementById("sidebar");

if (toggleBtnTD && sidebarTD) {
  toggleBtnTD.addEventListener("click", () => {
    sidebarTD.classList.toggle("hidden");
  });
}

function formatAmtTD(n) {
  const num = Number(n || 0);
  const f = Math.abs(num).toFixed(2);
  return num < 0 ? `-$${f}` : `$${f}`;
}

const txListBody = document.getElementById("txList");

// Detail card elements
const merchantNameEl = document.getElementById("merchantName");
const amountEl = document.getElementById("amount");
const dateEl = document.getElementById("date");
const categoryEl = document.getElementById("category");
const currencyEl = document.getElementById("currency");
const txidEl = document.getElementById("txid");
const notesEl = document.getElementById("notes");

function showTxDetail(tx) {
  if (!tx) return;

  const merchant = tx.name || "Unknown merchant";
  const category = tx.category || "Uncategorized";
  const dateStr = tx.date || "—";
  const iso = tx.iso_currency_code || "—";

  // Use signed_amount if present, otherwise fall back to amount
  const signed =
    typeof tx.signed_amount === "number"
      ? tx.signed_amount
      : Number(tx.amount || 0);

  merchantNameEl.textContent = merchant;
  amountEl.textContent = formatAmtTD(signed);
  amountEl.classList.toggle("negative", signed < 0);
  amountEl.classList.toggle("positive", signed >= 0);

  dateEl.textContent = dateStr;
  categoryEl.textContent = category;
  currencyEl.textContent = iso;
  txidEl.textContent = tx.transaction_id || "—";

  notesEl.textContent =
    signed < 0
      ? "This looks like an expense from your linked account."
      : "This looks like income flowing into your linked account.";
}

async function loadTransactionsPage() {
  try {
    const res = await fetch("/api/transactions?limit=50");
    const data = await res.json();

    const txs = (data && data.transactions) || [];
    if (!txs.length) {
      txListBody.innerHTML = `
        <tr>
          <td colspan="4" style="text-align:center;color:#8091a3;">
            No transactions found. Connect a bank account first.
          </td>
        </tr>
      `;
      return;
    }

    // Render rows
    txListBody.innerHTML = txs
      .map((tx) => {
        const date = tx.date || "";
        const merchant = tx.name || "Unknown";
        const category = tx.category || "";
        const signed =
          typeof tx.signed_amount === "number"
            ? tx.signed_amount
            : Number(tx.amount || 0);

        return `
          <tr data-txid="${tx.transaction_id || ""}">
            <td>${date}</td>
            <td>${merchant}</td>
            <td>${category}</td>
            <td style="color:${signed < 0 ? "#ff9f9f" : "#5df2a9"}">
              ${formatAmtTD(signed)}
            </td>
          </tr>
        `;
      })
      .join("");

    // Click handler to update detail card
    txListBody.addEventListener("click", (e) => {
      const row = e.target.closest("tr[data-txid]");
      if (!row) return;
      const txId = row.getAttribute("data-txid");
      const tx = txs.find((t) => t.transaction_id === txId);
      if (tx) showTxDetail(tx);
    });

    // If query string has ?txid=..., pre-select that
    const params = new URLSearchParams(window.location.search);
    const wantedId = params.get("txid");

    if (wantedId) {
      const found = txs.find((t) => t.transaction_id === wantedId);
      if (found) {
        showTxDetail(found);
        return;
      }
    }

    // Otherwise default to first tx
    showTxDetail(txs[0]);
  } catch (err) {
    console.error("[transaction-details] Failed to load transactions:", err);
    txListBody.innerHTML = `
      <tr>
        <td colspan="4" style="text-align:center;color:#8091a3;">
          Failed to load transactions.
        </td>
      </tr>
    `;
  }
}

document.addEventListener("DOMContentLoaded", loadTransactionsPage);
