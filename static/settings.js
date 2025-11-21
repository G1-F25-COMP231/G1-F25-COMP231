document.addEventListener("DOMContentLoaded", () => {
  console.log("[settings.js] DOM loaded");

  const toggleBtn = document.getElementById("toggleSidebar");
  const sidebar = document.getElementById("sidebar");
  if (toggleBtn && sidebar) {
    toggleBtn.addEventListener("click", () => {
      sidebar.classList.toggle("hidden");
    });
  }

  const saveBtn = document.getElementById("saveBtn");
  if (saveBtn) {
    saveBtn.addEventListener("click", () => {
      const total = document.getElementById("totalBudget").value;
      const categories = {
        groceries: document.getElementById("budgetGroceries").value,
        dining: document.getElementById("budgetDining").value,
        transport: document.getElementById("budgetTransport").value,
        bills: document.getElementById("budgetBills").value,
      };

      const data = { total, categories };

      try {
        localStorage.setItem("budgetSettings", JSON.stringify(data));
        alert("✅ Budget settings saved successfully!");
        console.log("[settings.js] Saved:", data);
      } catch (err) {
        console.error("Error saving budget settings:", err);
        alert("❌ Failed to save settings. Check console for details.");
      }
    });
  }

  console.log("[settings.js] Script initialized successfully");
});
