// static/bank_connect.js

document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("bankConnectBtn");
  const statusText = document.getElementById("bankStatusText");
  const balanceText = document.getElementById("bankBalanceText");
  const txTable = document.getElementById("txTable"); // dashboard recent transactions table (if present)

  if (!btn || !statusText || !balanceText) {
    // Page doesn't have bank UI (e.g., only dashboard), still allow txTable updates if any
    setupPollingOnly();
    return;
  }

  let isConnected = false;

  async function refreshBank() {
    try {
      const res = await fetch("/api/bank/status");
      const data = await res.json();

      if (!data.ok) throw new Error(data.message || "Unknown error");

      if (!data.connected) {
        isConnected = false;
        btn.textContent = "Connect Sandbox Bank";
        statusText.textContent = "No bank connected.";
        balanceText.textContent = "--";
        btn.disabled = false;
        updateTransactionsTable(null);
        return;
      }

      isConnected = true;
      btn.textContent = "Disconnect Bank";
      statusText.textContent = "Sandbox bank connected.";
      const bal = Number(data.current_balance || 0);
      balanceText.textContent = `$${bal.toFixed(2)}`;

      updateTransactionsTable(data.recent_transactions || []);
      btn.disabled = false;
    } catch (err) {
      console.error("[bank_connect] refreshBank error:", err);
      statusText.textContent = "Unable to load bank status.";
      btn.disabled = false;
    }
  }

  async function handleClick() {
    btn.disabled = true;
    if (isConnected) {
      btn.textContent = "Disconnecting…";
      try {
        await fetch("/api/bank/disconnect", { method: "POST" });
      } catch (err) {
        console.error("[bank_connect] disconnect error:", err);
      }
      await refreshBank();
    } else {
      btn.textContent = "Connecting sandbox…";
      try {
        const res = await fetch("/api/bank/connect-sandbox", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        });
        const data = await res.json();
        if (!data.ok) {
          alert(data.message || "Failed to connect sandbox account.");
        }
      } catch (err) {
        console.error("[bank_connect] connect error:", err);
        alert("Network error while connecting sandbox bank.");
      }
      await refreshBank();
    }
  }

  function updateTransactionsTable(transactions) {
    if (!txTable) return; // this is only relevant on dashboard.html

    if (!transactions || transactions.length === 0) {
      txTable.innerHTML = `
        <tr>
          <td colspan="4" style="color:#a9bcd0;">No bank transactions yet.</td>
        </tr>`;
      return;
    }

    txTable.innerHTML = transactions
      .slice(0, 10) // just show a few
      .map((tx) => {
        const amt = Number(tx.amount || 0);
        const color = amt < 0 ? "#ff9f9f" : "#5df2a9";
        const sign = amt < 0 ? "-" : "";
        const val = Math.abs(amt).toFixed(2);
        const date = tx.date || "";
        const name = tx.name || "Unknown";
        const category = tx.category || "Other";
        return `
          <tr>
            <td>${date}</td>
            <td>${name}</td>
            <td>${category}</td>
            <td style="color:${color}">${sign}$${val}</td>
          </tr>`;
      })
      .join("");
  }

  function setupPollingOnly() {
    // Called on pages that *only* have the txTable (e.g. dashboard) but no button UI.
    if (!txTable) return;
    const poll = async () => {
      try {
        const res = await fetch("/api/bank/status");
        const data = await res.json();
        if (data.ok && data.connected) {
          updateTransactionsTable(data.recent_transactions || []);
        }
      } catch (err) {
        console.error("[bank_connect] polling error:", err);
      }
    };
    // initial load + repeat every 10 minutes
    poll();
    setInterval(poll, 10 * 60 * 1000);
  }

  // ===== INITIALISATION =====
  if (btn) {
    btn.addEventListener("click", handleClick);
    // initial status + 10-min polling
    refreshBank();
    setInterval(refreshBank, 10 * 60 * 1000);
  } else {
    setupPollingOnly();
  }
});
