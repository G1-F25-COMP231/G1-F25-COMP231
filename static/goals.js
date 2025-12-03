// =============================
// Load goals when page loads
// =============================
document.addEventListener("DOMContentLoaded", () => {
  loadGoals();

  // Add button listener
  const addBtn = document.querySelector(".btn-primary");
  if (addBtn) {
    addBtn.addEventListener("click", createGoal);
  }
});


// =============================
// Fetch and display all goals
// =============================
async function loadGoals() {
  const container = document.getElementById("goalsContainer");
  if (!container) return;

  try {
    const res = await fetch("/api/goals");
    const goals = await res.json();

    container.innerHTML = ""; // clear

    if (!goals || goals.length === 0) {
      container.innerHTML = `<p style="color:#8091a3;">No goals created yet.</p>`;
      return;
    }

    goals.forEach(goal => {
      const percent =
        goal.target_amount > 0
          ? Math.min(100, Math.round((goal.current_amount / goal.target_amount) * 100))
          : 0;

      const html = `
        <div class="goal-item">

          <div class="goal-top">
            <div class="goal-name">${goal.name}</div>
            <div class="goal-amount">$${goal.current_amount} / $${goal.target_amount}</div>
          </div>

          <div class="progress-bar">
            <div class="progress" style="width: ${percent}%;"></div>
          </div>

          <div class="goal-percent">${percent}% complete</div>

        </div>
      `;

      container.innerHTML += html;
    });

  } catch (err) {
    console.error("Failed to load goals:", err);
  }
}



// =============================
// Create a new goal
// =============================
async function createGoal() {
  const inputs = document.querySelectorAll(".input");

  const name = inputs[0].value.trim();
  const target = inputs[1].value;
  const current = inputs[2].value;
  const deadline = inputs[3].value;

  if (!name || !target) {
    alert("Please provide a goal name and target.");
    return;
  }

  const payload = {
    name,
    target_amount: parseFloat(target),
    current_amount: parseFloat(current || 0),
    deadline
  };

  try {
    const res = await fetch("/api/goals", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload)
    });

    const data = await res.json();

    if (data.message === "Goal created") {
      // Clear inputs
      inputs.forEach(i => (i.value = ""));

      // Reload goals
      loadGoals();
    }

  } catch (err) {
    console.error("Failed to create goal:", err);
  }
}
