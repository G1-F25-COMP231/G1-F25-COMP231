// =======================
// Sidebar toggle for mobile
// =======================
const toggleBtn = document.getElementById("toggleSidebar");
const sidebar = document.getElementById("sidebar");

if (toggleBtn && sidebar) {
  toggleBtn.addEventListener("click", () => {
    if (window.innerWidth <= 880) {
      sidebar.classList.toggle("show");
    } else {
      sidebar.classList.toggle("hidden");
    }
  });
}

// =======================
// Simple money formatter
// =======================
function formatMoney(n) {
  return `$${Number(n || 0).toFixed(2)}`;
}

// ============================
// Load Advisor Notes (Read-Only)
// ============================
async function loadAdvisorNotes() {
  const container = document.getElementById("advisorNotesView");
  if (!container) return;

  try {
    const res = await fetch("/api/user/advisor_notes");
    const data = await res.json();

    if (!data.ok) {
      container.innerHTML = `<p class="placeholder">Unable to load advisor notes.</p>`;
      return;
    }

    if (!data.notes || data.notes.length === 0) {
      container.innerHTML = `<p class="placeholder">No notes from your advisor yet.</p>`;
      return;
    }

    container.innerHTML = data.notes
      .map(
        (n) => `
        <div class="note-item">
          <div><strong>${n.advisor}</strong></div>
          <div>${n.note}</div>
          <div class="note-date">${new Date(n.created_at).toLocaleString()}</div>
        </div>
        <hr style="border-color:#1b263b;" />
      `
      )
      .join("");

  } catch (err) {
    container.innerHTML = `<p class="placeholder">Error loading notes.</p>`;
  }
}


// =======================
// Load Profile Picture + Greeting from DB
// =======================
document.addEventListener("DOMContentLoaded", async () => {
  const avatar = document.getElementById("avatarBtn");
  const greeting = document.getElementById("greetingText");

  // Load greeting
  try {
    const res = await fetch("/api/user-profile");
    const data = await res.json();

    if (data.ok && data.user) {
      const user = data.user;
      const firstName = user.fullName ? user.fullName.split(" ")[0] : "User";
      if (greeting) {
        greeting.textContent = `Hello, ${firstName}`;
      }
    }
  } catch (err) {
    console.error("[Dashboard] Failed to load user profile:", err);
  }

  // Load avatar
  try {
    if (!window.userId || !avatar) return;
    const res = await fetch(`/api/profile-picture/${window.userId}`);
    const data = await res.json();

    if (data.ok && data.image) {
      avatar.style.backgroundImage = `url(${data.image})`;
      avatar.style.backgroundSize = "cover";
      avatar.style.backgroundPosition = "center";
      avatar.textContent = "";
    } else {
      const initial =
        (greeting &&
          greeting.textContent &&
          greeting.textContent.replace("Hello, ", "").charAt(0)) || "U";
      avatar.textContent = initial;
    }
  } catch (err) {
    console.warn("[Dashboard] No profile picture found.");
    if (avatar) {
      const initial =
        (greeting &&
          greeting.textContent &&
          greeting.textContent.replace("Hello, ", "").charAt(0)) || "U";
      avatar.textContent = initial;
    }
  }

  if (avatar) {
    avatar.addEventListener("click", () => {
      window.location.href = "/edit-profile.html";
    });
  }
});

// =======================
// Transactions rendering (Plaid only)
// =======================
const txTable = document.getElementById("txTable");

function formatAmt(n) {
  const num = Number(n || 0);
  const f = Math.abs(num).toFixed(2);
  return num < 0 ? `-$${f}` : `$${f}`;
}

