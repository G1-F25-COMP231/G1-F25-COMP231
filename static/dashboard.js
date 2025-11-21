// =======================
// Sidebar toggle for mobile
// =======================
const toggleBtn = document.getElementById('toggleSidebar');
const sidebar = document.getElementById('sidebar');

if (toggleBtn && sidebar) {
  toggleBtn.addEventListener('click', () => {
    if (window.innerWidth <= 880) {
      sidebar.classList.toggle('show');
    } else {
      sidebar.classList.toggle('hidden');
    }
  });
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
      greeting.textContent = `Hello, ${firstName}`;
    }
  } catch (err) {
    console.error("[Dashboard] Failed to load user profile:", err);
  }

  // Load avatar from MongoDB
  try {
    const res = await fetch(`/api/profile-picture/${window.userId}`);
    const data = await res.json();

    if (data.ok && data.image) {
      avatar.style.backgroundImage = `url(${data.image})`;
      avatar.style.backgroundSize = "cover";
      avatar.style.backgroundPosition = "center";
      avatar.textContent = "";
    } else {
      // fallback initial
      avatar.textContent = greeting.textContent.replace("Hello, ", "").charAt(0) || "U";
    }
  } catch (err) {
    console.warn("[Dashboard] No profile picture found.");
    avatar.textContent = "U";
  }

  avatar.addEventListener("click", () => {
    window.location.href = "/edit-profile.html";
  });
});

// =======================
// Sample recent transactions
// =======================
const sampleTx = [
  { date: '2025-11-07', merchant: 'Uber Eats', category: 'Dining', amount: -24.19 },
  { date: '2025-11-06', merchant: 'Starbucks', category: 'Dining', amount: -6.15 },
  { date: '2025-11-06', merchant: 'Hydro Toronto', category: 'Bills', amount: -86.40 },
  { date: '2025-11-05', merchant: 'Metro', category: 'Groceries', amount: -72.33 },
  { date: '2025-11-04', merchant: 'Payroll', category: 'Income', amount: 2450.00 },
  { date: '2025-11-03', merchant: 'Airbnb', category: 'Travel', amount: -128.00 },
];

const txTable = document.getElementById('txTable');
function formatAmt(n) {
  const f = Math.abs(n).toFixed(2);
  return n < 0 ? `-$${f}` : `$${f}`;
}
function renderTx() {
  if (!txTable) return;
  txTable.innerHTML = sampleTx
    .map(
      (tx) => `
        <tr>
          <td>${tx.date}</td>
          <td>${tx.merchant}</td>
          <td>${tx.category}</td>
          <td style="color:${tx.amount < 0 ? '#ff9f9f' : '#5df2a9'}">${formatAmt(tx.amount)}</td>
        </tr>`
    )
    .join('');
}
renderTx();

// === Fetch Income vs Expense Summary ===
async function loadSummary() {
  try {
    const res = await fetch("/api/summary");
    const data = await res.json();

    const incomeBar = document.querySelector(".bar--income");
    const expenseBar = document.querySelector(".bar--expense");
    const incomeLabel = incomeBar.nextElementSibling;
    const expenseLabel = expenseBar.nextElementSibling;

    const income = data.income || 0;
    const expense = data.expense || 0;
    const total = income + expense;

    // Calculate relative height %
    const incomePct = total > 0 ? (income / total) * 100 : 50;
    const expensePct = total > 0 ? (expense / total) * 100 : 50;

    incomeBar.style.height = `${Math.max(10, incomePct)}%`;
    expenseBar.style.height = `${Math.max(10, expensePct)}%`;

    // Update labels
    incomeLabel.textContent = `Income ($${income.toFixed(2)})`;
    expenseLabel.textContent = `Expenses ($${expense.toFixed(2)})`;

  } catch (err) {
    console.error("[Dashboard] Failed to load summary:", err);
  }
}

document.addEventListener("DOMContentLoaded", loadSummary);

// =======================
// AI Insights Refresh Tips
// =======================
const refreshAI = document.getElementById('refreshAI');
const aiInsights = document.getElementById('aiInsights');
const tips = [
  '🚌 Try a transit pass this week — potential savings <b>$18</b>.',
  '🧾 Your subscriptions increased by <b>$6</b> MoM.',
  '🥦 Groceries are below average this week. Nice!',
  '🛍️ Consider a 48-hour rule for purchases over <b>$50</b>.',
];

if (refreshAI && aiInsights) {
  refreshAI.addEventListener('click', () => {
    const pick = Array.from({ length: 3 }, () => tips[Math.floor(Math.random() * tips.length)]);
    aiInsights.innerHTML = pick.map((t) => `<li>${t}</li>`).join('');
  });
}

