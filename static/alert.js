(function (global) {
  const root = document.getElementById("alerts-root");

  const ICONS = {
    success:
      '<svg width="16" height="16" viewBox="0 0 24 24"><path d="M20 6L9 17l-5-5" stroke="currentColor" stroke-width="2" fill="none"/></svg>',
    info:
      '<svg width="16" height="16" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2" fill="none"/><path d="M12 8h.01M11 12h1v4h1" stroke="currentColor" stroke-width="2"/></svg>',
    warning:
      '<svg width="16" height="16" viewBox="0 0 24 24"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" fill="currentColor"/><path d="M12 9v4M12 17h.01" stroke="#fff" stroke-width="2"/></svg>',
    danger:
      '<svg width="16" height="16" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" fill="currentColor"/><path d="M15 9l-6 6M9 9l6 6" stroke="#fff" stroke-width="2"/></svg>',
  };

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, m => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;"
    })[m]);
  }

  function closeAlert(alert) {
    if (alert._closing) return;
    alert._closing = true;
    clearTimeout(alert._timer);

    alert.classList.remove("show");
    alert.addEventListener("transitionend", () => alert.remove());
  }

  function createAlert({ type, title, message, timeout, dismissible }) {
    const el = document.createElement("div");
    el.className = `alert alert--${type}`;
    el.innerHTML = `
      <div class="icon">${ICONS[type]}</div>
      <div class="content">
        ${title ? `<div class="title">${escapeHtml(title)}</div>` : ""}
        <div class="msg">${escapeHtml(message)}</div>
      </div>
      <button class="close">&times;</button>
      <div class="progress"><i></i></div>
    `;

    if (!dismissible) el.querySelector(".close").style.display = "none";

    // close button
    el.querySelector(".close").addEventListener("click", () => closeAlert(el));

    // auto close
    if (timeout > 0) {
      const bar = el.querySelector(".progress i");
      bar.style.transitionDuration = timeout + "ms";
      requestAnimationFrame(() => (bar.style.transform = "scaleX(1)"));

      el._timer = setTimeout(() => closeAlert(el), timeout);
    } else {
      el.querySelector(".progress").style.display = "none";
    }

    return {
      node: el,
      show() {
        root.prepend(el);
        requestAnimationFrame(() => el.classList.add("show"));
      },
      close() {
        closeAlert(el);
      }
    };
  }

  const Alert = {
    notify(type, title, message, timeout = 4000, dismissible = true) {
      const alert = createAlert({ type, title, message, timeout, dismissible });
      alert.show();
      return alert;
    }
  };

  global.Alert = Alert;
})(window);
