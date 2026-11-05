(() => {
  const $ = (id) => document.getElementById(id);
  const STORAGE_KEY = "coletor-artigos-form";
  const views = {
    nova: $("view-nova"),
    historico: $("view-historico"),
  };
  const BASE_NAMES = {
    openalex: "OpenAlex",
    semantic_scholar: "Semantic Scholar",
    crossref: "Crossref",
    arxiv: "arXiv",
    pubmed: "PubMed",
    europepmc: "Europe PMC",
    core: "CORE",
    doaj: "DOAJ",
    scielo: "SciELO",
  };
  const PIE_COLORS = [
    "#4168ed",
    "#18a383",
    "#8064e8",
    "#e6992e",
    "#e05c6c",
    "#2898bd",
    "#6c8893",
    "#9c5de0",
  ];
  const SVG_NS = "http://www.w3.org/2000/svg";

  let lastRunStage = "ocioso";
  let toastTimer;
  let preferredModel = "qwen3.5:0.8b";
  let modelRefreshInProgress = false;
  let selectModelsRequested = false;
  let defaultConfig = {};
  let activeResearchId = null;
  let currentResearchData = null;
  let historyItems = [];

  const checkedValues = (id) => [...document.querySelectorAll(`#${id} input[type=checkbox]:checked`)].map((item) => item.value);
  const fillChecks = (id, values = []) => document.querySelectorAll(`#${id} input[type=checkbox]`).forEach((item) => { item.checked = values.includes(item.value); });

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

  function cleanKeywords(raw, fallbackId = "") {
    let trimmed = String(raw || "").trim();
    if (trimmed.length >= 2 && trimmed.startsWith("'") && trimmed.endsWith("'")) {
      trimmed = trimmed.slice(1, -1).trim();
    }
    if (trimmed) return trimmed;
    const parts = String(fallbackId || "").split("_", 3);
    return parts.length === 3 ? parts[2].replace(/-/g, " ") : String(fallbackId || "Pesquisa");
  }

  function formatTimestampId(researchId) {
    const match = /^(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})(\d{2})/.exec(String(researchId || ""));
    if (!match) return researchId;
    return `${match[3]}/${match[2]}/${match[1]} · ${match[4]}:${match[5]}`;
  }

  function highlightActiveHistoryItem() {
    document.querySelectorAll(".chat-history-item").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.id === activeResearchId);
    });
  }

  function setView(viewName, options = {}) {
    Object.entries(views).forEach(([name, element]) => {
      if (element) element.classList.toggle("active", name === viewName);
    });
    document.querySelectorAll(".nav-item").forEach((button) => {
      button.classList.toggle("active", button.dataset.view === viewName);
    });
    const isNew = viewName === "nova";
    $("new-actions").classList.toggle("hidden", !isNew);
    if (isNew) {
      activeResearchId = null;
      $("page-eyebrow").textContent = "NOVA EXECUÇÃO";
      $("page-title").textContent = "Nova Pesquisa";
    } else {
      const kw = options.keywords || "Pesquisa";
      $("page-eyebrow").textContent = `ARQUIVOS E RESULTADOS`;
      $("page-title").textContent = kw;
    }
    highlightActiveHistoryItem();
  }

  const clampInt = (val, min, max, fallback) => {
    const n = Number.parseInt(val, 10);
    return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : fallback;
  };

  function renderWeights(aderencia, ano, citacoes) {
    $("peso_aderencia").value = aderencia;
    $("peso_aderencia_num").value = aderencia;
    $("peso_ano").value = ano;
    $("peso_ano_num").value = ano;
    $("peso_citacoes").value = citacoes;
    $("peso_citacoes_num").value = citacoes;
  }

  function rebalanceWeights(changed, rawValue) {
    let a = clampInt($("peso_aderencia").value, 50, 100, 70);
    let r = clampInt($("peso_ano").value, 0, 50, 15);
    let c = clampInt($("peso_citacoes").value, 0, 50, 15);
    if (changed === "aderencia") {
      a = clampInt(rawValue, 50, 100, a);
      const rem = 100 - a;
      const sumRC = r + c;
      r = sumRC > 0 ? Math.round((rem * r) / sumRC) : Math.round(rem / 2);
      c = rem - r;
    } else if (changed === "ano") {
      r = clampInt(rawValue, 0, 50, r);
      c = Math.min(100 - a - r, c);
      if (c < 0) c = 0;
      a = 100 - r - c;
    } else if (changed === "citacoes") {
      c = clampInt(rawValue, 0, 50, c);
      r = Math.min(100 - a - c, r);
      if (r < 0) r = 0;
      a = 100 - r - c;
    }
    renderWeights(a, r, c);
  }

  function populate(data) {
    const config = data.config || {};
    $("query").value = config.query || "";
    fillChecks("bases", config.bases_ativas || []);
    $("max").value = config.max_artigos_por_base ?? 100;
    $("criteria").value = data.criteria || "";
    preferredModel = data.model || "qwen3.5:0.8b";
    const w = data.weights || {};
    const toPct = (v, fb) => {
      const n = Number(v);
      if (!Number.isFinite(n)) return fb;
      return Math.round(n <= 1 && (w.aderencia ?? 70) <= 1 ? n * 100 : n);
    };
    const a = clampInt(toPct(w.aderencia, 70), 50, 100, 70);
    const r = clampInt(toPct(w.ano, 15), 0, 100 - a, 15);
    const c = 100 - a - r;
    renderWeights(a, r, c);
  }

  function makePayload() {
    // Filtros, enriquecimento, saída, execução e limites não são editáveis na interface:
    // seguem sempre os valores padrão do servidor (/api/config).
    const hidden = structuredClone(defaultConfig);
    const aderencia = clampInt($("peso_aderencia").value, 50, 100, 70);
    const ano = clampInt($("peso_ano").value, 0, 100 - aderencia, 15);
    const citacoes = 100 - aderencia - ano;
    return {
      config: {
        ...hidden,
        query: $("query").value.trim(),
        bases_ativas: checkedValues("bases"),
        max_artigos_por_base: Number.parseInt($("max").value, 10),
      },
      criteria: $("criteria").value,
      model: $("model").value.trim(),
      weights: {
        aderencia: Number((aderencia / 100).toFixed(4)),
        ano: Number((ano / 100).toFixed(4)),
        citacoes: Number((citacoes / 100).toFixed(4)),
      },
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

  function renderFileLinks(container, researchId, files) {
    container.replaceChildren();
    for (const filename of files || []) {
      const link = document.createElement("a");
      link.className = "file-link";
      link.href = `/api/history/${encodeURIComponent(researchId)}/${encodeURIComponent(filename)}`;
      link.download = filename;
      const icon = document.createElement("span");
      icon.className = "file-type";
      icon.textContent = fileIcon(filename);
      const label = document.createElement("span");
      label.textContent = filename;
      link.append(icon, label);
      container.append(link);
    }
  }

  function scoreBadgeColors(score) {
    if (score === null || score === undefined || !Number.isFinite(Number(score))) {
      return { bg: "#94a3b8", border: "#7e8ea4", fg: "#ffffff" };
    }
    const s = Math.max(0, Math.min(1, Number(score)));
    // High-sensitivity multi-stop scale across every 0.1 step (1.0 -> 0.9 -> 0.8 -> 0.7 -> ... -> 0.0)
    const stops = [
      [0.0, 355, 78, 36], // 0.0: deep crimson
      [0.2, 4, 78, 43], // 0.2: red
      [0.4, 18, 82, 45], // 0.4: red-orange
      [0.5, 28, 86, 45], // 0.5: orange
      [0.6, 38, 88, 44], // 0.6: amber
      [0.7, 48, 88, 42], // 0.7: golden yellow
      [0.8, 72, 76, 39], // 0.8: yellow-lime
      [0.9, 108, 68, 38], // 0.9: fresh green
      [1.0, 152, 82, 32], // 1.0: deep emerald
    ];
    let lower = stops[0];
    let upper = stops[stops.length - 1];
    for (let i = 0; i < stops.length - 1; i += 1) {
      if (s >= stops[i][0] && s <= stops[i + 1][0]) {
        lower = stops[i];
        upper = stops[i + 1];
        break;
      }
    }
    const span = upper[0] - lower[0];
    const t = span > 0 ? (s - lower[0]) / span : 0;
    const hue = Math.round(lower[1] + (upper[1] - lower[1]) * t);
    const sat = Math.round(lower[2] + (upper[2] - lower[2]) * t);
    const light = Math.round(lower[3] + (upper[3] - lower[3]) * t);
    return {
      bg: `hsl(${hue} ${sat}% ${light}%)`,
      border: `hsl(${hue} ${sat}% ${Math.max(18, light - 7)}%)`,
      fg: "#ffffff",
    };
  }

  function renderPieChart(byBase, totalArticles, consolidatedArticles) {
    const svg = $("pie-svg");
    const legend = $("pie-legend");
    svg.replaceChildren();
    legend.replaceChildren();

    const entries = (byBase || []).filter((item) => Number(item.count) > 0);
    const total = entries.reduce((acc, item) => acc + Number(item.count), 0) || Number(totalArticles) || 0;
    $("pie-total").textContent = String(total);
    $("pie-subtitle").textContent = consolidatedArticles
      ? `${total} coletados nas bases · ${consolidatedArticles} únicos no consolidado.csv`
      : "Distribuição entre as bases acadêmicas consultadas.";

    const cx = 100;
    const cy = 100;
    const r = 68;
    const circumference = 2 * Math.PI * r;

    const bgCircle = document.createElementNS(SVG_NS, "circle");
    bgCircle.setAttribute("cx", String(cx));
    bgCircle.setAttribute("cy", String(cy));
    bgCircle.setAttribute("r", String(r));
    bgCircle.setAttribute("fill", "none");
    bgCircle.setAttribute("stroke", "#edf1f7");
    bgCircle.setAttribute("stroke-width", "32");
    svg.append(bgCircle);

    let cumulative = 0;
    entries.forEach((item, index) => {
      const count = Number(item.count);
      const fraction = total > 0 ? count / total : 0;
      const arcLength = fraction * circumference;
      const color = PIE_COLORS[index % PIE_COLORS.length];

      const slice = document.createElementNS(SVG_NS, "circle");
      slice.setAttribute("cx", String(cx));
      slice.setAttribute("cy", String(cy));
      slice.setAttribute("r", String(r));
      slice.setAttribute("fill", "none");
      slice.setAttribute("stroke", color);
      slice.setAttribute("stroke-width", "32");
      slice.setAttribute("stroke-dasharray", `${arcLength} ${circumference}`);
      slice.setAttribute("stroke-dashoffset", String(-cumulative));
      slice.setAttribute("transform", `rotate(-90 ${cx} ${cy})`);
      const title = document.createElementNS(SVG_NS, "title");
      const labelName = BASE_NAMES[item.base] || item.base;
      const pct = total > 0 ? Math.round(fraction * 100) : 0;
      title.textContent = `${labelName}: ${count} artigo(s) (${pct}%)`;
      slice.append(title);
      svg.append(slice);
      cumulative += arcLength;
    });

    const allBases = (byBase && byBase.length) ? byBase : entries;
    if (!allBases.length) {
      const emptyLi = document.createElement("li");
      emptyLi.className = "pie-legend-empty";
      emptyLi.textContent = "Sem estatísticas de coleta para exibir.";
      legend.append(emptyLi);
      return;
    }

    let colorIndex = 0;
    for (const item of allBases) {
      const count = Number(item.count) || 0;
      const hasArticles = count > 0;
      const color = hasArticles ? PIE_COLORS[colorIndex++ % PIE_COLORS.length] : "#cbd5e1";
      const pct = total > 0 && hasArticles ? `${Math.round((count / total) * 100)}%` : "0%";
      const li = document.createElement("li");
      li.className = "pie-legend-item";
      const swatch = document.createElement("span");
      swatch.className = "pie-swatch";
      swatch.style.background = color;
      const name = document.createElement("span");
      name.className = "pie-legend-name";
      name.textContent = BASE_NAMES[item.base] || item.base;
      const meta = document.createElement("span");
      meta.className = "pie-legend-count";
      meta.textContent = `${count} (${pct})`;
      li.append(swatch, name, meta);
      legend.append(li);
    }
  }

  function createArticleRow(article) {
    const row = document.createElement("article");
    row.className = "article-row";

    // 1. llm_score
    const scoreCell = document.createElement("div");
    scoreCell.className = "article-score-cell";
    const badge = document.createElement("span");
    badge.className = "score-square";
    const hasScore = article.llm_score !== null && article.llm_score !== undefined && Number.isFinite(Number(article.llm_score));
    const colors = scoreBadgeColors(hasScore ? Number(article.llm_score) : null);
    badge.style.backgroundColor = colors.bg;
    badge.style.borderColor = colors.border;
    badge.style.color = colors.fg;
    badge.textContent = hasScore ? Number(article.llm_score).toFixed(3) : "—";
    scoreCell.append(badge);

    // 2. ano
    const yearCell = document.createElement("div");
    yearCell.className = "article-year";
    yearCell.textContent = article.ano || "—";

    // 3. bases
    const basesCell = document.createElement("div");
    basesCell.className = "article-bases";
    const basesList = String(article.bases || "")
      .split("|")
      .map((b) => b.trim())
      .filter(Boolean);
    if (basesList.length) {
      for (const b of basesList) {
        const pill = document.createElement("span");
        pill.className = "base-pill";
        pill.textContent = BASE_NAMES[b] || b;
        basesCell.append(pill);
      }
    } else {
      basesCell.textContent = "—";
    }

    // 4. info_artigos (titulo, autores, resumo) — clicável para expandir o resumo completo
    const infoCell = document.createElement("div");
    infoCell.className = "article-info";
    infoCell.setAttribute("role", "button");
    infoCell.tabIndex = 0;
    infoCell.setAttribute("aria-expanded", "false");
    infoCell.title = "Clique para expandir ou recolher o resumo completo";
    const toggleExpand = () => {
      const expanded = row.classList.toggle("expanded");
      infoCell.setAttribute("aria-expanded", String(expanded));
    };
    infoCell.addEventListener("click", toggleExpand);
    infoCell.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        toggleExpand();
      }
    });
    const title = document.createElement("strong");
    title.className = "article-title";
    title.textContent = article.titulo || "Sem título";
    const authors = document.createElement("div");
    authors.className = "article-authors";
    const cleanAuthors = String(article.autores || "").split("|").map((a) => a.trim()).filter(Boolean).join(", ");
    authors.textContent = cleanAuthors || "Autores não informados";
    const abstract = document.createElement("p");
    abstract.className = "article-abstract";
    abstract.textContent = article.resumo || "Resumo não disponível.";
    infoCell.append(title, authors, abstract);

    // 5. llm_justification — também clicável para expandir
    const justCell = document.createElement("div");
    justCell.className = "article-justification";
    justCell.title = "Clique para expandir ou recolher a justificativa completa";
    const justText = document.createElement("p");
    justText.className = "article-justification-text";
    justText.textContent = article.llm_justification || "—";
    justCell.append(justText);
    justCell.addEventListener("click", toggleExpand);

    // 6. doi
    const doiCell = document.createElement("div");
    doiCell.className = "article-doi";
    const rawDoi = String(article.doi || "").trim();
    if (rawDoi) {
      const cleanDoi = rawDoi.replace(/^https?:\/\/(dx\.)?doi\.org\//i, "");
      const link = document.createElement("a");
      link.href = `https://doi.org/${encodeURI(cleanDoi)}`;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = cleanDoi;
      link.title = `Abrir https://doi.org/${cleanDoi}`;
      doiCell.append(link);
    } else {
      doiCell.textContent = "—";
    }

    row.append(scoreCell, yearCell, basesCell, infoCell, justCell, doiCell);
    return row;
  }

  function syncArticlesViewportHeight() {
    const body = $("articles-body");
    if (!body) return;
    const rows = [...body.querySelectorAll(".article-row")];
    if (rows.length <= 5) {
      body.style.removeProperty("max-height");
      return;
    }
    const visible = rows.slice(0, 5);
    const gap = 8;
    const total = visible.reduce((sum, r) => sum + r.offsetHeight, 0) + gap * (visible.length - 1);
    if (total > 0) {
      body.style.maxHeight = `${total}px`;
    }
  }

  function renderTopArticles() {
    if (!currentResearchData) return;
    const body = $("articles-body");
    const articles = (currentResearchData.articles || []).slice(0, 25);
    body.replaceChildren();
    body.scrollTop = 0;

    if (!articles.length) {
      body.style.removeProperty("max-height");
      const empty = document.createElement("div");
      empty.className = "articles-empty";
      empty.textContent = "Nenhum artigo ranqueado encontrado nesta pesquisa.";
      body.append(empty);
      return;
    }

    const fragment = document.createDocumentFragment();
    for (const article of articles) {
      fragment.append(createArticleRow(article));
    }
    body.append(fragment);
    window.requestAnimationFrame(() => syncArticlesViewportHeight());
  }

  async function openResearch(researchId) {
    try {
      const detail = await fetchJson(`/api/history/${encodeURIComponent(researchId)}`, { cache: "no-store" });
      currentResearchData = detail;
      activeResearchId = detail.id;
      const keywords = cleanKeywords(detail.query, detail.id);
      setView("historico", { keywords });
      activeResearchId = detail.id;
      highlightActiveHistoryItem();
      $("files-subtitle").textContent = `Pasta ./saida/${detail.id} (${(detail.files || []).length} arquivos)`;
      renderPieChart(detail.by_base || [], detail.total_articles, detail.consolidated_articles);
      renderFileLinks($("research-files"), detail.id, detail.files || []);
      renderTopArticles();
    } catch (error) {
      notify(error.message, true);
    }
  }

  function renderHistory(items) {
    historyItems = items || [];
    const root = $("history-list");
    root.replaceChildren();
    $("history-count").textContent = String(historyItems.length);
    $("history-empty").classList.toggle("hidden", historyItems.length > 0);
    if (!historyItems.length) return;

    const fragment = document.createDocumentFragment();
    for (const research of historyItems) {
      const keywords = cleanKeywords(research.query, research.id);
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chat-history-item";
      btn.dataset.id = research.id;
      btn.classList.toggle("active", research.id === activeResearchId);
      btn.title = `${keywords}\n(${research.id})`;
      const textWrap = document.createElement("span");
      textWrap.className = "chat-history-text";
      const title = document.createElement("strong");
      title.textContent = keywords;
      const sub = document.createElement("small");
      sub.textContent = formatTimestampId(research.id);
      textWrap.append(title, sub);
      btn.append(textWrap);
      btn.addEventListener("click", () => openResearch(research.id));
      fragment.append(btn);
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
      secondary.textContent = `Ollama Pronto · ${status.ollama_model}`;
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
    const fill = $("progress-fill");
    const track = fill.parentElement;
    const isIndeterminate = Boolean(status.running && !status.total);
    track.classList.toggle("indeterminate", isIndeterminate);
    if (isIndeterminate) {
      fill.style.removeProperty("width");
    } else if (status.total) {
      fill.style.width = `${Math.round((status.processed / status.total) * 100)}%`;
    } else {
      fill.style.width = status.stage === "concluído" ? "100%" : "0%";
    }
    $("progress-detail").textContent = status.total
      ? `Triagem de artigos${status.current ? ` · ${status.current}` : ""}`
      : status.running ? status.stage === "Buscando Artigos" ? "Consultando as bases acadêmicas em paralelo …" : status.stage === "carregando modelo" ? "O serviço Ollama está sendo preparado…" : "Preparando execução…"
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
  $("open-history").addEventListener("click", async () => {
    if (!historyItems.length) await refreshHistory();
    if (historyItems.length) openResearch(historyItems[0].id);
  });
  $("peso_aderencia").addEventListener("input", (e) => rebalanceWeights("aderencia", e.target.value));
  $("peso_aderencia_num").addEventListener("change", (e) => rebalanceWeights("aderencia", e.target.value));
  $("peso_ano").addEventListener("input", (e) => rebalanceWeights("ano", e.target.value));
  $("peso_ano_num").addEventListener("change", (e) => rebalanceWeights("ano", e.target.value));
  $("peso_citacoes").addEventListener("input", (e) => rebalanceWeights("citacoes", e.target.value));
  $("peso_citacoes_num").addEventListener("change", (e) => rebalanceWeights("citacoes", e.target.value));


  fetchJson("/api/config")
    .then((defaults) => {
      defaultConfig = defaults.config || {};
      try {
        const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
        if (saved?.model === "qwen2.5:7b") saved.model = "qwen3.5:0.8b";
        populate(saved || defaults);
      }
      catch { populate(defaults); }
    })
    .catch((error) => notify(`Não foi possível iniciar a interface: ${error.message}`, true));

  refreshHistory();

  async function poll() {
    try { updateStatus(await fetchJson("/api/status", { cache: "no-store" })); }
    catch { /* server may be restarting */ }
  }
  poll();
  window.setInterval(poll, 1200);
})();
