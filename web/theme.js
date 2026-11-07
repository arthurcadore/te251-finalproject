// Aplica o tema antes da primeira pintura: escolha salva no navegador ou, sem ela, o tema do sistema.
(() => {
  const KEY = "coletor-tema";
  const root = document.documentElement;
  const media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

  function saved() {
    try { return localStorage.getItem(KEY); } catch { return null; }
  }

  function apply(theme) {
    root.dataset.theme = theme;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme === "dark" ? "#0d131d" : "#f4f7fc");
  }

  const initial = saved() || (media && media.matches ? "dark" : "light");
  apply(initial);
  document.addEventListener("DOMContentLoaded", () => apply(root.dataset.theme));
  if (media) {
    media.addEventListener("change", (event) => {
      if (!saved()) apply(event.matches ? "dark" : "light");
    });
  }

  window.coletorTheme = {
    current: () => root.dataset.theme,
    toggle() {
      const next = root.dataset.theme === "dark" ? "light" : "dark";
      try { localStorage.setItem(KEY, next); } catch { /* sem armazenamento: vale só nesta página */ }
      apply(next);
      return next;
    },
  };
})();
