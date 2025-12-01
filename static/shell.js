// static/shell.js

document.addEventListener("DOMContentLoaded", () => {
  const DASH_MODE_KEY = "bm_useSimplifiedDashboard";

  const dashLink   = document.getElementById("dashboardNav");
  const avatar     = document.getElementById("avatarBtn");
  const greeting   = document.getElementById("greetingText");
  const userId     = window.userId;

  /* ==============================
     Load greeting + avatar (same logic as dashboard.js)
     ============================== */
  (async () => {
    // ---- Greeting ----
    try {
      const res = await fetch("/api/user-profile");
      const data = await res.json();

      if (data.ok && data.user) {
        const user = data.user;
        const firstName = user.fullName
          ? user.fullName.split(" ")[0]
          : (user.username || user.email || "User");

        if (greeting) {
          greeting.textContent = `Hello, ${firstName}`;
        }
      }
    } catch (err) {
      console.error("[shell.js] Failed to load user profile:", err);
    }

    // ---- Avatar ----
    try {
      if (!userId || !avatar) return;

      const res = await fetch(`/api/profile-picture/${userId}`);
      const data = await res.json();

      if (data.ok && data.image) {
        // image is base64 / data URL from the API (same as dashboard.js)
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
      console.warn("[shell.js] No profile picture found.");
      if (avatar) {
        const initial =
          (greeting &&
            greeting.textContent &&
            greeting.textContent.replace("Hello, ", "").charAt(0)) || "U";
        avatar.textContent = initial;
      }
    }

    // Click avatar → edit profile
    if (avatar) {
      avatar.addEventListener("click", () => {
        window.location.href = "/edit-profile.html";
      });
    }
  })();

  /* ==============================
     Dashboard nav: decide route
     ============================== */
  if (dashLink) {
    dashLink.addEventListener("click", async (e) => {
      e.preventDefault();

      let useSimplified = null;

      // 1) Try localStorage flag first
      try {
        const stored = localStorage.getItem(DASH_MODE_KEY);
        if (stored !== null) {
          useSimplified = stored === "true";
        }
      } catch (err) {
        console.warn("[shell.js] localStorage not available:", err);
      }

      // 2) If still unknown, ask backend
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

      // 3) Route to correct dashboard
      if (useSimplified) {
        window.location.href = "/simplified-dashboard.html";
      } else {
        window.location.href = "/dashboard.html";
      }
    });
  }
});