function renderTransactionsFromList(list) {
  if (!txTable) return;

  if (!list || !list.length) {
    txTable.innerHTML = `
      <tr>
        <td colspan="4" style="text-align:center;color:#8091a3;">
          Connect a bank account to see your recent transactions.
        </td>
      </tr>
    `;
    return;
  }

  txTable.innerHTML = list
    .map((tx) => {
      const date = tx.date || "";
      const merchant = tx.merchant || tx.name || "Unknown";

      // Use cleaned category from API
      const category =
        tx.resolved_category ||
        (Array.isArray(tx.category) ? tx.category[0] : tx.category) ||
        "Other";

      const txId = tx.transaction_id || "";
      const signed =
        typeof tx.amount === "number" ? tx.amount : Number(tx.amount || 0);

      return `
        <tr data-txid="${txId}">
          <td>${date}</td>
          <td>${merchant}</td>
          <td>${category}</td>
          <td style="color:${signed < 0 ? "#ff9f9f" : "#5df2a9"}">
            ${formatAmt(signed)}
          </td>
        </tr>`;
    })
    .join("");
}

// Clickable rows → transaction-details
if (txTable) {
  txTable.addEventListener("click", (e) => {
    const row = e.target.closest("tr[data-txid]");
    if (!row) return;
    const txId = row.getAttribute("data-txid");
    if (txId) {
      window.location.href = `/transaction-details.html?txid=${encodeURIComponent(
        txId
      )}`;
    }
  });
}

// =======================
// Income vs Expense Bar Chart
// =======================
async function updateBarChart() {
  try {
    const res = await fetch("/api/summary");
    if (!res.ok) throw new Error("API request failed");
    const data = await res.json();

    const barChart = document.getElementById("barChart");
    if (!barChart) return;
    barChart.innerHTML = "";

    const income = Number(data.income || 0);
    const expense = Number(data.expense || 0);

    const maxVal = Math.max(income, expense, 1);
    const minHeight = 10;
    const chartHeight = 220;

    // Income bar
    const incomeBarWrapper = document.createElement("div");
    incomeBarWrapper.className = "bar";
    const incomeHeight = Math.max((income / maxVal) * chartHeight, minHeight);
    incomeBarWrapper.innerHTML = `
      <div class="bar__fill bar--income" style="height:${incomeHeight}px"></div>
      <div class="bar__label">
        Income<br><b>$${income.toFixed(2)}</b>
      </div>
    `;
    barChart.appendChild(incomeBarWrapper);

    // Expense bar
    const expenseBarWrapper = document.createElement("div");
    expenseBarWrapper.className = "bar";
    const expenseHeight = Math.max(
      (expense / maxVal) * chartHeight,
      minHeight
    );
    expenseBarWrapper.innerHTML = `
      <div class="bar__fill bar--expense" style="height:${expenseHeight}px"></div>
      <div class="bar__label">
        Expenses<br><b>$${expense.toFixed(2)}</b>
      </div>
    `;
    barChart.appendChild(expenseBarWrapper);
  } catch (err) {
    console.error("[Dashboard] Chart render failed:", err);
  }
}

document.addEventListener("DOMContentLoaded", updateBarChart);

// =======================
// CATEGORY BREAKDOWN (Donut Chart — legacy)
// =======================
async function updateCategoryDonut() {
  try {
    const res = await fetch("/api/category-breakdown");
    const list = await res.json();

    if (!Array.isArray(list) || list.length === 0) {
      console.warn("[Dashboard] No category data");
      return;
    }

    drawCategoryDonut(list);
  } catch (err) {
    console.error("[Dashboard] Category breakdown failed:", err);
  }
}

// Draw donut
function drawCategoryDonut(list) {
  const slices = document.querySelectorAll(".donut__slice");
  const legends = document.querySelectorAll(".donut__legend span");

  if (!slices.length || !legends.length) return;

  const total = list.reduce(
    (sum, x) => sum + Number(x.total || 0),
    0
  );
  if (total <= 0) return;

  let offset = 0;

  list.slice(0, 3).forEach((item, i) => {
    const percent = (item.total / total) * 100;
    const dasharray = `${percent} ${100 - percent}`;

    slices[i].setAttribute("stroke-dasharray", dasharray);
    slices[i].setAttribute("stroke-dashoffset", offset);

    legends[i].innerText = `${item.category} (${formatMoney(item.total)})`;

    offset += percent;
  });
}

// =======================
// AI Insights (real AI via /api/ai-insights)
// =======================

