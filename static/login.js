// --- Helpers --------------------------------------------------------------
const $ = (sel, root = document) => root.querySelector(sel);

// Shared localStorage key for dashboard mode
const DASH_MODE_KEY = "bm_useSimplifiedDashboard";
const LAST_ID_KEY = "lastLoginIdentifier";

const patterns = {
  identifier(emailOrUser) {
    const value = emailOrUser.trim();
    const email = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/i;
    const user = /^[A-Za-z0-9._]{3,30}$/;
    return email.test(value) || user.test(value);
  },
  password(pw) {
    return /^(?=.*\d)(?=.*[^A-Za-z0-9]).{8,}$/.test(pw);
  },
  twofa(code) {
    return /^\d{6}$/.test(code);
  }
};

function setError(el, msg) {
  el.textContent = msg || "";
}

function getUseSimplifiedDashboard() {
  return localStorage.getItem(DASH_MODE_KEY) === "true";
}

function setUseSimplifiedDashboard(enabled) {
  localStorage.setItem(DASH_MODE_KEY, enabled ? "true" : "false");
  if (simplifiedToggleLogin) simplifiedToggleLogin.checked = enabled;
  if (simplifiedLoginHint) {
    simplifiedLoginHint.textContent = enabled
      ? "You will be redirected to the Simplified Dashboard after login."
      : "You will be redirected to the full Dashboard after login.";
  }
}

// --- Form elements --------------------------------------------------------
const form = $("#loginForm");
const idInput = $("#identifier");
const pwInput = $("#password");
const idError = $("#idError");
const pwError = $("#pwError");
const submitBtn = $("#submitBtn");
const formStatus = $("#formStatus");

// NEW: Simplified dashboard toggle on login page
const simplifiedToggleLogin = document.getElementById("simplifiedDashboardToggleLogin");
const simplifiedLoginHint = document.getElementById("simplifiedDashboardHint");

// --- Validation -----------------------------------------------------------
function validateIdentifier() {
  const ok = patterns.identifier(idInput.value);
  setError(idError, ok ? "" : "Enter a valid email or username.");
  return ok;
}

function validatePassword() {
  const ok = patterns.password(pwInput.value);
  setError(pwError, ok ? "" : "Password must be 8+ chars with a number and special character.");
  return ok;
}

function updateSubmitState() {
  submitBtn.disabled = !(validateIdentifier() && validatePassword());
}

idInput.addEventListener("input", updateSubmitState);
pwInput.addEventListener("input", updateSubmitState);

// Toggle password visibility
$("#togglePw").addEventListener("click", (e) => {
  const isPw = pwInput.type === "password";
  pwInput.type = isPw ? "text" : "password";
  e.currentTarget.textContent = isPw ? "Hide" : "Show";
  e.currentTarget.setAttribute("aria-label", isPw ? "Hide password" : "Show password");
});

// Forgot password link
document.addEventListener("DOMContentLoaded", () => {
  const forgotLink = document.getElementById("forgotLink");

  if (forgotLink) {
    forgotLink.addEventListener("click", (e) => {
      e.preventDefault();
      window.location.href = "/forgot_password.html";
    });
  } else {
    console.warn("[login.js] #forgotLink not found in DOM");
  }
});

// Wire up simplified-dashboard toggle
if (simplifiedToggleLogin) {
  simplifiedToggleLogin.addEventListener("change", () => {
    setUseSimplifiedDashboard(simplifiedToggleLogin.checked);
  });
}

// --- 2FA elements ---------------------------------------------------------
const twofaDialog = $("#twofaDialog");
const twofaForm = $("#twofaForm");
const cancel2fa = $("#cancel2fa");
const twofaInput = $("#twofa");
const faError = $("#faError");

