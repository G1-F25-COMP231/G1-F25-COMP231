// Sidebar toggle
const toggleBtn = document.getElementById("toggleSidebar");
const sidebar = document.getElementById("sidebar");
toggleBtn.addEventListener("click", () => sidebar.classList.toggle("hidden"));


// -------------------------------
// LOAD SETTINGS FROM BACKEND
// -------------------------------
async function loadSettings() {
  const res = await fetch("/api/compliance/get_settings");
  const data = await res.json();

  if (!data.ok) return;

  const s = data.settings;

  document.getElementById("toggleMasking").checked = s.enable_data_masking;
  document.getElementById("toggleIpLogging").checked = s.enable_ip_logging;
  document.getElementById("toggleAutoAnon").checked = s.auto_anonymize;

  document.getElementById("toggleCritical").checked = s.notify_critical;
  document.getElementById("toggleAdminActions").checked = s.track_admin;

  document.getElementById("retentionSelect").value = s.retention_days;
}

loadSettings();


// -------------------------------
// SAVE SETTINGS TO BACKEND
// -------------------------------
async function saveSettings() {
  const payload = {
    enable_data_masking: document.getElementById("toggleMasking").checked,
    enable_ip_logging: document.getElementById("toggleIpLogging").checked,
    auto_anonymize: document.getElementById("toggleAutoAnon").checked,
    notify_critical: document.getElementById("toggleCritical").checked,
    track_admin: document.getElementById("toggleAdminActions").checked,
    retention_days: document.getElementById("retentionSelect").value
  };

  await fetch("/api/compliance/save_settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}


// -------------------------------
// ADD EVENT LISTENERS
// -------------------------------
[
  "toggleMasking",
  "toggleIpLogging",
  "toggleAutoAnon",
  "toggleCritical",
  "toggleAdminActions"
].forEach(id => {
  const el = document.getElementById(id);
  el.addEventListener("change", saveSettings);
});

document.getElementById("retentionSelect")
  .addEventListener("change", saveSettings);


// -------------------------------
// Export Logs Button
// -------------------------------
document.getElementById("exportLogs").addEventListener("click", async () => {
  const res = await fetch("/api/compliance/export_csv");
  if (!res.ok) return alert("Failed to export logs");

  const csv = await res.text();
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);

  const link = document.createElement("a");
  link.href = url;
  link.download = "audit_logs.csv";
  link.click();

  URL.revokeObjectURL(url);
});
