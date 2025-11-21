document.addEventListener("DOMContentLoaded", () => {
  console.log("[register.js] DOM loaded");

  const form = document.getElementById("registerForm");
  const fullName = document.getElementById("fullname"); // matches HTML
  const username = document.getElementById("username");
  const email = document.getElementById("email");
  const password = document.getElementById("password");
  const confirmPassword = document.getElementById("confirmPassword");
  const role = document.getElementById("role");
  const terms = document.getElementById("terms");
  const submitBtn = form ? form.querySelector(".btn") : null;
  const togglePassword = document.getElementById("togglePassword");

  if (!form || !fullName || !username || !email || !password || !confirmPassword || !terms || !submitBtn) {
    console.error("[register.js] Missing required form elements.");
    return;
  }

  const showError = (input, message) => {
    if (!input) return;
    let error = input.parentElement.querySelector(".error");
    if (!error) {
      error = document.createElement("div");
      error.className = "error";
      input.parentElement.appendChild(error);
    }
    error.textContent = message;
  };

  const clearError = (input) => {
    if (!input) return;
    const error = input.parentElement.querySelector(".error");
    if (error) error.textContent = "";
  };

  const isValidEmail = (value) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
  const isStrongPassword = (value) => /^(?=.*[0-9])(?=.*[!@#$%^&*])(?=.{8,})/.test(value);

  const validateForm = () => {
    let valid = true;

    if (fullName.value.trim().split(" ").length < 2) {
      showError(fullName, "Enter your full name (first and last).");
      valid = false;
    } else clearError(fullName);

    if (username.value.trim().length < 3) {
      showError(username, "Username must be at least 3 characters.");
      valid = false;
    } else clearError(username);

    if (!isValidEmail(email.value.trim())) {
      showError(email, "Enter a valid email address.");
      valid = false;
    } else clearError(email);

    if (!isStrongPassword(password.value)) {
      showError(password, "Min 8 chars, 1 number, 1 special char.");
      valid = false;
    } else clearError(password);

    if (!confirmPassword.value || confirmPassword.value !== password.value) {
      showError(confirmPassword, "Passwords do not match.");
      valid = false;
    } else clearError(confirmPassword);

    if (!terms.checked) {
      showError(terms, "You must accept the terms to continue.");
      valid = false;
    } else clearError(terms);

    return valid;
  };

  // Toggle password visibility
  if (togglePassword) {
    togglePassword.addEventListener("click", () => {
      const type = password.getAttribute("type") === "password" ? "text" : "password";
      password.setAttribute("type", type);
      togglePassword.textContent = type === "password" ? "Show" : "Hide";
    });
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const valid = validateForm();
    if (!valid) return;

    submitBtn.disabled = true;
    const originalText = submitBtn.textContent;
    submitBtn.textContent = "Creating account…";

    try {
      const res = await fetch("/api/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          fullName: fullName.value.trim(),
          username: username.value.trim(),
          email: email.value.trim(),
          password: password.value,
          role: role ? role.value : ""
        }),
      });

      const data = await res.json().catch(() => ({}));
      console.log("[register.js] /api/register response:", res.status, data);

      if (!res.ok || !data.ok) {
        alert(data.message || "Registration failed.");
        submitBtn.disabled = false;
        submitBtn.textContent = originalText;
        return;
      }

      // ✅ Direct redirect after account creation
      window.location.href = data.redirect || "/dashboard.html";

    } catch (err) {
      console.error("[register.js] Network error:", err);
      alert("Network error. Please try again.");
      submitBtn.disabled = false;
      submitBtn.textContent = originalText;
    }
  });

  console.log("[register.js] Initialized successfully");
});
