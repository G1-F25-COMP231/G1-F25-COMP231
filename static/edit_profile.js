// static/edit_profile.js

document.addEventListener("DOMContentLoaded", () => {
  const enableBtn = document.getElementById("enable2FA");
  const disableBtn = document.getElementById("disable2FA");
  const qrContainer = document.getElementById("qrContainer");
  const qrImage = document.getElementById("qrImage");
  const qrSecret = document.getElementById("qrSecret");
  const msgBox = document.getElementById("twofaMessage");

  const profileForm = document.getElementById("profileForm");
  const profilePicInput = document.getElementById("profilePic");
  const profilePreview = document.getElementById("profilePreview");

  // -----------------------------
  // Load existing profile picture
  // -----------------------------
  loadProfilePicture();

  async function loadProfilePicture() {
    if (!window.userId) return;
    try {
      const res = await fetch(`/api/profile-picture/${window.userId}`);
      const data = await res.json();
      if (data.ok && data.image && profilePreview) {
        profilePreview.src = data.image;
      }
    } catch (err) {
      console.warn("[edit_profile] No profile picture found:", err);
    }
  }

  // -----------------------------
  // Preview new picture on select
  // -----------------------------
  if (profilePicInput && profilePreview) {
    profilePicInput.addEventListener("change", () => {
      const file = profilePicInput.files[0];
      if (!file) return;
      const url = URL.createObjectURL(file);
      profilePreview.src = url;
    });
  }

  // -----------------------------
  // Submit profile update form
  // -----------------------------
  if (profileForm) {
    profileForm.addEventListener("submit", async (e) => {
      e.preventDefault();

      const formData = new FormData(profileForm);

      try {
        const res = await fetch("/api/update-profile", {
          method: "POST",
          body: formData,
        });

        const data = await res.json();
        if (data.ok) {
          showMessage("✅ Profile updated successfully.", "success");

          // If server returned profilePic URL/base64, refresh preview
          if (data.user && data.user.profilePic && profilePreview) {
            profilePreview.src = data.user.profilePic;
          }
        } else {
          showMessage("⚠️ " + (data.message || "Failed to update profile."), "error");
        }
      } catch (err) {
        console.error("[edit_profile] Profile update failed:", err);
        showMessage("❌ Network error while saving profile.", "error");
      }
    });
  }

  // -----------------------------
  // 2FA handlers
  // -----------------------------
  check2FAStatus();

  if (enableBtn) {
    enableBtn.addEventListener("click", async () => {
      try {
        const res = await fetch("/api/setup-2fa", { method: "POST" });
        const data = await res.json();

        if (data.ok) {
          show2FAActive(data.qrCode, data.secret);
          showMessage("✅ 2FA has been activated successfully!", "success");
        } else {
          showMessage("⚠️ " + data.message, "error");
        }
      } catch (err) {
        console.error(err);
        showMessage("❌ Network error while enabling 2FA.", "error");
      }
    });
  }

  if (disableBtn) {
    disableBtn.addEventListener("click", async () => {
      if (!confirm("Are you sure you want to disable Two-Factor Authentication?")) return;

      try {
        const res = await fetch("/api/disable-2fa", { method: "POST" });
        const data = await res.json();

        if (data.ok) {
          show2FADisabled();
          showMessage("❌ 2FA has been disabled for your account.", "success");
        } else {
          showMessage("⚠️ " + data.message, "error");
        }
      } catch (err) {
        console.error(err);
        showMessage("❌ Network error while disabling 2FA.", "error");
      }
    });
  }

  // -----------------------------
  // 2FA helpers
  // -----------------------------
  async function check2FAStatus() {
    try {
      const res = await fetch("/api/2fa-status");
      const data = await res.json();

      if (data.ok && data.enabled) {
        show2FAActive(data.qrCode, data.secret);
      } else {
        show2FADisabled();
      }
    } catch (err) {
      console.error("[edit_profile] Failed to fetch 2FA status:", err);
    }
  }

  function show2FAActive(qrCode, secret) {
    if (!qrContainer) return;
    qrContainer.classList.remove("hidden");
    if (enableBtn) enableBtn.classList.add("hidden");
    if (disableBtn) disableBtn.classList.remove("hidden");

    if (qrImage && qrCode) qrImage.src = qrCode;
    if (qrSecret && secret) qrSecret.textContent = secret;
  }

  function show2FADisabled() {
    if (!qrContainer) return;
    qrContainer.classList.add("hidden");
    if (enableBtn) enableBtn.classList.remove("hidden");
    if (disableBtn) disableBtn.classList.add("hidden");
  }

  // Shared message UI
  function showMessage(msg, type = "success") {
    if (!msgBox) {
      alert(msg);
      return;
    }
    msgBox.textContent = msg;
    msgBox.classList.remove("hidden");
    msgBox.classList.toggle("error", type === "error");
    setTimeout(() => msgBox.classList.add("hidden"), 3000);
  }
});
