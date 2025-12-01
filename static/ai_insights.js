// === AI Insights Page ===

const refreshAI = document.getElementById("refreshInsights");
const aiInsights = document.getElementById("insightsList");

async function loadInsights() {
  if (!aiInsights) return;

  // Show loading state
  aiInsights.innerHTML = "<li>Loading AI insights based on your recent spending…</li>";

  try {
    const res = await fetch("/api/ai-insights", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({}), // no extra payload needed
    });

    if (!res.ok) {
      throw new Error("Request failed with status " + res.status);
    }

    const data = await res.json();
    const insights = data.insights || [];

    if (!insights.length) {
      aiInsights.innerHTML =
        "<li>No insights available yet. Try connecting a bank account or adding some transactions.</li>";
      return;
    }

    aiInsights.innerHTML = insights.map((t) => `<li>${t}</li>`).join("");
  } catch (err) {
    console.error("AI insights error:", err);
    aiInsights.innerHTML =
      "<li>⚠️ Couldn't load AI insights right now. Please try again later.</li>";
  }
}

// Refresh button → fetch new 3 insights
if (refreshAI) {
  refreshAI.addEventListener("click", loadInsights);
}

// Auto-load on page start
document.addEventListener("DOMContentLoaded", loadInsights);
