document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("forgotForm");
  const email = document.getElementById("email");
  const newPassword = document.getElementById("newPassword");
  const msg = document.getElementById("statusMsg");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    msg.textContent = "⏳ Sending request...";
    msg.style.color = "#ffc107";

    try {
      const res = await fetch("/api/forgot-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: email.value.trim(),
          newPassword: newPassword.value.trim(),
        }),
      });

      const data = await res.json();
      if (res.ok && data.ok) {
        msg.textContent = "✅ Password reset successfully! Redirecting...";
        msg.style.color = "#5df2a9";

        // redirect back to login after 2 seconds
        setTimeout(() => (window.location.href = "/"), 2000);
      } else {
        msg.textContent = `⚠️ ${data.message || "Failed to reset password."}`;
        msg.style.color = "#ff9f9f";
      }
    } catch (err) {
      console.error("[Forgot Password] Network error:", err);
      msg.textContent = "⚠️ Network error while resetting password.";
      msg.style.color = "#ff9f9f";
    }
  });
});