// --- Submit: /api/login ---------------------------------------------------
form.addEventListener("submit", async (e) => {
  e.preventDefault();

  if (!(validateIdentifier() && validatePassword())) {
    formStatus.textContent = "Please fix the highlighted fields.";
    return;
  }

  formStatus.textContent = "Checking credentials…";

  try {
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        identifier: idInput.value.trim(),
        password: pwInput.value.trim()
      })
    });

    const data = await res.json();

    if (!res.ok || !data.ok) {
      formStatus.textContent = data.message || "Invalid credentials.";
      return;
    }

    // 2FA required
    if (data.require_2fa) {
      formStatus.textContent = "Credentials accepted. Please verify your code.";
      twofaInput.value = "";
      setError(faError, "");
      twofaDialog.showModal();
      setTimeout(() => twofaInput.focus(), 100);
      return;
    }

    // Successful login without 2FA → redirect based on simplified toggle
    const useSimplified = getUseSimplifiedDashboard();
    let target = data.redirect || "/dashboard.html";
    if (useSimplified) target = "/simplified-dashboard.html";

    window.location.href = target;
  } catch (err) {
    console.error(err);
    formStatus.textContent = "Network error. Please try again.";
  }
});

// --- 2FA submit: /api/verify-2fa ------------------------------------------
twofaForm.addEventListener("submit", async (e) => {
  e.preventDefault();

  const code = twofaInput.value.trim();
  if (!patterns.twofa(code)) {
    setError(faError, "Enter the 6-digit code.");
    return;
  }

  setError(faError, "");
  formStatus.textContent = "Verifying code…";

  try {
    const res = await fetch("/api/verify-2fa", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code })
    });

    const data = await res.json();

    if (!res.ok || !data.ok) {
      setError(faError, data.message || "Invalid code.");
      formStatus.textContent = "Two-factor verification failed.";
      return;
    }

    twofaDialog.close();
    formStatus.textContent = "Welcome back! Redirecting to your dashboard…";

    const useSimplified = getUseSimplifiedDashboard();
    let target = data.redirect || "/dashboard.html";
    if (useSimplified) target = "/simplified-dashboard.html";

    window.location.href = target;
  } catch (err) {
    console.error(err);
    setError(faError, "Network error. Try again.");
    formStatus.textContent = "Network error. Try again.";
  }
});

// --- Cancel 2FA -----------------------------------------------------------
if (cancel2fa) {
  cancel2fa.addEventListener("click", () => {
    twofaDialog.close();
    formStatus.textContent = "Two-factor verification cancelled.";
  });
}

// Initialize submit state
updateSubmitState();

// ✅ Session-check: if already logged in, go straight to the right dashboard
window.addEventListener("DOMContentLoaded", async () => {
  try {
    const res = await fetch("/api/summary"); // simple auth-check endpoint
    if (res.ok) {
      const page = window.location.pathname;
      if (page.includes("login")) {
        const useSimplified = getUseSimplifiedDashboard();
        const target = useSimplified
          ? "/simplified-dashboard.html"
          : "/dashboard.html";
        console.log("[login.js] Session active. Redirecting to", target);
        window.location.href = target;
      }
    }
  } catch (err) {
    console.log("[login.js] Not logged in yet — continue to login.");
  }
});

// ✅ Auto-focus + last-identifier + init simplified toggle
document.addEventListener("DOMContentLoaded", () => {
  // Autofill last login identifier
  const last = localStorage.getItem(LAST_ID_KEY);
  if (last && idInput && !idInput.value) idInput.value = last;

  // Initialize simplified toggle from stored preference
  const enabled = getUseSimplifiedDashboard();
  setUseSimplifiedDashboard(enabled);

  updateSubmitState();

  // Auto-focus identifier field if empty
  if (idInput && !idInput.value) idInput.focus();
});

// ✅ Store last successful login identifier
async function storeLoginIdentifier(identifier) {
  localStorage.setItem(LAST_ID_KEY, identifier);
}
form.addEventListener("submit", () => {
  const identifier = idInput.value.trim();
  if (patterns.identifier(identifier)) storeLoginIdentifier(identifier);
});
