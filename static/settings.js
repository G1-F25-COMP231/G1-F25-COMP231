document.addEventListener("DOMContentLoaded", () => {
  console.log("[settings.js] DOM loaded");

  const toggleBtn = document.getElementById("toggleSidebar");
  const sidebar = document.getElementById("sidebar");
  const saveBtn = document.getElementById("saveBtn"); // ✅ FIXED

  if (toggleBtn && sidebar) {
    toggleBtn.addEventListener("click", () => {
      sidebar.classList.toggle("hidden");
    });
  }

  if (saveBtn) {
    saveBtn.addEventListener("click", () => {
      const limit = document.getElementById("totalBudget").value;

      if (!limit || Number(limit) <= 0) {
        alert("Please enter a valid monthly budget.");
        return;
      }

      // 🔥 SEND TO BACKEND
      fetch("/api/user/update_spending_limit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limit })
      })
        .then((res) => res.json())
        .then((data) => {
          if (data.ok) {
            alert("✅ Monthly budget updated! Your advisor will now see this limit.");
            console.log("[settings.js] Updated spending limit:", data.limit);

            // Save categories locally (optional)
            const categories = {
              groceries: document.getElementById("budgetGroceries").value,
              dining: document.getElementById("budgetDining").value,
              transport: document.getElementById("budgetTransport").value,
              bills: document.getElementById("budgetBills").value,
            };

            localStorage.setItem("budgetSettings", JSON.stringify({
              total: limit,
              categories
            }));
          } else {
            alert("❌ Failed to update limit: " + data.message);
          }
        })
        .catch((err) => {
          console.error("Error updating spending limit:", err);
          alert("❌ Error connecting to server.");
        });
    });
  }

  console.log("[settings.js] Script initialized successfully");
});
