(() => {
  const $ = (id) => document.getElementById(id);
  const STORAGE_KEY = "coletor-artigos-form";
  const views = { nova: $("view-nova"), historico: $("view-historico") };
  let lastRunStage = "ocioso";
  let toastTimer;
  let preferredModel = "qwen3.5:0.8b";
  let modelRefreshInProgress = false;
  let selectModelsRequested = false;

  const checkedValues = (id) => [...document.querySelectorAll(`#${id} input[type=checkbox]:checked`)].map((item) => item.value);
  const fillChecks = (id, values = []) => document.querySelectorAll(`#${id} input[type=checkbox]`).forEach((item) => { item.checked = values.includes(item.value); });
  const optionalInteger = (id) => $(id).value.trim() ? Number.parseInt($(id).value, 10) : null;

  function notify(message, error = false) {
    let toast = $("toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "toast";
      toast.className = "toast";
      toast.setAttribute("role", "status");
      document.body.append(toast);
    }
    toast.textContent = message;
    toast.classList.toggle("error", error);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.remove(), 3300);
  }

  function setView(viewName) {
    Object.entries(views).forEach(([name, element]) => element.classList.toggle("active", name === viewName));
    document.querySelectorAll(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === viewName));
    const isNew = viewName === "nova";
    $("new-actions").classList.toggle("hidden", !isNew);
    $("page-title").textContent = isNew ? "Nova pesquisa" : "Histórico de pesquisas";
    $("page-eyebrow").textContent = isNew ? "NOVA EXECUÇÃO" : "ARQUIVOS E RESULTADOS";
    if (viewName === "historico") refreshHistory();
  }

  function populate(data) {
    const config = data.config || {};
    const filtros = config.filtros || {};
    const enrich = config.enriquecimento || {};
    const output = config.saida || {};
    const exec = config.execucao || {};
    $("query").value = config.query || "";
    fillChecks("bases", config.bases_ativas || []);
    $("max").value = config.max_artigos_por_base ?? 100;
    $("campo").value = filtros.campo_busca || "tudo";
    $("ano_de").value = filtros.ano_de ?? "";
    $("ano_ate").value = filtros.ano_ate ?? "";
    $("idiomas").value = (filtros.idiomas || []).join(", ");
    fillChecks("tipos", filtros.tipos || []);
    $("somente_oa").checked = Boolean(filtros.somente_oa);
    $("referencias").checked = enrich.referencias ?? true;
    $("resolver_ids").checked = enrich.resolver_ids_para_doi ?? true;
    $("texto_completo").checked = enrich.texto_completo ?? true;
    $("separador").value = output.separador_lista || " | ";
    $("raw_json").checked = output.raw_json ?? true;
    $("timeout").value = exec.timeout_s ?? 30;
    $("paginas").value = exec.max_paginas_extras_filtro_local ?? 10;
    $("log_nivel").value = exec.log_nivel || "INFO";
    $("cache").checked = exec.cache_http ?? true;
    $("limites").value = JSON.stringify(config.limites || {}, null, 2);
    $("criteria").value = data.criteria || "";
    preferredModel = data.model || "qwen3.5:0.8b";
  }

  function makePayload() {
    let limits;
    try { limits = JSON.parse($("limites").value || "{}"); }
    catch { throw new Error("Os limites por base precisam estar em JSON válido."); }
    const languages = $("idiomas").value.split(",").map((value) => value.trim()).filter(Boolean);
    return {
      config: {
        query: $("query").value.trim(),
        bases_ativas: checkedValues("bases"),
        max_artigos_por_base: Number.parseInt($("max").value, 10),
        filtros: {
          ano_de: optionalInteger("ano_de"), ano_ate: optionalInteger("ano_ate"),
          tipos: checkedValues("tipos"), idiomas: languages,
          somente_oa: $("somente_oa").checked, campo_busca: $("campo").value,
        },
        enriquecimento: {
          referencias: $("referencias").checked,
          resolver_ids_para_doi: $("resolver_ids").checked,
          texto_completo: $("texto_completo").checked,
        },
        saida: { diretorio: "saida", raw_json: $("raw_json").checked, separador_lista: $("separador").value },
        execucao: {
          max_paginas_extras_filtro_local: Number.parseInt($("paginas").value, 10),
          cache_http: $("cache").checked,
          timeout_s: Number($("timeout").value),
          log_nivel: $("log_nivel").value,
        },
        limites: limits,
      },
      criteria: $("criteria").value,
      model: $("model").value.trim(),
    };
  }

  function saveLocally() {
    const payload = makePayload();
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
    return payload;
  }

  async function fetchJson(url, options = {}) {
    const response = await fetch(url, options);
    const result = await response.json();
    if (response.status === 401 && result.login) {
      window.location.replace(result.login);
      throw new Error("Sua sessão expirou. Entre novamente.");
    }
    if (!response.ok) throw new Error(result.detail || "Não foi possível concluir a operação.");
    return result;
  }

  async function refreshModels() {
    if (modelRefreshInProgress) return;
    modelRefreshInProgress = true;
    const select = $("model");
    const button = $("refresh-models");
    button.disabled = true;
    try {
      const result = await fetchJson("/api/models", { cache: "no-store" });
      select.replaceChildren();
      const models = result.models || [];
      if (!models.length) {
        const placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = "Nenhum modelo disponível";
        select.append(placeholder);
        select.disabled = true;
        $("models-hint").textContent = result.error || "Baixe um modelo no servidor Ollama e atualize a lista.";
        return;
      }

      for (const model of models) {
        const option = document.createElement("option");
        option.value = model.name;
        const info = [model.parameter_size, model.family].filter(Boolean).join(" · ");
        option.textContent = info ? `${model.name} — ${info}` : model.name;
        select.append(option);
      }
      const names = models.map((model) => model.name);
      const selected = names.includes(preferredModel)
        ? preferredModel
        : names.includes("qwen3.5:0.8b") ? "qwen3.5:0.8b" : names[0];
      select.value = selected;
      select.disabled = false;
      preferredModel = selected;
      $("models-hint").textContent = `${models.length} modelo(s) instalado(s). O selecionado será carregado ao iniciar a pesquisa.`;
    } catch (error) {
      $("models-hint").textContent = error.message;
    } finally {
      button.disabled = false;
      modelRefreshInProgress = false;
    }
  }

  function fileIcon(filename) {
    const ext = filename.split(".").pop().toLowerCase();
    return ({ csv: "CSV", yaml: "YML", txt: "TXT", md: "MD", json: "{}", log: "LOG" })[ext] || "FILE";
  }

  function renderHistory(items) {
    const root = $("history-list");
    root.replaceChildren();
    $("history-count").textContent = String(items.length);
    $("history-empty").classList.toggle("hidden", items.length > 0);
    if (!items.length) return;

    const fragment = document.createDocumentFragment();
    for (const research of items) {
      const card = document.createElement("article");
      card.className = "history-card";
      const header = document.createElement("div");
      header.className = "history-head";
      const name = document.createElement("div");
      name.className = "history-name";
      const folderIcon = document.createElement("span");
      folderIcon.className = "folder-icon";
      folderIcon.textContent = "▰";
      const titleWrap = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = research.id;
      const subtitle = document.createElement("small");
      subtitle.textContent = `${research.files.length} arquivos disponíveis`;
      titleWrap.append(title, subtitle);
      name.append(folderIcon, titleWrap);
      const count = document.createElement("span");
      count.className = "file-count";
      count.textContent = `${research.files.length} arquivos`;
      header.append(name, count);

      const fileGrid = document.createElement("div");
      fileGrid.className = "file-grid";
      for (const filename of research.files) {
        const link = document.createElement("a");
        link.className = "file-link";
        link.href = `/api/history/${encodeURIComponent(research.id)}/${encodeURIComponent(filename)}`;
        link.download = filename;
        const icon = document.createElement("span");
        icon.className = "file-type";
        icon.textContent = fileIcon(filename);
        const label = document.createElement("span");
        label.textContent = filename;
        link.append(icon, label);
        fileGrid.append(link);
      }
      card.append(header, fileGrid);
      fragment.append(card);
    }
    root.append(fragment);
  }

  async function refreshHistory() {
    const button = $("refresh-history");
    if (button) button.disabled = true;
    try { renderHistory(await fetchJson("/api/history", { cache: "no-store" })); }
    catch (error) { notify(error.message, true); }
    finally { if (button) button.disabled = false; }
  }

  function updateOllama(status) {
    const dot = $("ollama-dot");
    const label = $("ollama-label");
    const secondary = $("state-detail");
    dot.className = "ollama-dot";
    if (status.ollama_status === "pronto") {
      dot.classList.add("ready");
      label.textContent = `Modelo pronto · ${status.ollama_model}`;
      secondary.textContent = `Ollama pronto · ${status.ollama_model}`;
    } else if (status.ollama_status === "erro") {
      dot.classList.add("error");
      label.textContent = "Ollama indisponível";
      secondary.textContent = status.ollama_error || "Verifique a instalação do Ollama.";
    } else {
      dot.classList.add("loading");
      label.textContent = "Iniciando Ollama…";
      secondary.textContent = "Iniciando serviço e carregando modelo…";
    }
    const accelerator = status.ollama_accelerator || "não informado";
    $("gpu-status").textContent = accelerator;
    const acceleratorDot = document.querySelector(".accelerator-dot");
    acceleratorDot.classList.toggle("gpu", accelerator.includes("GPU") && !accelerator.startsWith("0%"));
    acceleratorDot.classList.toggle("cpu", accelerator.startsWith("0% GPU"));
    if ((status.ollama_status === "pronto" || status.ollama_status === "erro") && !selectModelsRequested) {
      selectModelsRequested = true;
      refreshModels();
    }
  }

  function updateStatus(status) {
    updateOllama(status);
    const badge = $("state-dot");
    badge.className = "state-dot";
    if (status.running) badge.classList.add("loading");
    else if (status.stage === "concluído") badge.classList.add("ready");
    $("stage").textContent = status.running ? status.stage : status.stage === "falhou" ? "Execução com erro" : status.stage === "concluído" ? "Pesquisa concluída" : "Pronto para configurar";
    $("run").disabled = status.running;
    const progressCard = $("progress-card");
    const showProgress = status.running || status.stage === "falhou" || status.stage === "concluído";
    progressCard.classList.toggle("hidden", !showProgress);
    $("progress-stage").textContent = status.stage;
    $("progress-number").textContent = status.total ? `${status.processed} / ${status.total}` : "";
    const track = $("progress-fill").parentElement;
    track.classList.toggle("indeterminate", status.running && !status.total);
    $("progress-fill").style.width = status.total ? `${Math.round(status.processed / status.total * 100)}%` : status.running ? "28%" : "0%";
    $("progress-detail").textContent = status.total
      ? `Triagem de artigos${status.current ? ` · ${status.current}` : ""}`
      : status.running ? status.stage === "buscando artigos" ? "Consultando as bases acadêmicas em paralelo…" : status.stage === "carregando modelo" ? "O serviço Ollama está sendo preparado…" : "Preparando execução…"
        : status.error || status.output || status.ollama_error || "";

    if (status.stage !== lastRunStage && status.stage === "concluído") {
      $("result-title").textContent = "Ranking gerado com sucesso";
      $("result-message").textContent = status.output ? `Arquivo: ${status.output}` : "Os arquivos desta execução estão no histórico.";
      $("result-banner").classList.remove("hidden");
      notify("Pesquisa concluída; arquivos disponíveis no histórico.");
      refreshHistory();
    } else if (status.stage !== lastRunStage && status.stage === "falhou") {
      notify(status.error || "A execução falhou. Consulte os detalhes do status.", true);
    }
    lastRunStage = status.stage;
  }

  document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
  $("save").addEventListener("click", () => {
    try { saveLocally(); notify("Configuração salva neste navegador."); }
    catch (error) { notify(error.message, true); }
  });
  $("run").addEventListener("click", async () => {
    const button = $("run");
    button.disabled = true;
    try {
      const payload = saveLocally();
      await fetchJson("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      $("result-banner").classList.add("hidden");
      notify("Pesquisa iniciada.");
    } catch (error) {
      button.disabled = false;
      notify(error.message, true);
    }
  });
  $("refresh-history").addEventListener("click", refreshHistory);
  $("refresh-models").addEventListener("click", refreshModels);
  $("model").addEventListener("change", () => { preferredModel = $("model").value; });
  $("logout").addEventListener("click", async () => {
    try {
      await fetchJson("/api/auth/logout", { method: "POST", credentials: "same-origin" });
      localStorage.removeItem(STORAGE_KEY);
      window.location.replace("/login");
    } catch (error) {
      notify(error.message, true);
    }
  });
  $("new-from-empty").addEventListener("click", () => setView("nova"));
  $("open-history").addEventListener("click", () => setView("historico"));

  fetchJson("/api/config")
    .then((defaults) => {
      try {
        const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
        if (saved?.model === "qwen2.5:7b") saved.model = "qwen3.5:0.8b";
        populate(saved || defaults);
      }
      catch { populate(defaults); }
    })
    .catch((error) => notify(`Não foi possível iniciar a interface: ${error.message}`, true));

  async function poll() {
    try { updateStatus(await fetchJson("/api/status", { cache: "no-store" })); }
    catch { /* server may be restarting */ }
  }
  poll();
  window.setInterval(poll, 1200);
})();
