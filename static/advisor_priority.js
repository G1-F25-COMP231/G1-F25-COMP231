console.log("[advisor_priority.js] Loaded");

let selectedPriority = null;

// highlight selected option
document.querySelectorAll(".priority-option").forEach(opt => {
    opt.addEventListener("click", () => {
        selectedPriority = opt.dataset.level;

        document.querySelectorAll(".priority-option")
            .forEach(o => o.classList.remove("selected"));

        opt.classList.add("selected");
    });
});

async function savePriority() {
    console.log("Save clicked. Selected:", selectedPriority);

    if (!selectedPriority) {
        alert("Please choose a priority level first.");
        return;
    }

    const clientId = localStorage.getItem("selectedClientId");

    console.log("Loaded client ID:", clientId);

    if (!clientId) {
        alert("No client selected — open Client List and pick one.");
        return;
    }

    const res = await fetch("/api/advisor/set_priority", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            client_id: clientId,
            priority: selectedPriority
        })
    });

    const data = await res.json();
    console.log("Server response:", data);

    if (!data.ok) {
        alert("Failed to update priority.");
        return;
    }

    alert("Priority updated!");
}
