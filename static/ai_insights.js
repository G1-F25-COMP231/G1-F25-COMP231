// === AI Insights Page ===

// Button + List references
const refreshAI = document.getElementById('refreshInsights');
const aiInsights = document.getElementById('insightsList');

// Sample AI insight tips (like dashboard.js)
const tips = [
  '🚌 Try a transit pass this week — potential savings <b>$18</b>.',
  '🧾 Your subscriptions increased by <b>$6</b> MoM.',
  '🥦 Groceries are below average this week. Nice!',
  '🛍️ Consider a 48-hour rule for purchases over <b>$50</b>.',
  '💡 Pay off your credit card mid-cycle to improve utilization.',
  '💧 Small daily purchases add up — review your coffee spend.',
  '📊 You saved 12% more this month than last month. Great work!'
];

// Function to render 3 random tips
function renderAI() {
  const pick = Array.from({ length: 3 }, () => tips[Math.floor(Math.random() * tips.length)]);
  aiInsights.innerHTML = pick.map(t => `<li>${t}</li>`).join('');
}

// Event listener
if (refreshAI) {
  refreshAI.addEventListener('click', renderAI);
}

// Auto-load on page start
document.addEventListener('DOMContentLoaded', renderAI);
