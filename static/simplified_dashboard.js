// =======================
// Helpers
// =======================

function formatMoney(n) {
  return `$${Number(n || 0).toFixed(2)}`;
}

// =======================
// Sidebar toggle for mobile
// =======================
function setupSidebarToggle() {
  const toggleBtn = document.getElementById("toggleSidebar");
  const sidebar = document.getElementById("sidebar");

  if (!toggleBtn || !sidebar) return;

  toggleBtn.addEventListener("click", () => {
    if (window.innerWidth <= 880) {
      sidebar.classList.toggle("show");
    } else {
      sidebar.classList.toggle("hidden");
    }
  });
}

// =======================
// Load Profile Picture + Greeting from DB
// =======================
async function setupProfileHeader() {
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
    console.error("[SimplifiedDashboard] Failed to load user profile:", err);
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
    console.warn("[SimplifiedDashboard] No profile picture found.");
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
}

// =======================
// Simplified Flows: income + expenses lists
// =======================
async function loadSimplifiedFlows() {
  const incomeBody = document.getElementById("sdIncomeTableBody");
  const expenseBody = document.getElementById("sdExpenseTableBody");

  if (!incomeBody || !expenseBody) return;

  incomeBody.innerHTML = `
    <tr><td colspan="4" style="text-align:center;color:#8091a3;">Loading income…</td></tr>
  `;
  expenseBody.innerHTML = `
    <tr><td colspan="4" style="text-align:center;color:#8091a3;">Loading expenses…</td></tr>
  `;

  try {
    const res = await fetch("/api/simplified/flows");
    const data = await res.json();

    if (!data.ok) {
      incomeBody.innerHTML = `
        <tr><td colspan="4" style="text-align:center;color:#ff9f9f;">Unable to load income streams.</td></tr>
      `;
      expenseBody.innerHTML = `
        <tr><td colspan="4" style="text-align:center;color:#ff9f9f;">Unable to load expenses.</td></tr>
      `;
      return;
    }

    const incomes = Array.isArray(data.income_streams) ? data.income_streams : [];
    const expenses = Array.isArray(data.expense_streams) ? data.expense_streams : [];

    // INCOME TABLE
    if (incomes.length === 0) {
      incomeBody.innerHTML = `
        <tr><td colspan="4" style="text-align:center;color:#8091a3;">No income streams found.</td></tr>
      `;
    } else {
      incomeBody.innerHTML = incomes
        .map((i) => {
          const date = i.date || "";
          const name = i.name || "Income";
          const category = i.category || "Other";
          const amount = Number(i.amount || 0);
          return `
            <tr>
              <td>${date}</td>
              <td>${name}</td>
              <td>${category}</td>
              <td style="color:#5df2a9;">${formatMoney(amount)}</td>
            </tr>
          `;
        })
        .join("");
    }

    // EXPENSE TABLE
    if (expenses.length === 0) {
      expenseBody.innerHTML = `
        <tr><td colspan="4" style="text-align:center;color:#8091a3;">No expenses found.</td></tr>
      `;
    } else {
      expenseBody.innerHTML = expenses
        .map((e) => {
          const date = e.date || "";
          const name = e.name || "Expense";
          const category = e.category || "Other";
          const amount = Number(e.amount || 0);
          return `
            <tr>
              <td>${date}</td>
              <td>${name}</td>
              <td>${category}</td>
              <td style="color:#ff9f9f;">-${formatMoney(amount)}</td>
            </tr>
          `;
        })
        .join("");
    }
  } catch (err) {
    console.error("[SimplifiedDashboard] Failed to load simplified flows:", err);
    incomeBody.innerHTML = `
      <tr><td colspan="4" style="text-align:center;color:#ff9f9f;">Error loading income.</td></tr>
    `;
    expenseBody.innerHTML = `
      <tr><td colspan="4" style="text-align:center;color:#ff9f9f;">Error loading expenses.</td></tr>
    `;
  }
}

