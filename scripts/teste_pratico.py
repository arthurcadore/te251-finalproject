#!/usr/bin/env python3
"""Teste prático das APIs (seção 11 do ESCOPO.md).

Uso:
    python scripts/teste_pratico.py coletar     # acessa a internet e grava tests/fixtures/<base>/
    python scripts/teste_pratico.py relatorio   # offline: gera docs/relatorio_teste_pratico.md
    python scripts/teste_pratico.py             # os dois

Para cada base faz uma busca real pequena (consulta `machine learning`, 5 resultados),
uma chamada por parâmetro de filtro da seção 6 e uma chamada de cada endpoint de
enriquecimento. Cada resposta é gravada como `<nome>.<ext>` e os metadados da chamada
(URL sem segredos, status, headers de limite, tentativas, 429) em `_index.json`.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import httpx
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
FIXTURES = RAIZ / "tests" / "fixtures"
RELATORIO = RAIZ / "docs" / "relatorio_teste_pratico.md"

load_dotenv(RAIZ / ".env")
ENV = {k: (os.getenv(k) or "").strip() for k in (
    "OPENALEX_API_KEY", "CONTACT_EMAIL", "NCBI_API_KEY", "S2_API_KEY",
    "CORE_API_KEY", "OPENCITATIONS_TOKEN",
)}
EMAIL = ENV["CONTACT_EMAIL"]
USER_AGENT = f"coletor-artigos/1.0 (mailto:{EMAIL})"
CONSULTA = "machine learning"
N = 5
PARAMS_SENSIVEIS = {"api_key", "mailto", "email"}

# ---------------------------------------------------------------- segredos


def _segredos() -> list[str]:
    return [v for v in ENV.values() if v]


def higienizar_texto(texto: str) -> str:
    for s in _segredos():
        texto = texto.replace(s, "***")
        texto = texto.replace(quote(s, safe=""), "***")
    return texto


def higienizar_url(url: str) -> str:
    p = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k not in PARAMS_SENSIVEIS]
    return higienizar_texto(urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), p.fragment)))


# ---------------------------------------------------------------- limitador mínimo


class Limitador:
    """Token bucket + semáforo + retentativa. Versão mínima para o teste prático."""

    PISO = 0.1  # 1 req a cada 10 s
    BACKOFF = [2, 4, 8, 16, 32]

    def __init__(self, nome: str, taxa: float, concorrencia: int):
        self.nome = nome
        self.taxa_inicial = taxa
        self.taxa = taxa
        self._sem = asyncio.Semaphore(concorrencia)
        self._lock = asyncio.Lock()
        self._proximo = 0.0
        self._ok_seguidos = 0
        self.n_chamadas = 0
        self.n_429 = 0

    async def _vez(self) -> None:
        async with self._lock:
            agora = time.monotonic()
            espera = max(0.0, self._proximo - agora)
            self._proximo = max(agora, self._proximo) + 1.0 / self.taxa
        if espera:
            await asyncio.sleep(espera)

    async def requisitar(self, cliente: httpx.AsyncClient, metodo: str, url: str, **kw):
        historico: list[str] = []
        resp = None
        for tentativa in range(6):
            espera = None
            async with self._sem:
                await self._vez()
                self.n_chamadas += 1
                try:
                    resp = await cliente.request(metodo, url, **kw)
                except (httpx.TimeoutException, httpx.TransportError) as e:
                    historico.append(type(e).__name__)
                    espera = self._backoff(tentativa)
                else:
                    historico.append(str(resp.status_code))
                    if resp.status_code == 429:
                        self.n_429 += 1
                        self._ok_seguidos = 0
                        self.taxa = max(self.PISO, self.taxa / 2)
                        espera = _retry_after(resp) or self._backoff(tentativa)
                    elif resp.status_code >= 500:
                        espera = self._backoff(tentativa)
                    else:
                        if resp.status_code < 400:
                            self._ok_seguidos += 1
                            if self._ok_seguidos >= 20:
                                self.taxa = min(self.taxa_inicial, self.taxa * 1.25)
                                self._ok_seguidos = 0
                        return resp, historico
            if tentativa < 5:
                print(f"  [{self.nome}] {historico[-1]} → esperando {espera:.1f}s", flush=True)
                await asyncio.sleep(espera)
        return resp, historico

    def _backoff(self, tentativa: int) -> float:
        base = self.BACKOFF[min(tentativa, len(self.BACKOFF) - 1)]
        return base + random.uniform(0, base / 2)


def _retry_after(resp: httpx.Response) -> float | None:
    v = resp.headers.get("retry-after")
    if v and v.strip().isdigit():
        return min(float(v), 120.0)
    return None


# ---------------------------------------------------------------- gravação


@dataclass
class Sessao:
    base: str
    limitador: Limitador
    cliente: httpx.AsyncClient
    indice: list[dict] = field(default_factory=list)

    @property
    def dir(self) -> Path:
        d = FIXTURES / self.base
        d.mkdir(parents=True, exist_ok=True)
        return d

    async def chamar(self, nome: str, metodo: str, url: str, ext: str = "json", **kw) -> httpx.Response | None:
        print(f"[{self.base}] {nome}", flush=True)
        t0 = time.monotonic()
        resp, historico = await self.limitador.requisitar(self.cliente, metodo, url, **kw)
        dur = time.monotonic() - t0
        meta = {
            "nome": nome,
            "metodo": metodo,
            "url": higienizar_url(str(resp.request.url)) if resp is not None else higienizar_url(url),
            "corpo_requisicao": kw.get("json"),
            "status": resp.status_code if resp is not None else None,
            "tentativas": historico,
            "duracao_s": round(dur, 2),
            "content_type": resp.headers.get("content-type") if resp is not None else None,
            "headers_limite": _headers_limite(resp) if resp is not None else {},
            "arquivo": None,
        }
        if resp is not None:
            arq = f"{nome}.{ext}"
            (self.dir / arq).write_text(higienizar_texto(resp.text), encoding="utf-8")
            meta["arquivo"] = arq
        self.indice.append(meta)
        return resp

    def salvar_indice(self, extra: dict | None = None) -> None:
        """Mescla com o índice existente: chamadas de mesmo nome são substituídas."""
        execucao = {
            "taxa_inicial": self.limitador.taxa_inicial,
            "taxa_final": self.limitador.taxa,
            "chamadas_http": self.limitador.n_chamadas,
            "n_429": self.limitador.n_429,
            **(extra or {}),
        }
        arq = self.dir / "_index.json"
        dados = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {"base": self.base, "execucoes": [], "chamadas": []}
        novos = {c["nome"] for c in self.indice}
        dados["chamadas"] = [c for c in dados["chamadas"] if c["nome"] not in novos] + self.indice
        dados["execucoes"].append(execucao)
        (self.dir / "_index.json").write_text(
            higienizar_texto(json.dumps(dados, ensure_ascii=False, indent=2)), encoding="utf-8")


def _headers_limite(resp: httpx.Response) -> dict:
    padrao = re.compile(r"rate|limit|retry|quota|cost|credit", re.I)
    return {k: higienizar_texto(v) for k, v in resp.headers.items() if padrao.search(k)}


def _json(resp: httpx.Response | None):
    if resp is None or resp.status_code >= 400:
        return None
    try:
        return resp.json()
    except ValueError:
        return None


def nova_sessao(base: str, taxa: float, conc: int, headers: dict | None = None, timeout: float = 30) -> Sessao:
    h = {"User-Agent": USER_AGENT, **(headers or {})}
    cliente = httpx.AsyncClient(headers=h, timeout=httpx.Timeout(timeout), follow_redirects=True)
    return Sessao(base, Limitador(base, taxa, conc), cliente)


# ---------------------------------------------------------------- bases


async def t_openalex(compart: dict) -> None:
    s = nova_sessao("openalex", 10, 5)
    url = "https://api.openalex.org/works"
    base = {"per_page": N, "api_key": ENV["OPENALEX_API_KEY"]}
    try:
        r = await s.chamar("busca", "GET", url, params={**base, "search": CONSULTA, "cursor": "*"})
        d = _json(r)
        if d and d.get("meta", {}).get("next_cursor"):
            await s.chamar("pagina2", "GET", url, params={**base, "search": CONSULTA, "cursor": d["meta"]["next_cursor"]})
        variantes = {
            "filtro_periodo": {"search": CONSULTA, "filter": "from_publication_date:2021-01-01,to_publication_date:2022-12-31"},
            "filtro_idioma": {"search": CONSULTA, "filter": "language:pt"},
            "filtro_tipo_revisao": {"search": CONSULTA, "filter": "type:review"},
            "filtro_tipo_preprint": {"search": CONSULTA, "filter": "type:preprint"},
            "filtro_tipo_conferencia": {"search": CONSULTA, "filter": "primary_location.source.type:conference"},
            "filtro_tipo_livro": {"search": CONSULTA, "filter": "type:book|book-chapter"},
            "filtro_oa": {"search": CONSULTA, "filter": "open_access.is_oa:true"},
            "campo_titulo": {"filter": f"title.search:{CONSULTA}"},
            "campo_titulo_resumo": {"filter": f"title_and_abstract.search:{CONSULTA}"},
        }
        for nome, p in variantes.items():
            await s.chamar(nome, "GET", url, params={**base, **p})
        ids: list[str] = []
        for w in (d or {}).get("results", []):
            ids += w.get("referenced_works", [])[:10] + w.get("related_works", [])[:5]
            if w.get("doi"):
                compart.setdefault("dois", []).append(w["doi"])
        ids = [i.rsplit("/", 1)[-1] for i in ids][:100]
        if ids:
            await s.chamar("enriq_ids_para_doi", "GET", url, params={
                "filter": "openalex_id:" + "|".join(ids), "select": "id,doi", "per_page": 100,
                "api_key": ENV["OPENALEX_API_KEY"]})
    finally:
        s.salvar_indice()
        await s.cliente.aclose()


async def t_semantic_scholar(compart: dict) -> None:
    h = {"x-api-key": ENV["S2_API_KEY"]} if ENV["S2_API_KEY"] else {}
    s = nova_sessao("semantic_scholar", 1, 1, h)
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    campos_completos = ("paperId,corpusId,externalIds,url,title,abstract,venue,publicationVenue,year,"
                        "referenceCount,citationCount,influentialCitationCount,isOpenAccess,openAccessPdf,"
                        "fieldsOfStudy,s2FieldsOfStudy,publicationTypes,publicationDate,journal,"
                        "authors.name,authors.authorId,authors.externalIds,authors.affiliations,tldr")
    extra = {}
    try:
        r = await s.chamar("busca_campos_completos", "GET", url, params={"query": CONSULTA, "limit": N, "fields": campos_completos})
        campos = campos_completos
        if r is not None and r.status_code == 400:
            campos = campos_completos.replace(",tldr", "")
            r = await s.chamar("busca_sem_tldr", "GET", url, params={"query": CONSULTA, "limit": N, "fields": campos})
            if r is not None and r.status_code == 400:
                campos = re.sub(r",authors\.[a-zA-Z]+", "", campos) + ",authors"
                r = await s.chamar("busca", "GET", url, params={"query": CONSULTA, "limit": N, "fields": campos})
        extra["campos_aceitos_na_busca"] = campos
        d = _json(r)
        variantes = {
            "pagina2": {"offset": N},
            "filtro_periodo": {"year": "2021-2022"},
            "filtro_tipo_revisao": {"publicationTypes": "Review"},
            "filtro_tipo_conferencia": {"publicationTypes": "Conference"},
            "filtro_tipo_artigo": {"publicationTypes": "JournalArticle"},
            "filtro_tipo_livro": {"publicationTypes": "Book,BookSection"},
            "filtro_oa": {"openAccessPdf": ""},
        }
        for nome, p in variantes.items():
            await s.chamar(nome, "GET", url, params={"query": CONSULTA, "limit": N, "fields": campos, **p})
        ids = [p["paperId"] for p in (d or {}).get("data", []) if p.get("paperId")]
        if ids:
            await s.chamar("enriq_batch_referencias", "POST", "https://api.semanticscholar.org/graph/v1/paper/batch",
                           params={"fields": "paperId,externalIds,citationCount,influentialCitationCount,tldr,"
                                             "references.paperId,references.externalIds"},
                           json={"ids": ids})
    finally:
        s.salvar_indice(extra)
        await s.cliente.aclose()


async def t_crossref(compart: dict) -> None:
    taxa, conc = (3, 3) if EMAIL else (1, 1)
    s = nova_sessao("crossref", taxa, conc)
    url = "https://api.crossref.org/works"
    base = {"rows": N, "mailto": EMAIL} if EMAIL else {"rows": N}
    try:
        r = await s.chamar("busca", "GET", url, params={**base, "query.bibliographic": CONSULTA, "cursor": "*"})
        d = _json(r)
        cursor = (d or {}).get("message", {}).get("next-cursor")
        if cursor:
            await s.chamar("pagina2", "GET", url, params={**base, "query.bibliographic": CONSULTA, "cursor": cursor})
        variantes = {
            "filtro_periodo": {"filter": "from-pub-date:2021-01-01,until-pub-date:2022-12-31"},
            "filtro_tipo_artigo": {"filter": "type:journal-article"},
            "filtro_tipo_preprint": {"filter": "type:posted-content"},
            "filtro_tipo_conferencia": {"filter": "type:proceedings-article"},
            "filtro_tipo_livro": {"filter": "type:book,type:book-chapter"},
            "filtro_com_referencias": {"filter": "has-references:true"},
        }
        for nome, p in variantes.items():
            await s.chamar(nome, "GET", url, params={**base, "query.bibliographic": CONSULTA, **p})
        for it in (d or {}).get("message", {}).get("items", []):
            if it.get("DOI"):
                compart.setdefault("dois", []).append(it["DOI"])
    finally:
        s.salvar_indice()
        await s.cliente.aclose()


async def t_arxiv(compart: dict) -> None:
    s = nova_sessao("arxiv", 1 / 3, 1, timeout=60)
    url = "https://export.arxiv.org/api/query"
    q = "all:machine AND all:learning"
    try:
        variantes = {
            "busca": {"search_query": q},
            "pagina2": {"search_query": q, "start": N},
            "busca_frase": {"search_query": 'all:"machine learning"'},
            "filtro_periodo": {"search_query": f"({q}) AND submittedDate:[202101010000 TO 202212312359]"},
            "campo_titulo": {"search_query": "ti:machine AND ti:learning"},
            "campo_titulo_resumo": {"search_query": "(ti:machine OR abs:machine) AND (ti:learning OR abs:learning)"},
        }
        for nome, p in variantes.items():
            await s.chamar(nome, "GET", url, ext="xml", params={**p, "max_results": N})
    finally:
        s.salvar_indice()
        await s.cliente.aclose()


async def t_pubmed(compart: dict) -> None:
    com_chave = bool(ENV["NCBI_API_KEY"])
    s = nova_sessao("pubmed", 9 if com_chave else 3, 3)
    eu = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    base = {"db": "pubmed", "retmode": "json", "retmax": N, "tool": "coletor-artigos"}
    if EMAIL:
        base["email"] = EMAIL
    if com_chave:
        base["api_key"] = ENV["NCBI_API_KEY"]
    try:
        r = await s.chamar("esearch", "GET", eu + "esearch.fcgi", params={**base, "term": CONSULTA})
        d = _json(r)
        termos = {
            "pagina2": (CONSULTA, {"retstart": N}),
            "filtro_periodo": (f"({CONSULTA}) AND 2021:2022[dp]", {}),
            "filtro_idioma_por": (f"({CONSULTA}) AND por[la]", {}),
            "filtro_idioma_portuguese": (f"({CONSULTA}) AND portuguese[la]", {}),
            "filtro_tipo_artigo": (f'({CONSULTA}) AND "Journal Article"[pt]', {}),
            "filtro_tipo_revisao": (f"({CONSULTA}) AND Review[pt]", {}),
            "filtro_tipo_preprint": (f"({CONSULTA}) AND Preprint[pt]", {}),
            "filtro_tipo_conferencia": (f"({CONSULTA}) AND Congress[pt]", {}),
            "filtro_tipo_livro": (f'({CONSULTA}) AND "Book Chapter"[pt]', {}),
            "filtro_oa": (f"({CONSULTA}) AND free full text[sb]", {}),
            "campo_titulo": ("machine learning[ti]", {}),
            "campo_titulo_resumo": ("machine learning[tiab]", {}),
        }
        for nome, (t, extra) in termos.items():
            await s.chamar(f"esearch_{nome}", "GET", eu + "esearch.fcgi", params={**base, "term": t, **extra})
        pmids = (d or {}).get("esearchresult", {}).get("idlist", [])
        if pmids:
            p = {k: v for k, v in base.items() if k not in ("retmode", "retmax")}
            await s.chamar("efetch", "GET", eu + "efetch.fcgi", ext="xml",
                           params={**p, "id": ",".join(pmids), "retmode": "xml"})
            compart["pmids"] = pmids
    finally:
        s.salvar_indice()
        await s.cliente.aclose()


async def t_europepmc(compart: dict) -> None:
    s = nova_sessao("europepmc", 2, 2)
    raiz = "https://www.ebi.ac.uk/europepmc/webservices/rest/"
    base = {"format": "json", "resultType": "core", "pageSize": N}
    extra: dict = {}
    try:
        r = await s.chamar("busca", "GET", raiz + "search", params={**base, "query": CONSULTA, "cursorMark": "*"})
        d = _json(r)
        if d and d.get("nextCursorMark"):
            await s.chamar("pagina2", "GET", raiz + "search",
                           params={**base, "query": CONSULTA, "cursorMark": d["nextCursorMark"]})
        variantes = {
            "filtro_periodo": f"({CONSULTA}) AND PUB_YEAR:[2021 TO 2022]",
            "filtro_idioma_por": f'({CONSULTA}) AND LANG:"por"',
            "filtro_idioma_pt": f'({CONSULTA}) AND LANG:"pt"',
            "filtro_tipo_artigo": f'({CONSULTA}) AND PUB_TYPE:"journal article"',
            "filtro_tipo_revisao": f'({CONSULTA}) AND PUB_TYPE:"review"',
            "filtro_tipo_preprint": f"({CONSULTA}) AND SRC:PPR",
            "filtro_oa": f"({CONSULTA}) AND OPEN_ACCESS:y",
            "campo_titulo": 'TITLE:"machine learning"',
            "campo_titulo_resumo": '(TITLE:"machine learning" OR ABSTRACT:"machine learning")',
        }
        for nome, q in variantes.items():
            await s.chamar(nome, "GET", raiz + "search", params={**base, "query": q})
        # referências
        alvo = next((x for x in (d or {}).get("resultList", {}).get("result", [])
                     if x.get("hasReferences") == "Y"), None)
        if alvo is None:
            r2 = await s.chamar("busca_com_referencias", "GET", raiz + "search",
                                params={**base, "query": f"({CONSULTA}) AND HAS_REFLIST:y"})
            alvo = next(iter((_json(r2) or {}).get("resultList", {}).get("result", [])), None)
        if alvo:
            await s.chamar("enriq_referencias", "GET", raiz + f"{alvo['source']}/{alvo['id']}/references",
                           params={"format": "json", "pageSize": 25, "page": 1})
        # texto completo
        r3 = await s.chamar("busca_oa_pmc", "GET", raiz + "search",
                            params={**base, "query": f"({CONSULTA}) AND OPEN_ACCESS:y AND IN_EPMC:y"})
        pmc = next((x.get("pmcid") for x in (_json(r3) or {}).get("resultList", {}).get("result", [])
                    if x.get("pmcid")), None)
        if pmc:
            await s.chamar("enriq_texto_completo", "GET", raiz + f"{pmc}/fullTextXML", ext="xml")
        # rajada sustentada a 2 req/s para observar 429 (20 chamadas pequenas)
        n429_antes = s.limitador.n_429
        t0 = time.monotonic()
        statuses = []
        cursor = "*"
        for _ in range(20):
            resp, hist = await s.limitador.requisitar(s.cliente, "GET", raiz + "search", params={
                "format": "json", "resultType": "idlist", "pageSize": 1, "query": CONSULTA, "cursorMark": cursor})
            statuses.append(hist)
            dj = _json(resp)
            cursor = (dj or {}).get("nextCursorMark", cursor)
        extra["teste_rajada"] = {
            "chamadas": 20, "duracao_s": round(time.monotonic() - t0, 1),
            "n_429": s.limitador.n_429 - n429_antes, "historicos": statuses,
        }
    finally:
        s.salvar_indice(extra)
        await s.cliente.aclose()


async def t_core(compart: dict) -> None:
    com_chave = bool(ENV["CORE_API_KEY"])
    h = {"Authorization": f"Bearer {ENV['CORE_API_KEY']}"} if com_chave else {}
    s = nova_sessao("core", 2 if com_chave else 0.5, 1, h, timeout=60)
    url = "https://api.core.ac.uk/v3/search/works/"
    extra = {"com_chave": com_chave}
    try:
        r = await s.chamar("busca", "GET", url, params={"q": CONSULTA, "limit": N})
        hist = s.indice[-1]["tentativas"]
        extra["busca_anonima_historico"] = hist
        if r is None or r.status_code == 429:
            # duas tentativas extras espaçadas para confirmar "sempre 429"
            for i in range(2):
                await asyncio.sleep(30)
                r = await s.chamar(f"busca_reteste_{i + 1}", "GET", url, params={"q": CONSULTA, "limit": N})
                if r is not None and r.status_code != 429:
                    break
        d = _json(r)
        extra["busca_funcionou"] = d is not None
        if d is None:
            return
        variantes = {
            "pagina2": {"q": CONSULTA, "offset": N},
            "filtro_periodo": {"q": f"({CONSULTA}) AND yearPublished>=2021 AND yearPublished<=2022"},
            "filtro_idioma": {"q": f"({CONSULTA}) AND language.code:pt"},
            "campo_titulo": {"q": 'title:"machine learning"'},
            "campo_titulo_resumo": {"q": '(title:"machine learning" OR abstract:"machine learning")'},
        }
        for nome, p in variantes.items():
            await s.chamar(nome, "GET", url, params={**p, "limit": N})
        for w in d.get("results", []):
            if w.get("doi"):
                compart.setdefault("dois", []).append(w["doi"])
        wid = next((w["id"] for w in d.get("results", []) if w.get("id")), None)
        if wid:
            await s.chamar("enriq_work", "GET", f"https://api.core.ac.uk/v3/works/{wid}")
    finally:
        s.salvar_indice(extra)
        await s.cliente.aclose()


async def t_doaj(compart: dict) -> None:
    s = nova_sessao("doaj", 2, 1)
    raiz = "https://doaj.org/api/search/articles/"
    try:
        variantes = {
            "busca": (CONSULTA, {}),
            "pagina2": (CONSULTA, {"page": 2}),
            "filtro_periodo": (f"({CONSULTA}) AND bibjson.year:[2021 TO 2022]", {}),
            "campo_titulo": ('bibjson.title:"machine learning"', {}),
            "campo_titulo_resumo": ('bibjson.title:"machine learning" OR bibjson.abstract:"machine learning"', {}),
            "limite_1000": (CONSULTA, {"page": 201}),
        }
        for nome, (q, p) in variantes.items():
            await s.chamar(nome, "GET", raiz + quote(q, safe=""), params={"pageSize": N, "page": 1, **p})
    finally:
        s.salvar_indice()
        await s.cliente.aclose()


async def t_scielo(compart: dict) -> None:
    s = nova_sessao("scielo", 1, 1)
    extra: dict = {}
    try:
        await s.chamar("search_robots", "GET", "https://search.scielo.org/robots.txt", ext="txt")
        await s.chamar("articlemeta_colecoes", "GET", "https://articlemeta.scielo.org/api/v1/collection/identifiers/")
        await s.chamar("articlemeta_identificadores", "GET", "https://articlemeta.scielo.org/api/v1/article/identifiers/",
                       params={"collection": "scl", "limit": N})
        await s.chamar("articlemeta_busca_q", "GET", "https://articlemeta.scielo.org/api/v1/article/",
                       params={"q": CONSULTA, "collection": "scl"})
        for fmt in ("json", "xml", "rss"):
            await s.chamar(f"search_output_{fmt}", "GET", "https://search.scielo.org/", ext="txt",
                           params={"q": CONSULTA, "lang": "pt", "count": N, "from": 0, "output": fmt})
    finally:
        s.salvar_indice(extra)
        await s.cliente.aclose()


async def t_opencitations(compart: dict) -> None:
    h = {"authorization": ENV["OPENCITATIONS_TOKEN"]} if ENV["OPENCITATIONS_TOKEN"] else {}
    s = nova_sessao("opencitations", 3, 3, h, timeout=60)
    raiz = "https://api.opencitations.net/index/v2/"
    try:
        dois = []
        for x in compart.get("dois", []):
            x = x.lower().removeprefix("https://doi.org/")
            if x not in dois:
                dois.append(x)
        doi = dois[0] if dois else "10.1038/nature14539"
        await s.chamar("referencias_doi", "GET", raiz + f"references/doi:{doi}")
        await s.chamar("citation_count_doi", "GET", raiz + f"citation-count/doi:{doi}")
        await s.chamar("reference_count_doi", "GET", raiz + f"reference-count/doi:{doi}")
        # DOI com referências conhecidas, para garantir fixture não vazia
        await s.chamar("referencias_doi_conhecido", "GET", raiz + "references/doi:10.1038/nature14539")
        pmid = (compart.get("pmids") or ["29902181"])[0]
        await s.chamar("referencias_pmid", "GET", raiz + f"references/pmid:{pmid}")
        await s.chamar("citation_count_pmid", "GET", raiz + f"citation-count/pmid:{pmid}")
    finally:
        s.salvar_indice({"doi_testado": doi})
        await s.cliente.aclose()


# ---------------------------------------------------------------- complementar
# Chamadas acrescentadas após a primeira coleta: dúvidas que ela levantou.


async def c_crossref() -> None:
    # Com cursor=* o Crossref devolveu scores 3,8–5,8 (sem cursor: 16,0): testar paginação por offset.
    s = nova_sessao("crossref", 3 if EMAIL else 1, 3 if EMAIL else 1)
    url = "https://api.crossref.org/works"
    base = {"rows": N, "query.bibliographic": CONSULTA, **({"mailto": EMAIL} if EMAIL else {})}
    try:
        await s.chamar("busca_sem_cursor", "GET", url, params=base)
        await s.chamar("pagina2_offset", "GET", url, params={**base, "offset": N})
    finally:
        s.salvar_indice()
        await s.cliente.aclose()


async def c_pubmed() -> None:
    # Congress[pt] e "Book Chapter"[pt] devolveram 0 com "phrase not found".
    s = nova_sessao("pubmed", 3, 3)
    eu = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    base = {"db": "pubmed", "retmode": "json", "retmax": N, "tool": "coletor-artigos",
            **({"email": EMAIL} if EMAIL else {})}
    termos = {
        "esearch_filtro_tipo_conferencia_pt_aspas": f'({CONSULTA}) AND "Congress"[Publication Type]',
        "esearch_filtro_tipo_livro_booksdocs": f"({CONSULTA}) AND booksdocs[filter]",
    }
    try:
        # A ordem padrão do esearch é "mais recentes"; conferir sort=relevance.
        r = await s.chamar("esearch_sort_relevance", "GET", eu + "esearch.fcgi",
                           params={**base, "term": CONSULTA, "sort": "relevance"})
        ids = (_json(r) or {}).get("esearchresult", {}).get("idlist", [])
        if ids:
            await s.chamar("efetch_relevancia", "GET", eu + "efetch.fcgi", ext="xml", params={
                **{k: v for k, v in base.items() if k not in ("retmode", "retmax")},
                "id": ",".join(ids), "retmode": "xml"})
        for nome, t in termos.items():
            r = await s.chamar(nome, "GET", eu + "esearch.fcgi", params={**base, "term": t})
            ids = (_json(r) or {}).get("esearchresult", {}).get("idlist", [])
            if nome.endswith("booksdocs") and ids:
                await s.chamar("efetch_livro", "GET", eu + "efetch.fcgi", ext="xml", params={
                    **{k: v for k, v in base.items() if k not in ("retmode", "retmax")},
                    "id": ",".join(ids[:2]), "retmode": "xml"})
        # A busca padrão devolve os PMIDs mais recentes, ainda sem MeSH/referências.
        # efetch de registros indexados (2021–2022, texto livre) para cobrir esses campos.
        ids = []
        for nome in ("esearch_filtro_periodo", "esearch_filtro_oa"):
            arq = FIXTURES / "pubmed" / f"{nome}.json"
            if arq.exists():
                ids += json.loads(arq.read_text())["esearchresult"]["idlist"][:3]
        if ids:
            await s.chamar("efetch_indexados", "GET", eu + "efetch.fcgi", ext="xml", params={
                **{k: v for k, v in base.items() if k not in ("retmode", "retmax")},
                "id": ",".join(ids), "retmode": "xml"})
    finally:
        s.salvar_indice()
        await s.cliente.aclose()


async def c_semantic_scholar() -> None:
    # Três filtros não passaram por 429 na primeira coleta: repetir com taxa bem menor.
    h = {"x-api-key": ENV["S2_API_KEY"]} if ENV["S2_API_KEY"] else {}
    s = nova_sessao("semantic_scholar", 0.2, 1, h)
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    campos = "paperId,externalIds,title,year,publicationTypes,isOpenAccess,openAccessPdf"
    variantes = {
        "filtro_periodo": {"year": "2021-2022"},
        "filtro_tipo_livro": {"publicationTypes": "Book,BookSection"},
        "filtro_oa": {"openAccessPdf": ""},
    }
    try:
        for nome, p in variantes.items():
            await s.chamar(nome, "GET", url, params={"query": CONSULTA, "limit": N, "fields": campos, **p})
    finally:
        s.salvar_indice({"modo": "complementar"})
        await s.cliente.aclose()


async def c_opencitations() -> None:
    h = {"authorization": ENV["OPENCITATIONS_TOKEN"]} if ENV["OPENCITATIONS_TOKEN"] else {}
    s = nova_sessao("opencitations", 3, 3, h, timeout=60)
    raiz = "https://api.opencitations.net/index/v2/"
    try:
        # PMID de 10.1038/nature14539, que tem referências conhecidas
        await s.chamar("referencias_pmid_conhecido", "GET", raiz + "references/pmid:26017442")
        await s.chamar("citation_count_doi_conhecido", "GET", raiz + "citation-count/doi:10.1038/nature14539")
    finally:
        s.salvar_indice()
        await s.cliente.aclose()


async def complementar() -> None:
    await asyncio.gather(c_crossref(), c_pubmed(), c_semantic_scholar(), c_opencitations())


async def coletar() -> None:
    if not ENV["OPENALEX_API_KEY"]:
        sys.exit("OPENALEX_API_KEY vazia no .env")
    compart: dict = {}
    tarefas = [t_openalex, t_semantic_scholar, t_crossref, t_arxiv, t_pubmed,
               t_europepmc, t_core, t_doaj, t_scielo]
    res = await asyncio.gather(*(t(compart) for t in tarefas), return_exceptions=True)
    for t, r in zip(tarefas, res):
        if isinstance(r, Exception):
            print(f"!! {t.__name__}: {type(r).__name__}: {higienizar_texto(str(r))}")
    await t_opencitations(compart)


def main() -> None:
    modo = sys.argv[1] if len(sys.argv) > 1 else "tudo"
    if modo in ("coletar", "tudo"):
        asyncio.run(coletar())
    if modo in ("complementar", "tudo"):
        asyncio.run(complementar())
    if modo in ("relatorio", "tudo"):
        from relatorio_teste_pratico import gerar  # noqa: E402  (mesmo diretório)
        gerar(FIXTURES, RELATORIO)


if __name__ == "__main__":
    main()
