// static/shell.js

document.addEventListener("DOMContentLoaded", () => {
  const dashLink = document.getElementById("dashboardNav");
  if (!dashLink) return;

  const LOCAL_KEY = "useSimplifiedDashboard";

  dashLink.addEventListener("click", async (e) => {
    e.preventDefault();

    let useSimplified = null;

    // 1) Try localStorage flag first (set from settings/login code)
    try {
      const stored = localStorage.getItem(LOCAL_KEY);
      if (stored !== null) {
        useSimplified = stored === "true";
      }
    } catch (err) {
      console.warn("[shell.js] localStorage not available:", err);
    }

    // 2) If we don't know yet, ask backend preference
    if (useSimplified === null) {
      try {
        const res = await fetch("/api/user/dashboard_mode");
        if (res.ok) {
          const data = await res.json();
          if (data.ok && data.mode === "simplified") {
            useSimplified = true;
          } else {
            useSimplified = false;
          }
        } else {
          useSimplified = false;
        }
      } catch (err) {
        console.warn("[shell.js] /api/user/dashboard_mode failed:", err);
        useSimplified = false;
      }
    }

    // 3) Route based on preference
    if (useSimplified) {
      window.location.href = "/simplified-dashboard.html";
    } else {
      window.location.href = "/dashboard.html";
    }
  });
});
