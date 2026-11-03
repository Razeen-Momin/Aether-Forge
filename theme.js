(function () {
  // Apply the saved theme immediately so the page doesn't flash
  const saved = localStorage.getItem("af-theme") || "dark";
  document.documentElement.setAttribute("data-theme", saved);

  document.addEventListener("DOMContentLoaded", function () {
    const btn = document.getElementById("themeToggle");
    if (!btn) return;

    function refreshIcon() {
      const theme = document.documentElement.getAttribute("data-theme");
      btn.textContent = theme === "light" ? "🌙" : "☀️";
    }

    btn.addEventListener("click", function () {
      const current = document.documentElement.getAttribute("data-theme");
      const next = current === "light" ? "dark" : "light";
      document.documentElement.setAttribute("data-theme", next);
      localStorage.setItem("af-theme", next);
      refreshIcon();
    });

    refreshIcon();
  });
})();