// =======================
// Logout Button
// =======================
const logoutBtn = document.querySelector('.logout');
if (logoutBtn) {
  logoutBtn.addEventListener('click', async (e) => {
    e.preventDefault();
    console.log('[dashboard.js] Logout clicked');
    try {
      const res = await fetch('/logout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (res.ok) {
        console.log('[dashboard.js] Logout success');
        window.location.href = '/';
      } else {
        console.error('[dashboard.js] Logout failed:', res.status);
        alert('Logout failed. Please try again.');
      }
    } catch (err) {
      console.error('[dashboard.js] Network error:', err);
      alert('Network error while logging out.');
    }
  });
}

// =======================
// AI Chat Modal Logic
// =======================
const chatModal = document.getElementById('aiChatModal');
const openChatBtn = document.getElementById('openChatBtn');
const closeChat = document.getElementById('closeChat');
const chatForm = document.getElementById('chatForm');
const chatInput = document.getElementById('chatInput');
const chatMessages = document.getElementById('chatMessages');

if (openChatBtn && chatModal) {
  openChatBtn.addEventListener('click', () => {
    chatModal.classList.remove('hidden');
  });
}

if (closeChat && chatModal) {
  closeChat.addEventListener('click', () => {
    chatModal.classList.add('hidden');
  });
}

if (chatForm && chatMessages && chatInput) {
  chatForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const userMsg = chatInput.value.trim();
    if (!userMsg) return;

    // Display user message
    chatMessages.innerHTML += `<p class="user">🧍 ${userMsg}</p>`;
    chatInput.value = '';

    try {
      const res = await fetch('/api/ai-chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMsg }),
      });

      const data = await res.json();
      chatMessages.innerHTML += `<p class="ai">🤖 ${data.reply}</p>`;
      chatMessages.scrollTop = chatMessages.scrollHeight;
    } catch (err) {
      console.error('[AI Chat] Error:', err);
      chatMessages.innerHTML += `<p class="ai">⚠️ Unable to connect to AI right now.</p>`;
    }
  });
}

// === Dynamic Income vs. Expense Chart Enhancement ===
async function updateBarChart() {
  try {
    const res = await fetch("/api/summary");
    if (!res.ok) throw new Error("API request failed");

    const data = await res.json();
    const { income = 0, expense = 0, categories = [] } = data;

    const barChart = document.getElementById("barChart");
    barChart.innerHTML = ""; // Clear placeholder bars

    // Find the max value for height scaling
    const maxVal = Math.max(income, ...categories.map(c => c.total));

    // Income bar
    const incomeBar = document.createElement("div");
    incomeBar.classList.add("bar");
    incomeBar.innerHTML = `
      <div class="bar__fill bar--income" style="height:${(income / maxVal) * 100}%"></div>
      <div class="bar__label">Income<br><b>$${income.toFixed(2)}</b></div>
    `;
    barChart.appendChild(incomeBar);

    // Expense bars by category
    if (categories.length === 0) {
      const noData = document.createElement("div");
      noData.classList.add("bar__label");
      noData.textContent = "No expenses yet.";
      barChart.appendChild(noData);
      return;
    }

    categories.forEach(cat => {
      const bar = document.createElement("div");
      bar.classList.add("bar");
      bar.innerHTML = `
        <div class="bar__fill bar--expense" style="height:${(cat.total / maxVal) * 100}%"></div>
        <div class="bar__label">${cat.name}<br><b>$${cat.total.toFixed(2)}</b></div>
      `;
      barChart.appendChild(bar);
    });
  } catch (err) {
    console.error("[Dashboard] Failed to update bar chart:", err);
  }
}

// Auto-run after page load
document.addEventListener("DOMContentLoaded", updateBarChart);

// === Improved Visible Bar Chart ===
async function updateBarChart() {
  try {
    const res = await fetch("/api/summary");
    if (!res.ok) throw new Error("API request failed");
    const data = await res.json();

    const barChart = document.getElementById("barChart");
    barChart.innerHTML = "";

    const { income = 0, categories = [] } = data;

    const maxVal = Math.max(income, ...categories.map(c => c.total)) || 1;

    const minHeight = 10; 
    const chartHeight = 220;

    const incomeBar = document.createElement("div");
    incomeBar.className = "bar";
    const incomeHeight = Math.max((income / maxVal) * chartHeight, minHeight);
    incomeBar.innerHTML = `
      <div class="bar__fill bar--income" style="height:${incomeHeight}px"></div>
      <div class="bar__label">Income<br><b>$${income.toFixed(2)}</b></div>
    `;
    barChart.appendChild(incomeBar);

    categories.forEach(cat => {
      const bar = document.createElement("div");
      bar.className = "bar";
      const expHeight = Math.max((cat.total / maxVal) * chartHeight, minHeight);
      bar.innerHTML = `
        <div class="bar__fill bar--expense" style="height:${expHeight}px"></div>
        <div class="bar__label">${cat.name}<br><b>$${cat.total.toFixed(2)}</b></div>
      `;
      barChart.appendChild(bar);
    });

  } catch (err) {
    console.error("[Dashboard] Chart render failed:", err);
  }
}

document.addEventListener("DOMContentLoaded", updateBarChart);
