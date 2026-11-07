(() => {
  const $ = (id) => document.getElementById(id);
  const STORAGE_KEY = "coletor-artigos-form";
  const DEFAULTS_VERSION_KEY = "coletor-artigos-padroes";
  const TEMPERATURE_MIGRATION_KEY = "coletor-temperatura-0.1";
  const DEFAULT_TEMPERATURE = 0.1;
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
  let modelListError = "";
  let lastOllamaStatus = {};

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
    $("history-actions").classList.toggle("hidden", isNew);
    if (isNew) {
      activeResearchId = null;
      $("page-title").textContent = "Nova Pesquisa";
    } else {
      $("page-title").textContent = options.keywords || "Pesquisa";
    }
    highlightActiveHistoryItem();
  }

  const clampInt = (val, min, max, fallback) => {
    const n = Number.parseInt(val, 10);
    return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : fallback;
  };

  // Pesos do score (em %): aderência entre 50 e 100; demais entre 0 e 50; total sempre 100.
  const WEIGHT_KEYS = ["aderencia", "ano", "citacoes", "tipo"];
  const OTHER_KEYS = WEIGHT_KEYS.slice(1);
  const DEFAULT_WEIGHTS = { aderencia: 70, ano: 10, citacoes: 10, tipo: 10 };
  const DEFAULT_TYPE_VALUES = { artigo: 100, revisao: 100, conferencia: 80, livro_capitulo: 60, preprint: 50, outros: 40 };

  function renderWeights(weights) {
    for (const key of WEIGHT_KEYS) {
      $(`peso_${key}`).value = weights[key];
      $(`peso_${key}_num`).value = weights[key];
    }
  }

  function currentWeights() {
    const w = { aderencia: clampInt($("peso_aderencia").value, 50, 100, DEFAULT_WEIGHTS.aderencia) };
    for (const key of OTHER_KEYS) w[key] = clampInt($(`peso_${key}`).value, 0, 50, DEFAULT_WEIGHTS[key]);
    return w;
  }

  function rebalanceWeights(changed, rawValue) {
    const w = currentWeights();
    if (changed === "aderencia") {
      // A sobra é dividida entre os demais pesos, na proporção atual deles.
      w.aderencia = clampInt(rawValue, 50, 100, w.aderencia);
      const rem = 100 - w.aderencia;
      const sum = OTHER_KEYS.reduce((acc, k) => acc + w[k], 0);
      let used = 0;
      OTHER_KEYS.forEach((k, i) => {
        if (i === OTHER_KEYS.length - 1) { w[k] = rem - used; return; }
        w[k] = sum > 0 ? Math.round((rem * w[k]) / sum) : Math.floor(rem / OTHER_KEYS.length);
        used += w[k];
      });
    } else {
      // Mudar um peso secundário ajusta a aderência; se ela ficaria abaixo de 50%, o valor é limitado.
      const others = OTHER_KEYS.filter((k) => k !== changed).reduce((acc, k) => acc + w[k], 0);
      w[changed] = Math.min(clampInt(rawValue, 0, 50, w[changed]), 50 - others);
      if (w[changed] < 0) w[changed] = 0;
      w.aderencia = 100 - others - w[changed];
    }
    renderWeights(w);
  }

  function weightsFromData(raw) {
    const w = raw || {};
    if (w.tipo === undefined || w.aderencia === undefined) return { ...DEFAULT_WEIGHTS };
    const fraction = WEIGHT_KEYS.every((k) => Number(w[k]) <= 1);
    const pct = (k) => {
      const n = Number(w[k]);
      return Number.isFinite(n) ? Math.round(fraction ? n * 100 : n) : DEFAULT_WEIGHTS[k];
    };
    const result = { aderencia: clampInt(pct("aderencia"), 50, 100, DEFAULT_WEIGHTS.aderencia) };
    for (const k of OTHER_KEYS) result[k] = clampInt(pct(k), 0, 50, DEFAULT_WEIGHTS[k]);
    const total = WEIGHT_KEYS.reduce((acc, k) => acc + result[k], 0);
    return total === 100 ? result : { ...DEFAULT_WEIGHTS };
  }

  function typeValueInputs() {
    return [...document.querySelectorAll("#type-values input[data-tipo]")];
  }

  function renderTypeValues(values) {
    const v = values || {};
    for (const input of typeValueInputs()) {
      const n = Number(v[input.dataset.tipo]);
      const fallback = DEFAULT_TYPE_VALUES[input.dataset.tipo];
      input.value = String(Number.isFinite(n) ? clampInt(Math.round(n <= 1 && v.artigo <= 1 ? n * 100 : n), 0, 100, fallback) : fallback);
    }
  }

  function currentTypeValues() {
    const values = {};
    for (const input of typeValueInputs()) {
      const n = clampInt(input.value, 0, 100, DEFAULT_TYPE_VALUES[input.dataset.tipo]);
      input.value = String(n);
      values[input.dataset.tipo] = n;
    }
    return values;
  }

  function renderTemperature(value) {
    const n = Number(value);
    const t = Number.isFinite(n) ? Math.min(1, Math.max(0, Math.round(n * 100) / 100)) : DEFAULT_TEMPERATURE;
    $("temperatura").value = String(t);
    $("temperatura_num").value = String(t);
    return t;
  }

  function populate(data) {
    const config = data.config || {};
    $("query").value = config.query || "";
    fillChecks("bases", config.bases_ativas || []);
    $("max").value = config.max_artigos_por_base ?? 100;
    $("criteria").value = data.criteria || "";
    preferredModel = data.model || "qwen3.5:0.8b";
    renderWeights(weightsFromData(data.weights));
    renderTypeValues(data.type_values || DEFAULT_TYPE_VALUES);
    renderTemperature(data.temperature ?? DEFAULT_TEMPERATURE);
  }

  function makePayload() {
    // Filtros, enriquecimento, saída, execução e limites não são editáveis na interface:
    // seguem sempre os valores padrão do servidor (/api/config).
    const hidden = structuredClone(defaultConfig);
    const w = currentWeights();
    return {
      config: {
        ...hidden,
        query: $("query").value.trim(),
        bases_ativas: checkedValues("bases"),
        max_artigos_por_base: Number.parseInt($("max").value, 10),
      },
      criteria: $("criteria").value,
      model: $("model").value.trim(),
      weights: Object.fromEntries(WEIGHT_KEYS.map((key) => [key, Number((w[key] / 100).toFixed(4))])),
      type_values: Object.fromEntries(Object.entries(currentTypeValues()).map(([key, n]) => [key, Number((n / 100).toFixed(4))])),
      temperature: renderTemperature($("temperatura").value),
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
        modelListError = result.error || "Nenhum modelo instalado no Ollama.";
        renderModelStatus();
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
      modelListError = "";
      renderModelStatus();
    } catch (error) {
      modelListError = error.message;
      renderModelStatus();
    } finally {
      button.disabled = false;
      modelRefreshInProgress = false;
    }
  }

  function fileIcon(filename) {
    const ext = filename.split(".").pop().toLowerCase();
    return ({ csv: "CSV", yaml: "YML", txt: "TXT", md: "MD", json: "{}", log: "LOG" })[ext] || "FILE";
  }

  function syncThemeButton() {
    const dark = window.coletorTheme.current() === "dark";
    document.querySelector(".theme-toggle-icon").textContent = dark ? "☀" : "☾";
    document.querySelector(".theme-toggle-label").textContent = dark ? "Tema claro" : "Tema escuro";
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
    bgCircle.style.stroke = "var(--pie-track)";
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
      const color = hasArticles ? PIE_COLORS[colorIndex++ % PIE_COLORS.length] : "var(--pie-empty)";
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
    justText.textContent = article.llm_justification
      || (currentResearchData?.ranking === "ausente" ? "Sem triagem: o ranking não foi gerado nesta pesquisa." : "—");
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

  function formatDuration(seconds) {
    const n = Number(seconds);
    if (seconds === null || seconds === undefined || !Number.isFinite(n)) return "—";
    const total = Math.round(n);
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const sec = total % 60;
    if (h) return `${h}h ${String(m).padStart(2, "0")}min`;
    if (m) return `${m}min ${String(sec).padStart(2, "0")}s`;
    return `${sec}s`;
  }

  function renderTiming(timing) {
    const busca = timing.busca_s;
    const proc = timing.processamento_s;
    const known = (v) => v !== null && v !== undefined && Number.isFinite(Number(v));
    $("timing-busca").textContent = formatDuration(busca);
    $("timing-processamento").textContent = formatDuration(proc);
    $("timing-total").textContent = known(busca) || known(proc)
      ? formatDuration((known(busca) ? Number(busca) : 0) + (known(proc) ? Number(proc) : 0))
      : "—";
    $("timing-processamento").title = known(proc)
      ? ""
      : "Não registrado: triagem não concluída ou pesquisa anterior ao registro de tempos.";
  }

  // ---------- Grafo de artigos e referências (layout por forças, sem bibliotecas externas) ----------
  const GRAPH_W = 600;
  const GRAPH_H = 420;
  const graphState = { nodes: [], edges: [], view: { x: 0, y: 0, w: GRAPH_W, h: GRAPH_H }, requestId: 0 };

  async function loadGraph(researchId) {
    const requestId = ++graphState.requestId;
    $("graph-svg").replaceChildren();
    $("graph-empty").classList.add("hidden");
    $("graph-subtitle").textContent = "Montando o grafo…";
    try {
      const data = await fetchJson(`/api/history/${encodeURIComponent(researchId)}/graph`, { cache: "no-store" });
      if (requestId !== graphState.requestId) return;
      renderGraph(data);
    } catch (error) {
      if (requestId !== graphState.requestId) return;
      $("graph-subtitle").textContent = error.message;
    }
  }

  function layoutGraph(nodes, edges, width, height) {
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const links = edges.map((e) => [byId.get(e.source), byId.get(e.target)]).filter(([a, b]) => a && b);
    nodes.forEach((n, i) => {
      const angle = (i / Math.max(1, nodes.length)) * Math.PI * 2;
      const radius = n.type === "artigo" ? width * 0.18 : width * 0.36;
      n.x = width / 2 + Math.cos(angle) * radius + (Math.random() - 0.5) * 10;
      n.y = height / 2 + Math.sin(angle) * radius * 0.75 + (Math.random() - 0.5) * 10;
      n.vx = 0;
      n.vy = 0;
    });
    const k = Math.sqrt((width * height) / Math.max(1, nodes.length)) * 0.55;
    const steps = 320;
    for (let iter = 0; iter < steps; iter += 1) {
      const cooling = 1 - iter / steps;
      for (let i = 0; i < nodes.length; i += 1) {
        const a = nodes[i];
        for (let j = i + 1; j < nodes.length; j += 1) {
          const b = nodes[j];
          let dx = a.x - b.x;
          let dy = a.y - b.y;
          let d2 = dx * dx + dy * dy;
          if (d2 < 0.01) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; d2 = 0.25; }
          const force = ((k * k) / d2) * 0.02;
          a.vx += dx * force; a.vy += dy * force;
          b.vx -= dx * force; b.vy -= dy * force;
        }
      }
      for (const [a, b] of links) {
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
        const force = (d - k) * 0.04;
        const fx = (dx / d) * force;
        const fy = (dy / d) * force;
        a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
      }
      for (const n of nodes) {
        n.vx += (width / 2 - n.x) * 0.02;
        n.vy += (height / 2 - n.y) * 0.02;
        const speed = Math.sqrt(n.vx * n.vx + n.vy * n.vy);
        const limit = 18 * cooling + 0.5;
        if (speed > limit) { n.vx = (n.vx / speed) * limit; n.vy = (n.vy / speed) * limit; }
        n.x += n.vx;
        n.y += n.vy;
        n.vx *= 0.6;
        n.vy *= 0.6;
      }
    }
    return links;
  }

  function applyGraphView() {
    const v = graphState.view;
    $("graph-svg").setAttribute("viewBox", `${v.x} ${v.y} ${v.w} ${v.h}`);
  }

  function fitGraphView() {
    const { nodes } = graphState;
    if (!nodes.length) return;
    const xs = nodes.map((n) => n.x);
    const ys = nodes.map((n) => n.y);
    const pad = 24;
    const minX = Math.min(...xs) - pad;
    const maxX = Math.max(...xs) + pad;
    const minY = Math.min(...ys) - pad;
    const maxY = Math.max(...ys) + pad;
    const box = $("graph-svg").getBoundingClientRect();
    const ratio = box.width > 0 && box.height > 0 ? box.width / box.height : GRAPH_W / GRAPH_H;
    let w = maxX - minX;
    let h = maxY - minY;
    if (w / h > ratio) h = w / ratio; else w = h * ratio;
    graphState.view = { x: (minX + maxX - w) / 2, y: (minY + maxY - h) / 2, w, h };
    applyGraphView();
  }

  function zoomGraph(factor, cx, cy) {
    const v = graphState.view;
    const px = cx ?? v.x + v.w / 2;
    const py = cy ?? v.y + v.h / 2;
    const w = Math.min(4000, Math.max(80, v.w * factor));
    const h = w * (v.h / v.w);
    graphState.view = { x: px - ((px - v.x) * w) / v.w, y: py - ((py - v.y) * h) / v.h, w, h };
    applyGraphView();
  }

  function shortLabel(text, max = 70) {
    const t = String(text || "");
    return t.length > max ? `${t.slice(0, max - 1)}…` : t;
  }

  function renderGraph(data) {
    const svg = $("graph-svg");
    svg.replaceChildren();
    const nodes = (data.nodes || []).map((n) => ({ ...n }));
    const edges = data.edges || [];
    graphState.nodes = nodes;
    graphState.edges = edges;
    const nArtigos = nodes.filter((n) => n.type === "artigo").length;
    const nRefs = nodes.length - nArtigos;
    if (!nodes.length) {
      graphState.view = { x: 0, y: 0, w: GRAPH_W, h: GRAPH_H };
      applyGraphView();
      $("graph-empty").classList.remove("hidden");
      $("graph-subtitle").textContent = data.articles_with_references
        ? `${data.articles_with_references} artigo(s) com referências, mas nenhuma referência em comum.`
        : "Os artigos desta pesquisa não têm referências registradas.";
      return;
    }
    $("graph-subtitle").textContent =
      `${nArtigos} artigos mais bem ranqueados · ${nRefs} referências em comum · ${edges.length} ligações`;

    const links = layoutGraph(nodes, edges, GRAPH_W, GRAPH_H);
    const maxCit = Math.max(2, ...nodes.filter((n) => n.type === "referencia").map((n) => n.citations || 2));

    const edgeGroup = document.createElementNS(SVG_NS, "g");
    edgeGroup.setAttribute("class", "graph-edges");
    const linesByNode = new Map();
    for (const [a, b] of links) {
      const line = document.createElementNS(SVG_NS, "line");
      line.setAttribute("x1", a.x.toFixed(1));
      line.setAttribute("y1", a.y.toFixed(1));
      line.setAttribute("x2", b.x.toFixed(1));
      line.setAttribute("y2", b.y.toFixed(1));
      edgeGroup.append(line);
      for (const n of [a, b]) {
        if (!linesByNode.has(n.id)) linesByNode.set(n.id, []);
        linesByNode.get(n.id).push(line);
      }
    }
    svg.append(edgeGroup);

    const tooltip = $("graph-tooltip");
    const wrap = svg.parentElement;
    const nodeGroup = document.createElementNS(SVG_NS, "g");
    for (const n of nodes) {
      const circle = document.createElementNS(SVG_NS, "circle");
      circle.setAttribute("cx", n.x.toFixed(1));
      circle.setAttribute("cy", n.y.toFixed(1));
      if (n.type === "artigo") {
        n.baseR = 7;
        circle.setAttribute("class", "graph-node artigo");
        circle.style.fill = n.score == null ? "var(--blue)" : scoreBadgeColors(n.score).bg;
      } else {
        n.baseR = 3 + 6 * Math.sqrt(((n.citations || 2) - 1) / Math.max(1, maxCit - 1));
        circle.setAttribute("class", "graph-node referencia");
      }
      n.circle = circle;
      const show = (event) => {
        const lines = n.type === "artigo"
          ? [
            shortLabel(n.label, 110),
            [n.ano, n.score != null ? `score ${Number(n.score).toFixed(3)}` : "sem score"].filter(Boolean).join(" · "),
            n.doi,
          ]
          : [`Referência: ${n.doi}`, `Citada por ${n.citations} artigos da pesquisa`];
        tooltip.replaceChildren(...lines.filter(Boolean).map((text, i) => {
          const el = document.createElement(i === 0 ? "strong" : "span");
          el.textContent = text;
          return el;
        }));
        const box = wrap.getBoundingClientRect();
        tooltip.style.left = `${Math.min(box.width - 250, Math.max(4, event.clientX - box.left + 12))}px`;
        tooltip.style.top = `${Math.max(4, event.clientY - box.top + 12)}px`;
        tooltip.classList.remove("hidden");
        svg.classList.add("focusing");
        circle.classList.add("active");
        (linesByNode.get(n.id) || []).forEach((l) => l.classList.add("active"));
      };
      const hide = () => {
        tooltip.classList.add("hidden");
        svg.classList.remove("focusing");
        circle.classList.remove("active");
        (linesByNode.get(n.id) || []).forEach((l) => l.classList.remove("active"));
      };
      circle.addEventListener("mouseenter", show);
      circle.addEventListener("mousemove", show);
      circle.addEventListener("mouseleave", hide);
      if (n.doi) {
        circle.style.cursor = "pointer";
        circle.addEventListener("click", () => {
          const doi = n.doi.replace(/^https?:\/\/(dx\.)?doi\.org\//i, "");
          window.open(`https://doi.org/${encodeURI(doi)}`, "_blank", "noopener");
        });
      }
      nodeGroup.append(circle);
    }
    svg.append(nodeGroup);
    fitGraphView();
    // Tamanho dos nós e espessura das linhas acompanham o enquadramento inicial, para não ficarem minúsculos.
    const scale = Math.max(1, graphState.view.w / GRAPH_W);
    for (const n of nodes) n.circle.setAttribute("r", (n.baseR * scale).toFixed(1));
    svg.style.setProperty("--graph-scale", String(scale));
  }

  function svgPoint(event) {
    const box = $("graph-svg").getBoundingClientRect();
    const v = graphState.view;
    return {
      x: v.x + ((event.clientX - box.left) / box.width) * v.w,
      y: v.y + ((event.clientY - box.top) / box.height) * v.h,
    };
  }

  function setupGraphControls() {
    const svg = $("graph-svg");
    svg.addEventListener("wheel", (event) => {
      if (!graphState.nodes.length) return;
      event.preventDefault();
      const p = svgPoint(event);
      zoomGraph(event.deltaY > 0 ? 1.15 : 1 / 1.15, p.x, p.y);
    }, { passive: false });
    let drag = null;
    svg.addEventListener("pointerdown", (event) => {
      if (event.target.closest(".graph-node")) return;
      drag = { x: event.clientX, y: event.clientY, view: { ...graphState.view } };
      svg.setPointerCapture(event.pointerId);
      svg.classList.add("panning");
    });
    svg.addEventListener("pointermove", (event) => {
      if (!drag) return;
      const box = svg.getBoundingClientRect();
      const dx = ((event.clientX - drag.x) / box.width) * drag.view.w;
      const dy = ((event.clientY - drag.y) / box.height) * drag.view.h;
      graphState.view = { ...drag.view, x: drag.view.x - dx, y: drag.view.y - dy };
      applyGraphView();
    });
    const end = () => { drag = null; svg.classList.remove("panning"); };
    svg.addEventListener("pointerup", end);
    svg.addEventListener("pointercancel", end);
    $("graph-zoom-in").addEventListener("click", () => zoomGraph(1 / 1.25));
    $("graph-zoom-out").addEventListener("click", () => zoomGraph(1.25));
    $("graph-reset").addEventListener("click", () => { if (activeResearchId) loadGraph(activeResearchId); });
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
      const rankingNotes = {
        completo: "Ordenados do maior para o menor score. Clique em um artigo para expandir.",
        parcial: "Ranking incompleto: a triagem foi interrompida. Exibindo os artigos avaliados até a interrupção.",
        ausente: "Ranking não gerado (execução interrompida ou com erro). Exibindo o consolidado, sem score nem justificativa.",
      };
      const note = $("articles-subtitle");
      note.textContent = rankingNotes[detail.ranking] || rankingNotes.completo;
      note.classList.toggle("warning-text", detail.ranking !== "completo");
      renderTopArticles();
      renderTiming(detail.timing || {});
      loadGraph(detail.id);
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
  // Único indicador do modelo: o seletor mostra qual está escolhido; esta linha mostra o estado dele.
  function renderModelStatus() {
    const status = lastOllamaStatus;
    const dot = $("ollama-dot");
    const label = $("ollama-label");
    dot.className = "ollama-dot";
    const selected = $("model").value;
    const loaded = status.ollama_model;
    if (status.ollama_status === "erro") {
      dot.classList.add("error");
      label.textContent = status.ollama_error || "Ollama indisponível";
    } else if (modelListError) {
      dot.classList.add("error");
      label.textContent = modelListError;
    } else if (status.ollama_status === "pronto") {
      const accelerator = status.ollama_accelerator && status.ollama_accelerator !== "não informado"
        ? ` · ${status.ollama_accelerator}` : "";
      if (selected && loaded && selected !== loaded) {
        dot.classList.add("idle");
        label.textContent = "Será carregado ao iniciar a pesquisa";
      } else {
        dot.classList.add("ready");
        label.textContent = `Pronto${accelerator}`;
      }
    } else {
      dot.classList.add("loading");
      label.textContent = "Iniciando Ollama…";
    }
  }

  function updateOllama(status) {
    lastOllamaStatus = status;
    renderModelStatus();
    if ((status.ollama_status === "pronto" || status.ollama_status === "erro") && !selectModelsRequested) {
      selectModelsRequested = true;
      refreshModels();
    }
  }

  // ---------- Barra de status e botão de execução ----------
  const SEEN_RESULT_KEY = "coletor-resultado-visto";
  let lastStatus = {};

  function seenResult() {
    try { return sessionStorage.getItem(SEEN_RESULT_KEY) || ""; } catch { return ""; }
  }

  function markResultSeen(researchId) {
    try { sessionStorage.setItem(SEEN_RESULT_KEY, researchId || ""); } catch { /* sem armazenamento */ }
  }

  function statusText(status) {
    const stage = status.stage || "ocioso";
    if (status.running) {
      if (stage === "cancelando") return ["Cancelando…", "Interrompendo a etapa atual"];
      if (stage === "Buscando Artigos") return ["Buscando artigos", "Consultando as bases em paralelo"];
      if (stage === "Validando e Ranqueando") {
        return ["Classificando artigos", status.current ? shortLabel(status.current, 90) : "Triagem com o modelo local"];
      }
      if (stage === "carregando modelo") return ["Carregando o modelo", status.ollama_model || ""];
      return ["Preparando a execução", ""];
    }
    if (stage === "concluído") return ["Pesquisa concluída", "Ranking gerado"];
    if (stage === "cancelado") return ["Pesquisa cancelada", "Resultados parciais ficam no histórico"];
    if (stage === "falhou") return ["Execução com erro", status.error || "Consulte o relatório da execução"];
    return ["Pronto para configurar", ""];
  }

  function updateStatus(status) {
    lastStatus = status;
    updateOllama(status);
    const stage = status.stage || "ocioso";
    const [title, detail] = statusText(status);
    const bar = $("status-bar");
    bar.dataset.state = status.running ? "running" : stage === "concluído" ? "done" : stage === "falhou" ? "error" : stage === "cancelado" ? "cancelled" : "idle";
    const dot = $("state-dot");
    dot.className = "state-dot";
    if (status.running) dot.classList.add("loading");
    else if (stage === "concluído") dot.classList.add("ready");
    else if (stage === "falhou") dot.classList.add("error");
    $("stage").textContent = title;
    $("status-detail").textContent = detail;
    bar.title = [title, detail].filter(Boolean).join(" · ");
    $("status-count").textContent = status.running && status.total ? `${status.processed} / ${status.total}` : "";

    const fill = $("status-fill");
    const track = fill.parentElement;
    track.classList.toggle("visible", Boolean(status.running));
    track.classList.toggle("indeterminate", Boolean(status.running && !status.total));
    fill.style.width = status.running && status.total ? `${Math.round((status.processed / status.total) * 100)}%` : "";

    const showResult = !status.running && stage === "concluído" && status.research_id && seenResult() !== status.research_id;
    $("run").classList.toggle("hidden", Boolean(status.running || showResult));
    $("run").disabled = Boolean(status.running);
    $("run-busy").classList.toggle("hidden", !status.running);
    $("cancel").classList.toggle("hidden", !status.running);
    $("cancel").disabled = stage === "cancelando";
    $("view-result").classList.toggle("hidden", !showResult);

    if (stage !== lastRunStage && lastRunStage !== "ocioso") {
      if (stage === "concluído") {
        notify("Pesquisa concluída.");
        refreshHistory();
      } else if (stage === "falhou") {
        notify(status.error || "A execução falhou.", true);
        refreshHistory();
      } else if (stage === "cancelado") {
        notify("Pesquisa cancelada.");
        refreshHistory();
      }
    }
    lastRunStage = stage;
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
      lastRunStage = "iniciando";
      poll();
    } catch (error) {
      button.disabled = false;
      notify(error.message, true);
    }
  });
  $("cancel").addEventListener("click", async () => {
    $("cancel").disabled = true;
    try {
      await fetchJson("/api/cancel", { method: "POST" });
      poll();
    } catch (error) {
      $("cancel").disabled = false;
      notify(error.message, true);
    }
  });
  $("view-result").addEventListener("click", async () => {
    const researchId = lastStatus.research_id;
    markResultSeen(researchId);
    $("view-result").classList.add("hidden");
    $("run").classList.remove("hidden");
    await refreshHistory();
    if (researchId) openResearch(researchId);
  });
  $("refresh-history").addEventListener("click", refreshHistory);
  $("refresh-models").addEventListener("click", refreshModels);
  $("model").addEventListener("change", () => { preferredModel = $("model").value; renderModelStatus(); });
  $("logout").addEventListener("click", async () => {
    try {
      await fetchJson("/api/auth/logout", { method: "POST", credentials: "same-origin" });
      localStorage.removeItem(STORAGE_KEY);
      window.location.replace("/login");
    } catch (error) {
      notify(error.message, true);
    }
  });
  $("peso_aderencia").addEventListener("input", (e) => rebalanceWeights("aderencia", e.target.value));
  $("peso_aderencia_num").addEventListener("change", (e) => rebalanceWeights("aderencia", e.target.value));
  $("peso_ano").addEventListener("input", (e) => rebalanceWeights("ano", e.target.value));
  $("peso_ano_num").addEventListener("change", (e) => rebalanceWeights("ano", e.target.value));
  $("peso_citacoes").addEventListener("input", (e) => rebalanceWeights("citacoes", e.target.value));
  $("peso_citacoes_num").addEventListener("change", (e) => rebalanceWeights("citacoes", e.target.value));
  $("peso_tipo").addEventListener("input", (e) => rebalanceWeights("tipo", e.target.value));
  $("peso_tipo_num").addEventListener("change", (e) => rebalanceWeights("tipo", e.target.value));
  typeValueInputs().forEach((input) => input.addEventListener("change", () => currentTypeValues()));
  $("temperatura").addEventListener("input", (e) => renderTemperature(e.target.value));
  $("temperatura_num").addEventListener("change", (e) => renderTemperature(e.target.value));
  $("theme-toggle").addEventListener("click", () => {
    window.coletorTheme.toggle();
    syncThemeButton();
  });
  syncThemeButton();
  setupGraphControls();


  fetchJson("/api/config")
    .then((defaults) => {
      defaultConfig = defaults.config || {};
      try {
        const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
        if (saved?.model === "qwen2.5:7b") saved.model = "qwen3.5:0.8b";
        if (saved) {
          saved.config = { ...defaults.config, ...(saved.config || {}) };
          // Padrões novos no servidor (versão diferente): consulta e critérios salvos são substituídos uma vez.
          let savedVersion = null;
          try { savedVersion = localStorage.getItem(DEFAULTS_VERSION_KEY); } catch { /* sem armazenamento */ }
          const outdated = defaults.defaults_version && savedVersion !== defaults.defaults_version;
          if (outdated || !String(saved.config.query || "").trim()) saved.config.query = defaults.config?.query || "";
          if (outdated || !String(saved.criteria || "").trim()) saved.criteria = defaults.criteria || "";
          // Migração única: configurações salvas com o padrão antigo (0) passam ao novo padrão (0,1).
          let tempMigrated = false;
          try { tempMigrated = localStorage.getItem(TEMPERATURE_MIGRATION_KEY) === "1"; } catch { /* sem armazenamento */ }
          if (saved.temperature === undefined || (!tempMigrated && Number(saved.temperature) === 0)) {
            saved.temperature = defaults.temperature ?? DEFAULT_TEMPERATURE;
          }
          try { localStorage.setItem(TEMPERATURE_MIGRATION_KEY, "1"); } catch { /* sem armazenamento */ }
        }
        try { if (defaults.defaults_version) localStorage.setItem(DEFAULTS_VERSION_KEY, defaults.defaults_version); }
        catch { /* sem armazenamento */ }
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
