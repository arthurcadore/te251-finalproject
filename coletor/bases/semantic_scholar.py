"""Semantic Scholar — GET /graph/v1/paper/search (mapeamento a partir de tests/fixtures/semantic_scholar/)."""

from __future__ import annotations

from typing import AsyncIterator

from ..config import Enriquecimento, Filtros
from ..consulta import No, texto_simples
from ..enriquecimento import semantic_scholar as s2_lote
from ..filtros import NATIVO, SEM_DADO, PlanoFiltros, planejar
from ..modelo import Registro, espacos, normalizar_doi, unicos
from ..segredos import Credenciais
from ..texto import orcid
from .base import Adaptador, Pagina

URL_BUSCA = "https://api.semanticscholar.org/graph/v1/paper/search"
CAMPOS = ("paperId,corpusId,externalIds,url,title,abstract,venue,publicationVenue,year,referenceCount,"
          "citationCount,influentialCitationCount,isOpenAccess,openAccessPdf,fieldsOfStudy,s2FieldsOfStudy,"
          "publicationTypes,publicationDate,journal,authors.name,authors.authorId,authors.externalIds,"
          "authors.affiliations,tldr")
MAX_OFFSET = 1000  # a busca por relevância não passa de offset + limit = 1000

TIPO_NATIVO = {"artigo": ["JournalArticle"], "revisao": ["Review"], "conferencia": ["Conference"],
               "livro_capitulo": ["Book", "BookSection"]}
# prioridade quando há vários publicationTypes (ex.: ["Review", "JournalArticle"])
PRIORIDADE = [("Review", "revisao"), ("Conference", "conferencia"), ("Book", "livro_capitulo"),
              ("BookSection", "livro_capitulo"), ("JournalArticle", "artigo")]


def tipo_canonico(p: dict) -> str | None:
    tipos = p.get("publicationTypes") or []
    for original, canonico in PRIORIDADE:
        if original in tipos:
            return canonico
    if (p.get("externalIds") or {}).get("ArXiv"):
        return "preprint"  # sem tipo publicado e com ID arXiv
    return tipos[0] if tipos else None


class SemanticScholar(Adaptador):
    chave = "semantic_scholar"
    nome = "Semantic Scholar"
    colunas_extras = ["x_s2_corpus_id", "x_s2_dblp", "x_s2_mag", "x_s2_tipo_veiculo"]

    @classmethod
    def limites_padrao(cls, cred: Credenciais) -> tuple[float, int]:
        return 1, 1

    def suporta(self, filtros: Filtros) -> PlanoFiltros:
        return planejar(filtros, nome_base=self.nome, periodo=NATIVO, idiomas=SEM_DADO, somente_oa=NATIVO,
                        tipos_nativos=lambda tipos: "preprint" not in tipos)

    def traduzir(self, arvore: No, plano: PlanoFiltros) -> str:
        return " & ".join(f"{k}={v}" for k, v in self.parametros(arvore, plano).items())

    def parametros(self, arvore: No, plano: PlanoFiltros) -> dict:
        f = self.ctx.config.filtros
        # sem sintaxe de consulta; termos com hífen não casam (documentação da API)
        params: dict = {"query": texto_simples(arvore).replace("-", " ")}
        if plano.nativo("periodo"):
            params["year"] = f"{f.ano_de if f.ano_de is not None else ''}-{f.ano_ate if f.ano_ate is not None else ''}"
        if plano.nativo("tipos"):
            params["publicationTypes"] = ",".join(t for c in f.tipos for t in TIPO_NATIVO[c])
        if plano.nativo("somente_oa"):
            params["openAccessPdf"] = ""
        return params

    def _headers(self) -> dict:
        chave = self.ctx.credenciais.S2_API_KEY
        return {"x-api-key": chave} if chave else {}

    async def paginas(self, arvore: No, plano: PlanoFiltros, tamanho: int) -> AsyncIterator[Pagina]:
        params = {**self.parametros(arvore, plano), "fields": CAMPOS}
        offset = 0
        while True:
            lim = min(tamanho, MAX_OFFSET - offset)
            resp = await self.ctx.cliente.get(URL_BUSCA, params={**params, "offset": offset, "limit": lim},
                                              headers=self._headers())
            d = resp.json()
            dados = d.get("data") or []
            prox = d.get("next")
            ultima = prox is None or not dados or prox >= MAX_OFFSET
            yield Pagina([self.normalizar(p) for p in dados], d.get("total"), ultima=ultima)
            if ultima:
                return
            offset = prox

    async def enriquecer(self, registros: list[Registro], opcoes: Enriquecimento) -> list[Registro]:
        """Referências por POST /paper/batch: DOI quando houver, senão s2:paperId (seção 8.1)."""
        if opcoes.referencias:
            await s2_lote.referencias_em_lote(registros, self.ctx.cliente, self._headers())
        return registros

    def normalizar(self, p: dict) -> Registro:
        ext = p.get("externalIds") or {}
        venue = p.get("publicationVenue") or {}
        journal = p.get("journal") or {}
        oa = p.get("openAccessPdf") or {}
        autores = p.get("authors") or []
        status = oa.get("status")
        reg = Registro(
            base=self.chave,
            id_na_base=p.get("paperId") or "",
            doi=normalizar_doi(ext.get("DOI")),
            pmid=ext.get("PubMed"),
            pmcid=f"PMC{ext['PubMedCentral']}" if ext.get("PubMedCentral") else None,
            arxiv_id=ext.get("ArXiv"),
            url_pagina=p.get("url"),
            titulo=espacos(p.get("title")),
            autores=[a.get("name") or "" for a in autores],
            autores_orcid=[orcid((a.get("externalIds") or {}).get("ORCID")) for a in autores],
            afiliacoes=unicos(x for a in autores for x in a.get("affiliations") or []),
            ano=p.get("year"),
            data_publicacao=p.get("publicationDate"),
            tipo=tipo_canonico(p),
            veiculo=venue.get("name") or journal.get("name") or p.get("venue") or None,
            issn=unicos([venue.get("issn")]),
            volume=espacos(journal.get("volume")),
            paginas=espacos(journal.get("pages")),
            resumo=p.get("abstract"),
            tldr=(p.get("tldr") or {}).get("text"),
            assuntos=unicos([s.get("category") for s in p.get("s2FieldsOfStudy") or []] + (p.get("fieldsOfStudy") or [])),
            acesso_aberto=p.get("isOpenAccess"),
            status_oa=status.lower() if status else None,
            licenca=oa.get("license"),
            url_pdf=oa.get("url") or None,
            n_citacoes=p.get("citationCount"),
            n_citacoes_influentes=p.get("influentialCitationCount"),
            n_referencias=p.get("referenceCount"),
            fonte_citacoes="nativa" if p.get("citationCount") is not None else "nenhuma",
            raw=p,
        )
        reg.extras = {
            "x_s2_corpus_id": p.get("corpusId") or ext.get("CorpusId"),
            "x_s2_dblp": ext.get("DBLP"),
            "x_s2_mag": ext.get("MAG"),
            "x_s2_tipo_veiculo": venue.get("type"),
        }
        return reg
