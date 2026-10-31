"""OpenAlex — GET https://api.openalex.org/works (mapeamento a partir de tests/fixtures/openalex/)."""

from __future__ import annotations

import re
from typing import AsyncIterator

import httpx

from ..config import Enriquecimento, Filtros
from ..consulta import No, texto_booleano
from ..enriquecimento import openalex_ids
from ..filtros import NATIVO, PlanoFiltros, planejar
from ..http import ErroHTTP
from ..modelo import Registro, espacos, normalizar_doi, unicos
from ..segredos import Credenciais
from .base import Adaptador, EncerrarBase, Pagina

URL = "https://api.openalex.org/works"
CUSTO_BUSCA_USD = 0.001  # medido no teste prático (x-ratelimit-cost-usd)

TIPO_NATIVO = {"artigo": ["article"], "revisao": ["review"], "preprint": ["preprint"],
               "livro_capitulo": ["book", "book-chapter"]}
TIPO_CANONICO = {"article": "artigo", "review": "revisao", "preprint": "preprint", "book": "livro_capitulo",
                 "book-chapter": "livro_capitulo", "conference-paper": "conferencia"}


def _sufixo(url: str | None) -> str | None:
    """'https://openalex.org/W123' → 'W123'; 'https://orcid.org/0000-…' → '0000-…'."""
    return url.rstrip("/").rsplit("/", 1)[-1] if url else None


def _tipos_nativos(tipos: list[str]) -> bool:
    # conferência é filtro de outro campo (source.type); só dá para combinar com os demais localmente
    return "conferencia" not in tipos or tipos == ["conferencia"]


def resumo(indice: dict | None) -> str | None:
    """Reconstrói o texto a partir de `abstract_inverted_index` ({palavra: [posições]})."""
    if not indice:
        return None
    pos = {}
    for palavra, posicoes in indice.items():
        for p in posicoes:
            pos[p] = palavra
    return " ".join(pos[i] for i in sorted(pos)) or None


def _orcamento_esgotado(headers) -> bool:
    try:
        return float(headers.get("x-ratelimit-remaining-usd", "1")) < CUSTO_BUSCA_USD
    except ValueError:
        return False


