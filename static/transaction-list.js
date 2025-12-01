document.addEventListener("DOMContentLoaded", () => {
    loadTransactions();
    loadSummary();
    loadAlerts();
});

// -----------------------------
// Fetch Recent Transactions
// -----------------------------
async function loadTransactions() {
    const container = document.querySelector(".list-card");

    try {
        const res = await fetch("/api/transactions");
        const data = await res.json();

        if (!data.ok || !data.transactions) {
            container.innerHTML += "<p>No transactions found.</p>";
            return;
        }

        const txList = data.transactions;

        // Clear fake placeholder transactions
        container.innerHTML = `
            <h2 class="card__title">Recent Transactions</h2>
        `;

        txList.forEach(tx => {
            const amount = parseFloat(tx.amount || 0);
            const isIncome = amount > 0;

            const txDiv = document.createElement("div");
            txDiv.className = "transaction";

            txDiv.innerHTML = `
                <div class="tx-info">
                    <div class="tx-icon">${getIcon(tx.name)}</div>
                    <div>
                        <div class="tx-merchant">${tx.name}</div>
                        <div class="tx-date">${formatDate(tx.date)}</div>
                    </div>
                </div>
                <div class="tx-amount ${isIncome ? "green" : "red"}">
                    ${isIncome ? "+" : "-"}$${Math.abs(amount).toFixed(2)}
                </div>
            `;

            container.appendChild(txDiv);
        });

    } catch (err) {
        console.error("Transaction Load Error:", err);
    }
}

// -----------------------------
// Fetch Summary (week + month)
// -----------------------------
async function loadSummary() {
    const weekEl = document.querySelector(".summary-bar .summary-value");
    const monthEl = document.querySelectorAll(".summary-value")[1];

    try {
        const res = await fetch("/api/summary");
        const data = await res.json();

        if (!data) return;

        const income = data.income || 0;
        const expense = data.expense || 0;

        // Simple mock weekly calculation — uses 25% of monthly spending
        const weeklyExpense = (expense * 0.25).toFixed(2);

        weekEl.textContent = `$${weeklyExpense}`;
        monthEl.textContent = `$${expense.toFixed(2)}`;

    } catch (err) {
        console.error("Summary Load Error:", err);
    }
}

// -----------------------------
// Fetch Alerts
// -----------------------------
async function loadAlerts() {
    const list = document.querySelector(".alerts-list");
    list.innerHTML = ""; // clear placeholders

    try {
        const res = await fetch("/api/notifications");
        const data = await res.json();

        if (!data.ok) return;

        const items = data.notifications;

        if (items.length === 0) {
            list.innerHTML = "<li>No alerts yet.</li>";
            return;
        }

        items.forEach(n => {
            const li = document.createElement("li");
            li.innerHTML = `🔔 ${n.message}`;
            list.appendChild(li);
        });

    } catch (err) {
        console.error("Alerts Load Error:", err);
    }
}

// -----------------------------
// Helpers
// -----------------------------

function formatDate(dateStr) {
    const date = new Date(dateStr);
    return date.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric"
    });
}

function getIcon(name) {
    if (!name) return "💳";
    name = name.toLowerCase();

    if (name.includes("mcdonald")) return "🍔";
    if (name.includes("starbucks")) return "☕";
    if (name.includes("uber")) return "🚗";
    if (name.includes("walmart")) return "🛒";
    if (name.includes("shell")) return "⛽";
    if (name.includes("spotify")) return "🎶";
    if (name.includes("amazon")) return "📦";

    return "💳";
}
