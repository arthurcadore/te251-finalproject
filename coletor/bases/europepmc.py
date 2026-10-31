"""Europe PMC — GET /webservices/rest/search, resultType=core (mapeamento a partir de tests/fixtures/europepmc/)."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from ..config import Enriquecimento, Filtros
from ..consulta import No, para_europepmc
from ..enriquecimento import europepmc as epmc
from ..filtros import LOCAL, NATIVO, PlanoFiltros, planejar
from ..modelo import Registro, normalizar_doi, unicos
from ..segredos import Credenciais
from ..texto import ISO1_PARA_ISO2B, html_para_texto, idioma_iso1
from .base import Adaptador, Pagina

RAIZ = "https://www.ebi.ac.uk/europepmc/webservices/rest/"
TIPO_NATIVO = {"artigo": 'PUB_TYPE:"journal article"', "revisao": 'PUB_TYPE:"review"', "preprint": "SRC:PPR"}
REVISOES = {"review", "review-article", "systematic review", "meta-analysis", "scoping review"}


def tipo_canonico(r: dict) -> str | None:
    tipos = (r.get("pubTypeList") or {}).get("pubType") or []
    baixo = {t.lower() for t in tipos}
    if r.get("source") == "PPR" or "preprint" in baixo:
        return "preprint"
    if baixo & REVISOES:
        return "revisao"
    if baixo & {"congress", "conference paper", "conference proceedings"}:
        return "conferencia"
    if baixo & {"book", "book chapter", "chapter"}:
        return "livro_capitulo"
    if baixo & {"journal article", "research-article"}:
        return "artigo"
    return tipos[0] if tipos else None


def _lista(d: dict | None, *chaves) -> list:
    for c in chaves:
        d = (d or {}).get(c)
    return d if isinstance(d, list) else ([d] if d else [])


class EuropePMC(Adaptador):
    chave = "europepmc"
    nome = "Europe PMC"
    colunas_extras = ["x_epmc_fonte", "x_epmc_grants", "x_epmc_substancias", "x_epmc_mesh_qualificadores",
                      "x_epmc_versao_preprint", "x_epmc_tem_dados"]

    @classmethod
    def limites_padrao(cls, cred: Credenciais) -> tuple[float, int]:
        return 2, 2

    def suporta(self, filtros: Filtros) -> PlanoFiltros:
        idiomas = NATIVO if all(i in ISO1_PARA_ISO2B for i in filtros.idiomas) else LOCAL
        return planejar(filtros, nome_base=self.nome, periodo=NATIVO, idiomas=idiomas, somente_oa=NATIVO,
                        tipos_nativos=lambda tipos: all(t in TIPO_NATIVO for t in tipos),
                        campos_nativos=frozenset({"tudo", "titulo", "titulo_resumo"}))

    def traduzir(self, arvore: No, plano: PlanoFiltros) -> str:
        f = self.ctx.config.filtros
        partes = [para_europepmc(arvore, f.campo_busca if plano.nativo("campo_busca") else "tudo")]
        if plano.nativo("periodo"):
            partes.append(f"PUB_YEAR:[{f.ano_de if f.ano_de is not None else 1000} TO "
                          f"{f.ano_ate if f.ano_ate is not None else 3000}]")
        if plano.nativo("idiomas"):  # ISO 639-2 de 3 letras: LANG:"pt" não funciona (teste prático)
            partes.append(" OR ".join(f'LANG:"{ISO1_PARA_ISO2B[i]}"' for i in f.idiomas))
        if plano.nativo("tipos"):
            partes.append(" OR ".join(TIPO_NATIVO[t] for t in f.tipos))
        if plano.nativo("somente_oa"):
            partes.append("OPEN_ACCESS:y")
        return partes[0] if len(partes) == 1 else " AND ".join(f"({p})" for p in partes)

    async def paginas(self, arvore: No, plano: PlanoFiltros, tamanho: int) -> AsyncIterator[Pagina]:
        q = self.traduzir(arvore, plano)
        cursor = "*"
        while True:
            resp = await self.ctx.cliente.get(RAIZ + "search", params={
                "query": q, "format": "json", "resultType": "core", "pageSize": tamanho, "cursorMark": cursor})
            d = resp.json()
            resultados = (d.get("resultList") or {}).get("result") or []
            prox = d.get("nextCursorMark")
            ultima = not resultados or not prox or prox == cursor
            yield Pagina([self.normalizar(r) for r in resultados], d.get("hitCount"), ultima=ultima)
            if ultima:
                return
            cursor = prox

    async def enriquecer(self, registros: list[Registro], opcoes: Enriquecimento) -> list[Registro]:
        """Referências quando hasReferences=Y; texto completo para OA com PMCID (seção 8.1)."""
        etapas = []
        for r in registros:
            if opcoes.referencias:
                etapas.append(self.com_aviso(r, epmc.referencias(r, self.ctx.cliente)))
            if opcoes.texto_completo:
                etapas.append(self.com_aviso(r, epmc.texto_completo(r, self.ctx.cliente)))
        await asyncio.gather(*etapas)
        return registros

    def normalizar(self, r: dict) -> Registro:
        autores = _lista(r, "authorList", "author")
        jinfo = r.get("journalInfo") or {}
        journal = jinfo.get("journal") or {}
        tipos = _lista(r, "pubTypeList", "pubType")
        fonte, ident = r.get("source"), r.get("id")
        pdfs = [u.get("url") for u in _lista(r, "fullTextUrlList", "fullTextUrl")
                if u.get("documentStyle") == "pdf" and u.get("availabilityCode") == "OA"]
        afil = unicos(a.get("affiliation") for au in autores
                      for a in _lista(au, "authorAffiliationDetailsList", "authorAffiliation"))
        oa = r.get("isOpenAccess")
        mesh = _lista(r, "meshHeadingList", "meshHeading")
        reg = Registro(
            base=self.chave,
            id_na_base=ident or "",
            doi=normalizar_doi(r.get("doi")),
            pmid=r.get("pmid"),
            pmcid=r.get("pmcid"),
            url_pagina=f"https://europepmc.org/article/{fonte}/{ident}" if fonte and ident else None,
            titulo=html_para_texto(r.get("title")),
            autores=[a.get("fullName") or "" for a in autores],
            autores_orcid=[(a.get("authorId") or {}).get("value", "") if (a.get("authorId") or {}).get("type") == "ORCID"
                           else "" for a in autores],
            afiliacoes=afil or unicos([r.get("affiliation")]),
            ano=int(r["pubYear"]) if str(r.get("pubYear", "")).isdigit() else None,
            data_publicacao=r.get("firstPublicationDate"),
            tipo=tipo_canonico(r),
            idioma=idioma_iso1(r.get("language")),
            veiculo=journal.get("title") or (r.get("bookOrReportDetails") or {}).get("publisher"),
            issn=unicos([journal.get("issn"), journal.get("essn")]),
            volume=jinfo.get("volume"),
            numero=jinfo.get("issue"),
            paginas=r.get("pageInfo"),
            resumo=html_para_texto(r.get("abstractText")),
            palavras_chave=unicos(_lista(r, "keywordList", "keyword")),
            assuntos=unicos(m.get("descriptorName") for m in mesh),
            acesso_aberto={"Y": True, "N": False}.get(oa),
            licenca=r.get("license"),
            url_pdf=pdfs[0] if pdfs else None,
            n_citacoes=r.get("citedByCount"),
            fonte_citacoes="nativa" if r.get("citedByCount") is not None else "nenhuma",
            financiadores=unicos(g.get("agency") for g in _lista(r, "grantsList", "grant")),
            retratado=("Retracted Publication" in tipos) if tipos else None,
            raw=r,
        )
        reg.extras = {
            "x_epmc_fonte": fonte,
            "x_epmc_grants": unicos(f"{g.get('agency')}: {g.get('grantId')}" if g.get("grantId") else g.get("agency")
                                    for g in _lista(r, "grantsList", "grant")),
            "x_epmc_substancias": unicos(c.get("name") for c in _lista(r, "chemicalList", "chemical")),
            "x_epmc_mesh_qualificadores": unicos(
                f"{m.get('descriptorName')}/{q.get('qualifierName')}"
                for m in mesh for q in _lista(m, "meshQualifierList", "meshQualifier")),
            "x_epmc_versao_preprint": r.get("versionNumber"),
            "x_epmc_tem_dados": {"Y": True, "N": False}.get(r.get("hasData")),
        }
        return reg
