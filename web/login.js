(() => {
  const form = document.getElementById("login-form");
  const tokenInput = document.getElementById("token");
  const button = document.getElementById("submit");
  const buttonLabel = document.getElementById("submit-label");
  const spinner = document.getElementById("spinner");
  const message = document.getElementById("message");

  document.getElementById("toggle-token").addEventListener("click", (event) => {
    const visible = tokenInput.type === "password";
    tokenInput.type = visible ? "text" : "password";
    event.currentTarget.textContent = visible ? "Ocultar" : "Mostrar";
    event.currentTarget.setAttribute("aria-label", visible ? "Ocultar token" : "Mostrar token");
  });

  document.getElementById("token").addEventListener("input", () => {
    message.textContent = "";
    message.classList.remove("success");
  });

  async function checkExistingSession() {
    try {
      const response = await fetch("/api/auth/session", { credentials: "same-origin", cache: "no-store" });
      const data = await response.json();
      if (data.authenticated) window.location.replace("/");
      if (!data.configured) message.textContent = "A autenticação remota não está configurada no servidor.";
    } catch {
      message.textContent = "Não foi possível contactar o servidor.";
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const token = tokenInput.value;
    if (!token) return;
    button.disabled = true;
    buttonLabel.textContent = "Verificando…";
    spinner.classList.remove("hidden");
    message.textContent = "";
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Não foi possível entrar.");
      tokenInput.value = "";
      window.location.replace("/");
    } catch (error) {
      message.textContent = error.message;
      tokenInput.focus();
      tokenInput.select();
    } finally {
      button.disabled = false;
      buttonLabel.textContent = "Entrar";
      spinner.classList.add("hidden");
    }
  });

  checkExistingSession();
})();