// =======================
// Simplified Summary: net income + 20% savings rule
// =======================
async function loadSimplifiedSummary() {
  const totalIncomeEl = document.getElementById("sdTotalIncome");
  const totalExpenseEl = document.getElementById("sdTotalExpense");
  const netIncomeEl = document.getElementById("sdNetIncome");
  const savingsTextEl = document.getElementById("sdSavingsText");
  const savingsStatusEl = document.getElementById("sdSavingsStatusText");
  const savingsProgressEl = document.getElementById("sdSavingsProgress");

  try {
    const [summaryRes, bankRes] = await Promise.all([
      fetch("/api/simplified/summary"),
      fetch("/api/bank/status").catch(() => null),
    ]);

    const summaryData = await summaryRes.json();
    let bankData = null;
    if (bankRes && bankRes.ok) {
      bankData = await bankRes.json();
    }

    if (!summaryData.ok) {
      if (totalIncomeEl) totalIncomeEl.textContent = "$0.00";
      if (totalExpenseEl) totalExpenseEl.textContent = "$0.00";
      if (netIncomeEl) netIncomeEl.textContent = "$0.00";
      if (savingsTextEl) savingsTextEl.textContent = "20% savings target: $0.00";
      if (savingsStatusEl) {
        savingsStatusEl.textContent =
          "Unable to compute summary. Try again later.";
      }
      if (savingsProgressEl) savingsProgressEl.style.width = "0%";
      return;
    }

    const totalIncome = Number(summaryData.total_income || 0);
    const totalExpense = Number(summaryData.total_expense || 0);
    const netIncome = Number(summaryData.net_income || 0);
    const savingsTarget = Number(summaryData.savings_target || 0);

    if (totalIncomeEl) totalIncomeEl.textContent = formatMoney(totalIncome);
    if (totalExpenseEl) totalExpenseEl.textContent = formatMoney(totalExpense);
    if (netIncomeEl) netIncomeEl.textContent = formatMoney(netIncome);
    if (savingsTextEl) {
      savingsTextEl.textContent = `20% savings target: ${formatMoney(
        savingsTarget
      )}`;
    }

    // Compare ACTUAL savings (bank balance) vs target
    let actualSavings = null;
    if (bankData && bankData.ok && bankData.connected) {
      const bal =
        typeof bankData.current_balance === "number"
          ? bankData.current_balance
          : 0;
      actualSavings = bal;
    }

    if (savingsStatusEl && savingsProgressEl) {
      if (netIncome <= 0 || savingsTarget <= 0) {
        savingsStatusEl.textContent =
          "Your net income is non-positive, so the 20% savings rule doesn’t apply yet.";
        savingsProgressEl.style.width = "0%";
      } else if (actualSavings === null) {
        savingsStatusEl.textContent =
          "Link a bank account to see how you compare to the 20% savings target.";
        savingsProgressEl.style.width = "0%";
      } else {
        const pctOfGoal = (actualSavings / savingsTarget) * 100;
        const diff = pctOfGoal - 100;
        const diffAbs = Math.abs(diff).toFixed(1);

        let direction;
        if (diff > 1) direction = "above";
        else if (diff < -1) direction = "below";
        else direction = "at";

        if (direction === "at") {
          savingsStatusEl.textContent =
            "You are right on your 20% savings target. Nice!";
        } else {
          savingsStatusEl.textContent = `You are ${diffAbs}% ${direction} your 20% savings target.`;
        }

        const clamped = Math.max(0, Math.min(150, pctOfGoal));
        savingsProgressEl.style.width = `${Math.min(clamped, 100)}%`;
      }
    }
  } catch (err) {
    console.error("[SimplifiedDashboard] Failed to load summary:", err);
    if (savingsStatusEl) {
      savingsStatusEl.textContent =
        "Error loading summary. Please try again.";
    }
    if (savingsProgressEl) savingsProgressEl.style.width = "0%";
  }
}

// =======================
// Logout
// =======================
function initLogout() {
  const logoutBtn = document.querySelector(".logout");
  if (!logoutBtn) return;

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
        console.error("[simplified_dashboard.js] Logout failed:", res.status);
        alert("Logout failed. Please try again.");
      }
    } catch (err) {
      console.error("[simplified_dashboard.js] Network error:", err);
      alert("Network error while logging out.");
    }
  });
}

// =======================
// AI Chat
// =======================
function initAIChat() {
  const chatModal = document.getElementById("aiChatModal");
  const openChatBtn = document.getElementById("openChatBtn");
  const closeChat = document.getElementById("closeChat");
  const chatForm = document.getElementById("chatForm");
  const chatInput = document.getElementById("chatInput");
  const chatMessages = document.getElementById("chatMessages");

  if (!chatModal || !chatForm || !chatInput || !chatMessages) {
    console.warn("[SimplifiedDashboard] AI Chat elements not found in DOM.");
    return;
  }

  if (openChatBtn) {
    openChatBtn.addEventListener("click", () => {
      chatModal.classList.remove("hidden");
      setTimeout(() => chatInput.focus(), 120);
    });
  }

  if (closeChat) {
    closeChat.addEventListener("click", () => {
      chatModal.classList.add("hidden");
    });
  }

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

// =======================
// CLIENT NOTIFICATION SYSTEM
// =======================
function initClientNotifications() {
  const btn = document.getElementById("notificationsBtn");
  const badge = document.getElementById("notificationsBadge");
  const panel = document.getElementById("notificationsPanel");
  const closeBtn = document.getElementById("closeNotifications");
  const listEl = document.getElementById("notificationsList");

  if (!btn || !badge || !panel || !closeBtn || !listEl) {
    console.warn("[simplified_dashboard.js] Notification elements not found");
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
    if (panel.classList.contains("hidden")) return;
    const clickedInsidePanel = panel.contains(e.target);
    const clickedBell = btn.contains(e.target);
    if (!clickedInsidePanel && !clickedBell) {
      panel.classList.add("hidden");
    }
  });

  // Load immediately + poll every 30s
  fetchAllNotifications();
  setInterval(fetchAllNotifications, 30000);

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

      // Advisor NOTES
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

        renderNotifications(
          advisorRequests,
          budgetRequests,
          noteNotifications
        );

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

  function renderNotifications(
    advisorRequests,
    budgetRequests,
    noteNotifications
  ) {
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

    // Advisor link requests
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

    // Budget limit permission requests
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

    // Advisor Notes notifications
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

    // Wire up buttons
    listEl.querySelectorAll("button[data-kind]").forEach((btnEl) => {
      btnEl.addEventListener("click", () => {
        const kind = btnEl.getAttribute("data-kind");
        const action = btnEl.getAttribute("data-action");
        const id = btnEl.getAttribute("data-id");
        if (!kind || !action || !id) return;

        if (kind === "link") {
          respondToAdvisorLinkRequest(id, action);
        } else if (kind === "budget") {
          respondToBudgetLimitRequest(id, action);
        }
      });
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

// =======================
// Init
// =======================
document.addEventListener("DOMContentLoaded", () => {
  setupSidebarToggle();
  setupProfileHeader();
  initLogout();
  initAIChat();
  initClientNotifications();

  loadSimplifiedFlows();
  loadSimplifiedSummary();
});