const dashboardFallbackTips = [
  "🚌 Try a transit pass this week — potential savings <b>$18</b>.",
  "🧾 Your subscriptions increased by <b>$6</b> MoM.",
  "🥦 Groceries are below average this week. Nice!",
  "🛍️ Consider a 48-hour rule for purchases over <b>$50</b>.",
];

async function loadDashboardInsights() {
  const listEl = document.getElementById("aiInsights");
  if (!listEl) return;

  listEl.innerHTML = `<li>🔍 Loading insights…</li>`;

  try {
    const res = await fetch("/api/ai-insights", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    });

    const data = await res.json();

    let tips = [];
    if (data && Array.isArray(data.insights) && data.insights.length > 0) {
      tips = data.insights;
    } else {
      tips = dashboardFallbackTips;
    }

    listEl.innerHTML = tips.map((t) => `<li>${t}</li>`).join("");
  } catch (err) {
    console.error("[Dashboard] AI insights failed:", err);
    listEl.innerHTML = dashboardFallbackTips.map((t) => `<li>${t}</li>`).join("");
  }
}

// Hook up button + auto-load
document.addEventListener("DOMContentLoaded", () => {
  const refreshAI = document.getElementById("refreshAI");

  if (refreshAI) {
    refreshAI.addEventListener("click", (e) => {
      e.preventDefault();
      loadDashboardInsights();
    });
  }

  // Load once on dashboard open
  loadDashboardInsights();
});


