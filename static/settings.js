document.addEventListener("DOMContentLoaded", () => {
  console.log("[settings.js] DOM loaded");

  const DASH_MODE_KEY = "bm_useSimplifiedDashboard";

  const toggleBtn = document.getElementById("toggleSidebar");
  const sidebar = document.getElementById("sidebar");
  const saveBtn = document.getElementById("saveBtn");

  const budgetCard = document.getElementById("budgetCard");
  const budgetLockedBanner = document.getElementById("budgetLockedBanner");

  const totalBudgetInput = document.getElementById("totalBudget");
  const budgetGroceriesInput = document.getElementById("budgetGroceries");
  const budgetDiningInput = document.getElementById("budgetDining");
  const budgetTransportInput = document.getElementById("budgetTransport");
  const budgetBillsInput = document.getElementById("budgetBills");

  const advisorCard = document.getElementById("advisorLockCard");
  const advisorSelect = document.getElementById("advisorSelect");
  const addAdvisorBtn = document.getElementById("addAdvisorBtn");
  const advisorActionMessage = document.getElementById("advisorActionMessage");

  // NEW: Simplified dashboard toggle elements
  const simplifiedToggle = document.getElementById("simplifiedDashboardToggle");
  const simplifiedStatus = document.getElementById("simplifiedDashboardStatus");

  const budgetInputs = [
    totalBudgetInput,
    budgetGroceriesInput,
    budgetDiningInput,
    budgetTransportInput,
    budgetBillsInput,
  ];

  /* ==============================
     Sidebar toggle
     ============================== */
  if (toggleBtn && sidebar) {
    toggleBtn.addEventListener("click", () => {
      sidebar.classList.toggle("hidden");
    });
  }

  /* ==============================
     Save budget (when NOT locked)
     ============================== */
  if (saveBtn) {
    saveBtn.addEventListener("click", () => {
      const limit = totalBudgetInput.value;

      if (!limit || Number(limit) <= 0) {
        alert("Please enter a valid monthly budget.");
        return;
      }

      fetch("/api/user/update_spending_limit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limit }),
      })
        .then((res) => res.json())
        .then((data) => {
          if (data.ok) {
            alert(
              "✅ Monthly budget updated! Your advisor (if any) will now see this limit."
            );
            console.log("[settings.js] Updated spending limit:", data.limit);

            const categories = {
              groceries: budgetGroceriesInput.value,
              dining: budgetDiningInput.value,
              transport: budgetTransportInput.value,
              bills: budgetBillsInput.value,
            };

            localStorage.setItem(
              "budgetSettings",
              JSON.stringify({
                total: limit,
                categories,
              })
            );
          } else {
            alert("❌ Failed to update limit: " + (data.message || "Unknown"));
          }
        })
        .catch((err) => {
          console.error("Error updating spending limit:", err);
          alert("❌ Error connecting to server.");
        });
    });
  }

  /* ==============================
     Lock / unlock budget controls
     ============================== */
  function setBudgetLocked(isLocked, info) {
    if (!budgetCard) return;

    if (isLocked) {
      budgetCard.classList.add("locked");
      budgetInputs.forEach((input) => {
        if (input) input.disabled = true;
      });
      if (saveBtn) {
        saveBtn.disabled = true;
      }
      if (budgetLockedBanner) {
        const riskText = info?.risk_level
          ? info.risk_level.toUpperCase()
          : "UNKNOWN";

        const percentLeft =
          typeof info?.percent_income_left === "number"
            ? info.percent_income_left.toFixed(2)
            : null;

        budgetLockedBanner.textContent =
          percentLeft !== null
            ? `Your budget controls are locked because our system detected a ${riskText} financial vulnerability (${percentLeft}% of your income left in the current period). Please connect with a Financial Advisor for support.`
            : `Your budget controls are locked because our system detected financial vulnerability. Please connect with a Financial Advisor for support.`;

        budgetLockedBanner.classList.remove("hidden");
      }

      if (advisorCard) {
        advisorCard.classList.remove("hidden");
      }
    } else {
      budgetCard.classList.remove("locked");
      budgetInputs.forEach((input) => {
        if (input) input.disabled = false;
      });
      if (saveBtn) {
        saveBtn.disabled = false;
      }
      if (budgetLockedBanner) {
        budgetLockedBanner.classList.add("hidden");
      }
      if (advisorCard) {
        advisorCard.classList.add("hidden");
      }
    }
  }

  /* ==============================
     Load advisor list for dropdown
     ============================== */
  function loadAdvisors() {
    if (!advisorSelect) return;

    advisorSelect.innerHTML =
      '<option value="">Select a Financial Advisor...</option>';

    fetch("/api/user/advisors")
      .then((res) => res.json())
      .then((data) => {
        if (!data.ok) {
          console.warn("[settings.js] Failed to load advisors:", data.message);
          return;
        }

        (data.advisors || []).forEach((advisor) => {
          const opt = document.createElement("option");
          opt.value = advisor.id;
          const labelName = advisor.name || "Advisor";
          const labelEmail = advisor.email ? ` (${advisor.email})` : "";
          opt.textContent = labelName + labelEmail;
          advisorSelect.appendChild(opt);
        });
      })
      .catch((err) => {
        console.error("[settings.js] Error loading advisors:", err);
      });
  }

  /* ==============================
     Handle "Add Advisor" click
     ============================== */
  if (addAdvisorBtn && advisorSelect) {
    addAdvisorBtn.addEventListener("click", () => {
      const advisorId = advisorSelect.value;
      if (!advisorId) {
        alert("Please select an advisor first.");
        return;
      }

      advisorActionMessage.textContent = "Sending request...";
      advisorActionMessage.style.color = "#b8c4d1";

      fetch("/api/user/select_advisor", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ advisor_id: advisorId }),
      })
        .then((res) => res.json())
        .then((data) => {
          if (!data.ok) {
            advisorActionMessage.textContent =
              data.message || "Could not add advisor.";
            advisorActionMessage.style.color = "#ff6b6b";
            return;
          }

          advisorActionMessage.textContent =
            data.message || "Advisor added successfully.";
          advisorActionMessage.style.color = "#6bff95";
        })
        .catch((err) => {
          console.error("Error selecting advisor:", err);
          advisorActionMessage.textContent =
            "Something went wrong. Please try again.";
          advisorActionMessage.style.color = "#ff6b6b";
        });
    });
  }

  /* ==============================
     Check if user is financially vulnerable
     ============================== */
  function checkFinancialStatus() {
    fetch("/api/user/financial_status")
      .then((res) => res.json())
      .then((data) => {
        if (!data.ok) {
          console.warn(
            "[settings.js] Could not fetch financial status:",
            data.message
          );
          return;
        }

        if (data.vulnerable) {
          console.log(
            "[settings.js] User is financially vulnerable:",
            data.risk_level
          );
          setBudgetLocked(true, data);
          loadAdvisors();
        } else {
          console.log("[settings.js] User is NOT flagged as vulnerable");
          setBudgetLocked(false, null);
        }
      })
      .catch((err) => {
        console.error("[settings.js] Error fetching financial status:", err);
      });
  }

  /* ==============================
     Simplified Dashboard toggle
     ============================== */
  function initSimplifiedDashboardToggle() {
    if (!simplifiedToggle || !simplifiedStatus) return;

    const stored = localStorage.getItem(DASH_MODE_KEY);
    const enabled = stored === "true";

    simplifiedToggle.checked = enabled;
    simplifiedStatus.textContent = enabled
      ? "Simplified Dashboard will open after you log in."
      : "Full Dashboard will open after you log in.";

    simplifiedToggle.addEventListener("change", () => {
      const on = simplifiedToggle.checked;
      localStorage.setItem(DASH_MODE_KEY, on ? "true" : "false");
      simplifiedStatus.textContent = on
        ? "Simplified Dashboard will open after you log in."
        : "Full Dashboard will open after you log in.";
    });
  }

  // Kick everything off
  checkFinancialStatus();
  initSimplifiedDashboardToggle();

  console.log("[settings.js] Script initialized successfully");
});