class OpenAlex(Adaptador):
    chave = "openalex"
    nome = "OpenAlex"
    credencial_obrigatoria = "OPENALEX_API_KEY"
    colunas_extras = ["x_openalex_topico_principal", "x_openalex_area", "x_openalex_tipo_fonte",
                      "x_openalex_paises", "x_openalex_indexado_em", "x_openalex_apc_usd",
                      "x_openalex_ods", "x_openalex_mesh"]

    def __init__(self, ctx):
        super().__init__(ctx)
        self._cache_ids: dict[str, str | None] = {}  # W… → DOI, para toda a execução
        self._sem_orcamento = False

    @classmethod
    def limites_padrao(cls, cred: Credenciais) -> tuple[float, int]:
        return 10, 5

    def suporta(self, filtros: Filtros) -> PlanoFiltros:
        return planejar(filtros, nome_base=self.nome, periodo=NATIVO, idiomas=NATIVO, somente_oa=NATIVO,
                        tipos_nativos=_tipos_nativos,
                        campos_nativos=frozenset({"tudo", "titulo", "titulo_resumo"}))

    def traduzir(self, arvore: No, plano: PlanoFiltros) -> str:
        return " & ".join(f"{k}={v}" for k, v in self.parametros(arvore, plano).items())

    def parametros(self, arvore: No, plano: PlanoFiltros) -> dict:
        f = self.ctx.config.filtros
        q = texto_booleano(arvore)
        filtro = []
        params: dict = {}
        campo = f.campo_busca if plano.nativo("campo_busca") else "tudo"
        if campo == "tudo":
            params["search"] = q
        else:
            # vírgula separa filtros na API: não pode aparecer no valor
            nome = "title.search" if campo == "titulo" else "title_and_abstract.search"
            filtro.append(f"{nome}:{q.replace(',', ' ')}")
        if plano.nativo("periodo"):
            if f.ano_de is not None:
                filtro.append(f"from_publication_date:{f.ano_de}-01-01")
            if f.ano_ate is not None:
                filtro.append(f"to_publication_date:{f.ano_ate}-12-31")
        if plano.nativo("idiomas"):
            filtro.append("language:" + "|".join(f.idiomas))
        if plano.nativo("tipos"):
            if f.tipos == ["conferencia"]:
                filtro.append("primary_location.source.type:conference")
            else:
                filtro.append("type:" + "|".join(t for c in f.tipos for t in TIPO_NATIVO[c]))
        if plano.nativo("somente_oa"):
            filtro.append("open_access.is_oa:true")
        if filtro:
            params["filter"] = ",".join(filtro)
        return params

    async def paginas(self, arvore: No, plano: PlanoFiltros, tamanho: int) -> AsyncIterator[Pagina]:
        params = {**self.parametros(arvore, plano), "per_page": tamanho,
                  "api_key": self.ctx.credenciais.OPENALEX_API_KEY}
        cursor = "*"
        while cursor:
            try:
                resp = await self.ctx.cliente.get(URL, params={**params, "cursor": cursor},
                                                  parar=self._parar)
            except ErroHTTP as e:
                if e.status == 429:
                    raise EncerrarBase("orçamento diário do OpenAlex esgotado (HTTP 429)") from e
                raise
            d = resp.json()
            meta = d.get("meta") or {}
            resultados = d.get("results") or []
            cursor = meta.get("next_cursor")
            yield Pagina([self.normalizar(w) for w in resultados], meta.get("count"), ultima=not cursor)
            if not resp.do_cache and _orcamento_esgotado(resp.headers):
                raise EncerrarBase("orçamento diário do OpenAlex esgotado "
                                   f"(x-ratelimit-remaining-usd = {resp.headers.get('x-ratelimit-remaining-usd')})")

    @staticmethod
    def _parar(resp: httpx.Response) -> bool:
        """429 por orçamento esgotado não melhora com espera: não repetir."""
        return _orcamento_esgotado(resp.headers)

    async def enriquecer(self, registros: list[Registro], opcoes: Enriquecimento) -> list[Registro]:
        """Converte IDs W de referências e relacionados em DOI, por lote (seção 8.1)."""
        if not opcoes.resolver_ids_para_doi or self._sem_orcamento:
            return registros
        try:
            await openalex_ids.resolver(registros, self.ctx.cliente, self.ctx.credenciais.OPENALEX_API_KEY,
                                        self._cache_ids, self.log, _orcamento_esgotado)
        except openalex_ids.OrcamentoEsgotado as e:
            self._sem_orcamento = True
            self.ctx.estat.avisos.append(str(e))
            self.log.warning("%s: IDs mantidos como openalex:W…", e)
            for r in registros:
                r.avisar("enriquecimento_falhou")
        return registros

    # ------------------------------------------------------------ normalização

    def normalizar(self, w: dict) -> Registro:
        ids = w.get("ids") or {}
        prim = w.get("primary_location") or {}
        fonte = prim.get("source") or {}
        best = w.get("best_oa_location") or {}
        oa = w.get("open_access") or {}
        biblio = w.get("biblio") or {}
        autorias = w.get("authorships") or []
        tipo = w.get("type")
        canonico = "conferencia" if fonte.get("type") == "conference" else TIPO_CANONICO.get(tipo, tipo)
        arxiv = next((loc.get("landing_page_url") for loc in w.get("locations") or []
                      if "arxiv.org/abs/" in (loc.get("landing_page_url") or "")), None)
        paginas = "-".join(p for p in (biblio.get("first_page"), biblio.get("last_page")) if p) or None
        if biblio.get("first_page") and biblio.get("first_page") == biblio.get("last_page"):
            paginas = biblio["first_page"]
        financiadores = unicos(x.get("display_name") for x in w.get("funders") or []) or \
            unicos(x.get("funder_display_name") for x in w.get("awards") or [])
        pct = (w.get("citation_normalized_percentile") or {}).get("value")
        refs = [f"openalex:{_sufixo(x)}" for x in w.get("referenced_works") or []]
        reg = Registro(
            base=self.chave,
            id_na_base=_sufixo(w.get("id")) or "",
            doi=normalizar_doi(w.get("doi")),
            pmid=_sufixo(ids.get("pmid")),
            pmcid=_sufixo(ids.get("pmcid")),
            arxiv_id=_sem_versao(arxiv.split("arxiv.org/abs/", 1)[1]) if arxiv else None,
            url_pagina=prim.get("landing_page_url") or w.get("doi") or w.get("id"),
            titulo=espacos(w.get("title") or w.get("display_name")),
            autores=[(a.get("author") or {}).get("display_name") or a.get("raw_author_name") or "" for a in autorias],
            autores_orcid=[_sufixo((a.get("author") or {}).get("orcid")) or "" for a in autorias],
            afiliacoes=unicos(i.get("display_name") for a in autorias for i in a.get("institutions") or [])
            or unicos(s for a in autorias for s in a.get("raw_affiliation_strings") or []),
            ano=w.get("publication_year"),
            data_publicacao=w.get("publication_date"),
            tipo=canonico,
            idioma=w.get("language"),
            veiculo=fonte.get("display_name"),
            issn=unicos(fonte.get("issn") or []),
            editora=fonte.get("host_organization_name"),
            volume=biblio.get("volume"),
            numero=biblio.get("issue"),
            paginas=paginas,
            resumo=resumo(w.get("abstract_inverted_index")),
            palavras_chave=unicos(k.get("display_name") for k in w.get("keywords") or []),
            assuntos=unicos(t.get("display_name") for t in w.get("topics") or [])
            or unicos(c.get("display_name") for c in w.get("concepts") or []),
            acesso_aberto=oa.get("is_oa"),
            status_oa=oa.get("oa_status"),
            licenca=best.get("license") or prim.get("license"),
            url_pdf=best.get("pdf_url") or prim.get("pdf_url"),
            n_citacoes=w.get("cited_by_count"),
            citacoes_por_ano={c["year"]: c["cited_by_count"] for c in w.get("counts_by_year") or []
                              if c.get("year") is not None},
            percentil_citacoes=pct,
            fwci=w.get("fwci"),
            n_referencias=w.get("referenced_works_count"),
            referencias=refs,
            relacionados=[f"openalex:{_sufixo(x)}" for x in w.get("related_works") or []],
            fonte_referencias="nativa" if refs else "nenhuma",
            fonte_citacoes="nativa" if w.get("cited_by_count") is not None else "nenhuma",
            financiadores=financiadores,
            retratado=w.get("is_retracted"),
            raw=w,
        )
        topico = w.get("primary_topic") or {}
        reg.extras = {
            "x_openalex_topico_principal": topico.get("display_name"),
            "x_openalex_area": (topico.get("field") or {}).get("display_name"),
            "x_openalex_tipo_fonte": fonte.get("type"),
            "x_openalex_paises": unicos(c for a in autorias for c in a.get("countries") or []),
            "x_openalex_indexado_em": unicos(w.get("indexed_in") or []),
            "x_openalex_apc_usd": (w.get("apc_paid") or {}).get("value_usd"),
            "x_openalex_ods": unicos(s.get("display_name") for s in w.get("sustainable_development_goals") or []),
            "x_openalex_mesh": unicos(m.get("descriptor_name") for m in w.get("mesh") or []),
        }
        return reg


def _sem_versao(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", arxiv_id.strip("/"))
