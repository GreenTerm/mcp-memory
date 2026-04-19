(() => {
  const storage = window.localStorage;
  const root = document.documentElement;

  const applyTheme = (theme) => {
    const nextTheme = theme === "light" ? "light" : "dark";
    root.dataset.theme = nextTheme;
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.setAttribute("aria-pressed", String(nextTheme === "light"));
    });
  };

  const savedTheme = storage.getItem("mcp-memory-theme");
  if (savedTheme) {
    applyTheme(savedTheme);
  }

  document.addEventListener("click", async (event) => {
    const themeToggle = event.target.closest("[data-theme-toggle]");
    if (themeToggle) {
      const nextTheme = root.dataset.theme === "light" ? "dark" : "light";
      storage.setItem("mcp-memory-theme", nextTheme);
      applyTheme(nextTheme);
      return;
    }

    const sidebarToggle = event.target.closest("[data-sidebar-toggle]");
    if (sidebarToggle) {
      const collapsed = document.body.classList.toggle("sidebar-collapsed");
      storage.setItem("mcp-memory-sidebar-collapsed", collapsed ? "1" : "0");
      sidebarToggle.setAttribute("aria-expanded", String(!collapsed));
      return;
    }

    const copyButton = event.target.closest("[data-copy-target]");
    if (!copyButton) {
      return;
    }

    const target = document.querySelector(copyButton.dataset.copyTarget);
    const text = target ? target.textContent.trim() : copyButton.dataset.copyText || "";
    if (!text || !navigator.clipboard) {
      return;
    }

    await navigator.clipboard.writeText(text);
    const previousLabel = copyButton.textContent;
    copyButton.textContent = copyButton.dataset.copiedLabel || "Copied";
    window.setTimeout(() => {
      copyButton.textContent = previousLabel;
    }, 1400);
  });

  if (storage.getItem("mcp-memory-sidebar-collapsed") === "1") {
    document.body.classList.add("sidebar-collapsed");
    document.querySelectorAll("[data-sidebar-toggle]").forEach((button) => {
      button.setAttribute("aria-expanded", "false");
    });
  }
})();