// =======================
// Logout
// =======================
const logoutBtn = document.querySelector(".logout");
if (logoutBtn) {
  logoutBtn.addEventListener("click", async (e) => {
    e.preventDefault();
    try {
      const res = await fetch("/logout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (res.ok) {
        window.location.href = "/";
      } else {
        console.error("[dashboard.js] Logout failed:", res.status);
        alert("Logout failed. Please try again.");
      }
    } catch (err) {
      console.error("[dashboard.js] Network error:", err);
      alert("Network error while logging out.");
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  const chatModal = document.getElementById("aiChatModal");
  const openChatBtn = document.getElementById("openChatBtn");
  const closeChat = document.getElementById("closeChat");
  const chatForm = document.getElementById("chatForm");
  const chatInput = document.getElementById("chatInput");
  const chatMessages = document.getElementById("chatMessages");

  if (!chatModal || !openChatBtn) {
    console.warn("AI Chat elements not found in DOM.");
    return;
  }

  // Open chat
  openChatBtn.addEventListener("click", () => {
    chatModal.classList.remove("hidden");
    setTimeout(() => chatInput.focus(), 120);
  });

  // Close chat
  if (closeChat) {
    closeChat.addEventListener("click", () => {
      chatModal.classList.add("hidden");
    });
  }

  // Send message
  if (chatForm) {
    chatForm.addEventListener("submit", async (e) => {
      e.preventDefault();

      const msg = chatInput.value.trim();
      if (!msg) return;

      chatMessages.innerHTML += `<p class="user">🧍 ${msg}</p>`;
      chatInput.value = "";

      try {
        const res = await fetch("/api/ai-chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: msg }),
        });

        const data = await res.json();
        chatMessages.innerHTML += `<p class="ai">🤖 ${data.reply}</p>`;
      } catch {
        chatMessages.innerHTML += `<p class="ai">⚠️ Connection error.</p>`;
      }

      chatMessages.scrollTop = chatMessages.scrollHeight;
    });
  }
});



// =======================
// BANK STATUS UI
// =======================

// NOTE: now a mutable budget target; will be overwritten from /api/user-profile
let MONTHLY_BUDGET_TARGET = 2500;
const SAVINGS_GOAL_TARGET = 10000;

// Load the user's current spending_limit so dashboard uses real budget
async function loadUserBudgetLimit() {
  try {
    const res = await fetch("/api/user-profile");
    const data = await res.json();

    if (data.ok && data.user) {
      const user = data.user;
      const limit = Number(user.spending_limit);

      if (!Number.isNaN(limit) && limit > 0) {
        MONTHLY_BUDGET_TARGET = limit;
      }
    }
  } catch (err) {
    console.error("[Dashboard] Failed to load spending_limit:", err);
    // keep default 2500 if error
  }
}

async function updateBankUI() {
  const balanceEl = document.getElementById("totalBalance");

  const monthlySpendingEl = document.getElementById("monthlySpending");
  const monthlySpendingHintEl = document.getElementById("monthlySpendingHint");
  const monthlySpendingProgressEl =
    document.getElementById("monthlySpendingProgress");

  const savingsGoalTextEl = document.getElementById("savingsGoalText");
  const savingsGoalHintEl = document.getElementById("savingsGoalHint");
  const savingsGoalProgressEl =
    document.getElementById("savingsGoalProgress");

  function resetBankUI() {
    if (balanceEl) balanceEl.textContent = "$0.00";
    renderTransactionsFromList([]);

    if (monthlySpendingEl) monthlySpendingEl.textContent = "$0.00";
    if (monthlySpendingHintEl) {
      monthlySpendingHintEl.textContent = `vs. budget $${MONTHLY_BUDGET_TARGET.toFixed(
        2
      )}`;
    }
    if (monthlySpendingProgressEl)
      monthlySpendingProgressEl.style.width = "0%";

    if (savingsGoalTextEl) {
      savingsGoalTextEl.textContent = `$0.00 / $${SAVINGS_GOAL_TARGET.toFixed(
        2
      )}`;
    }
    if (savingsGoalHintEl) {
      savingsGoalHintEl.textContent = "Connect a bank to track savings.";
    }
    if (savingsGoalProgressEl) savingsGoalProgressEl.style.width = "0%";
  }

  try {
    const res = await fetch("/api/bank/status");
    const data = await res.json();

    if (!data.ok || !data.connected) {
      resetBankUI();
      return;
    }

    // ---- Bank is connected ----
    const currentBal =
      typeof data.current_balance === "number" ? data.current_balance : 0;

    // 1) Total Balance
    if (balanceEl) {
      balanceEl.textContent = `$${currentBal.toFixed(2)}`;
    }

    // 2) Transactions
    const recent = Array.isArray(data.recent_transactions)
      ? data.recent_transactions
      : [];

    const uiTx = recent.map((tx) => {
      const raw = Number(tx.amount || 0);
      const signed =
        typeof tx.signed_amount === "number"
          ? tx.signed_amount
          : raw;

      return {
        date: tx.date,
        merchant: tx.name,
        category: tx.category,
        amount: signed,
        transaction_id: tx.transaction_id,
      };
    });

    renderTransactionsFromList(uiTx);

    // 3) Income vs Expense
    let totalIncome = 0;
    let totalExpense = 0;

    uiTx.forEach((tx) => {
      const amt = Number(tx.amount || 0);
      if (amt > 0) totalIncome += amt;
      else if (amt < 0) totalExpense += Math.abs(amt);
    });

    const spendingAbs = totalExpense;

    if (monthlySpendingEl) {
      monthlySpendingEl.textContent = `$${spendingAbs.toFixed(2)}`;
    }
    if (monthlySpendingHintEl) {
      monthlySpendingHintEl.textContent = `vs. budget $${MONTHLY_BUDGET_TARGET.toFixed(
        2
      )}`;
    }
    if (monthlySpendingProgressEl) {
      const pct =
        MONTHLY_BUDGET_TARGET > 0
          ? Math.min(100, (spendingAbs / MONTHLY_BUDGET_TARGET) * 100)
          : 0;
      monthlySpendingProgressEl.style.width = `${pct}%`;
    }

    // 4) Savings Goal
    if (savingsGoalTextEl) {
      savingsGoalTextEl.textContent = `$${currentBal.toFixed(
        2
      )} / $${SAVINGS_GOAL_TARGET.toFixed(2)}`;
    }
    if (savingsGoalHintEl) {
      savingsGoalHintEl.textContent = "Based on your linked account balance.";
    }
    if (savingsGoalProgressEl) {
      const goalPct =
        SAVINGS_GOAL_TARGET > 0
          ? Math.min(100, (currentBal / SAVINGS_GOAL_TARGET) * 100)
          : 0;
      savingsGoalProgressEl.style.width = `${goalPct}%`;
    }
  } catch (err) {
    console.error("[Dashboard] Failed to load bank status:", err);
    resetBankUI();
  }
}

// =======================
// Dashboard Category Pie Chart (REAL DATA)
// =======================

let categoryChart = null;

// Load filtered category chart
async function loadCategoryChart(filter = "all") {
  try {
    const res = await fetch(`/api/category-breakdown?range=${filter}`);
    const data = await res.json();

    if (!data || data.length === 0) return;

    const labels = data.map(i => i.category);
    const values = data.map(i => i.total);

    const canvas = document.getElementById("dashboardCategoryChart");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    if (categoryChart) categoryChart.destroy();

    categoryChart = new Chart(ctx, {
      type: "pie",
      data: {
        labels,
        datasets: [{
          data: values,
          backgroundColor: [
            "#00ffff", "#00b3b3", "#38d9ff", "#4ce0d2",
            "#75f5e3", "#009999", "#66fff2", "#ff6b6b"
          ],
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

  } catch (err) {
    console.error("Pie chart load error:", err);
  }
}

// =======================
// CATEGORY FILTER DROPDOWN
// =======================
document.addEventListener("DOMContentLoaded", () => {
  const filter = document.getElementById("pieFilter");
  if (!filter) return;

  filter.addEventListener("change", (e) => {
    const mode = e.target.value;
    loadCategoryChart(mode);
  });
});

// =======================
// Run dashboard updates
// =======================
document.addEventListener("DOMContentLoaded", async () => {
  // make sure we pull the user's real spending_limit first
  await loadUserBudgetLimit();

  updateBankUI();
  loadCategoryChart("all");
  loadAdvisorNotes();

  // Refresh bank every 10 minutes
  setInterval(updateBankUI, 600000);
});


// =======================
// CLIENT NOTIFICATION SYSTEM
// =======================
document.addEventListener("DOMContentLoaded", () => {
  initClientNotifications();
});

function initClientNotifications() {
  const btn = document.getElementById("notificationsBtn");
  const badge = document.getElementById("notificationsBadge");
  const panel = document.getElementById("notificationsPanel");
  const closeBtn = document.getElementById("closeNotifications");
  const listEl = document.getElementById("notificationsList");

  if (!btn || !badge || !panel || !closeBtn || !listEl) {
    console.warn("[dashboard.js] Notification elements not found");
    return;
  }

  const togglePanel = () => {
    panel.classList.toggle("hidden");
  };

  btn.addEventListener("click", (e) => {
    e.preventDefault();
    togglePanel();
  });

  closeBtn.addEventListener("click", (e) => {
    e.preventDefault();
    panel.classList.add("hidden");
  });

  // Close if clicking outside
  document.addEventListener("click", (e) => {
    if (!panel.classList.contains("hidden")) return;
    const clickedInsidePanel = panel.contains(e.target);
    const clickedBell = btn.contains(e.target);
    if (!clickedInsidePanel && !clickedBell) {
      panel.classList.add("hidden");
    }
  });

  // Load immediately + poll every 30s
  fetchAllNotifications();
  setInterval(fetchAllNotifications, 30000);

  // ---- NEW: fetch BOTH advisor-link requests and budget-limit requests ----
  function fetchAllNotifications() {
    Promise.all([
      // Advisor link requests
      fetch("/api/client/requests")
        .then((res) => res.json())
        .catch(() => null),

      // Budget limit permission requests
      fetch("/api/client/budget_limit_requests")
        .then((res) => res.json())
        .catch(() => null),

      // Advisor NOTES (NEW)
      fetch("/api/notifications")
        .then((res) => res.json())
        .catch(() => null),
    ])
      .then(([linkData, budgetData, notesData]) => {
        const advisorRequests =
          linkData && linkData.ok && Array.isArray(linkData.requests)
            ? linkData.requests
            : [];

        const budgetRequests =
          budgetData && budgetData.ok && Array.isArray(budgetData.requests)
            ? budgetData.requests
            : [];

        const noteNotifications =
          notesData && notesData.ok && Array.isArray(notesData.notifications)
            ? notesData.notifications.filter((n) => n.type === "advisor_note")
            : [];

        renderNotifications(advisorRequests, budgetRequests, noteNotifications);

        updateBadge(
          advisorRequests.length +
          budgetRequests.length +
          noteNotifications.length
        );
      })
      .catch((err) => {
        console.error("Error fetching notifications:", err);
      });
  }

  function updateBadge(count) {
    if (count > 0) {
      badge.textContent = count;
      badge.classList.remove("hidden");
    } else {
      badge.textContent = "";
      badge.classList.add("hidden");
    }
  }

  // Renders BOTH types of notifications into the same panel
  function renderNotifications(advisorRequests, budgetRequests, noteNotifications) {
    listEl.innerHTML = "";

    const total =
      advisorRequests.length +
      budgetRequests.length +
      noteNotifications.length;

    if (total === 0) {
      const empty = document.createElement("p");
      empty.className = "notif-empty";
      empty.textContent = "No new notifications.";
      listEl.appendChild(empty);
      return;
    }

    // --- Advisor link requests ---
    advisorRequests.forEach((req) => {
      const item = document.createElement("div");
      item.className = "notif-item";
      item.innerHTML = `
        <p><strong>${req.advisorName}</strong> wants to add you as a client.</p>
        <div class="notif-actions">
          <button class="btn small"
                  data-kind="link"
                  data-action="accept"
                  data-id="${req.id}">
            Accept
          </button>
          <button class="btn ghost small"
                  data-kind="link"
                  data-action="decline"
                  data-id="${req.id}">
            Decline
          </button>
        </div>`;
      listEl.appendChild(item);
    });

    // --- Budget limit permission requests ---
    budgetRequests.forEach((req) => {
      const item = document.createElement("div");
      const currentLimitText = `$${Number(req.currentLimit || 0).toFixed(2)}`;
      item.className = "notif-item";
      item.innerHTML = `
        <p><strong>${req.advisorName}</strong> wants permission to edit your budget limit
          (current: <b>${currentLimitText}</b>).</p>
        <div class="notif-actions">
          <button class="btn small"
                  data-kind="budget"
                  data-action="accept"
                  data-id="${req.id}">
            Allow
          </button>
          <button class="btn ghost small"
                  data-kind="budget"
                  data-action="decline"
                  data-id="${req.id}">
            Deny
          </button>
        </div>`;
      listEl.appendChild(item);
    });

    // --- NEW: Advisor Notes (simple notification) ---
    noteNotifications.forEach((note) => {
      const item = document.createElement("div");
      item.className = "notif-item";
      item.innerHTML = `
        <p>📝 <strong>New advisor note:</strong> ${note.message}</p>
        <p style="font-size:0.8rem; opacity:0.7;">
          ${new Date(note.created_at).toLocaleString()}
        </p>`;
      listEl.appendChild(item);
    });
  }


  function respondToAdvisorLinkRequest(id, decision) {
    fetch("/api/client/requests/respond", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, decision }),
    })
      .then((res) => res.json())
      .then((data) => {
        if (!data.ok) {
          alert(data.message || "Something went wrong.");
          return;
        }
        fetchAllNotifications();
      })
      .catch((err) => {
        console.error("Error responding to advisor request:", err);
        alert("Something went wrong. Please try again.");
      });
  }

  function respondToBudgetLimitRequest(id, decision) {
    fetch("/api/client/budget_limit_requests/respond", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, decision }),
    })
      .then((res) => res.json())
      .then((data) => {
        if (!data.ok) {
          alert(data.message || "Something went wrong.");
          return;
        }
        fetchAllNotifications();
      })
      .catch((err) => {
        console.error("Error responding to budget limit request:", err);
        alert("Something went wrong. Please try again.");
      });
  }
}
