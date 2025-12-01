// === AI Insights Page (real AI) ===

// Fallback tips if the AI endpoint fails
const insightsFallback = [
  "🚌 Try a transit pass this week — potential savings <b>$18</b>.",
  "🧾 Your subscriptions increased slightly — review and cancel any you don’t use.",
  "🥦 Groceries look solid — keep planning meals to avoid last-minute takeout.",
  "🛍️ Use a 48-hour rule before any purchase over <b>$50</b>.",
  "💡 Pay your credit card before the statement date to lower utilization.",
  "💧 Small daily purchases add up — track coffee/snack spending for one week.",
  "📊 Pick one category to reduce by 10% this month and move the savings aside."
];

async function loadInsightsPageTips() {
  const listEl = document.getElementById("insightsList");
  if (!listEl) return;

  // Show loading state
  listEl.innerHTML = `<li>🔍 Loading insights…</li>`;

  try {
    const res = await fetch("/api/ai-insights", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}) // no extra data needed
    });

    const data = await res.json();

    let tips = [];
    if (data && Array.isArray(data.insights) && data.insights.length > 0) {
      tips = data.insights;
    } else {
      tips = insightsFallback;
    }

    listEl.innerHTML = tips.map((t) => `<li>${t}</li>`).join("");
  } catch (err) {
    console.error("[AI Insights] Failed to load AI insights:", err);
    listEl.innerHTML = insightsFallback.map((t) => `<li>${t}</li>`).join("");
  }
}

// Wire up when DOM is ready
document.addEventListener("DOMContentLoaded", () => {
  const refreshBtn = document.getElementById("refreshInsights");

  if (refreshBtn) {
    refreshBtn.addEventListener("click", (e) => {
      e.preventDefault();
      loadInsightsPageTips();
    });
  }

  // Auto-load on page load
  loadInsightsPageTips();
});
