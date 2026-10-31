"""Crossref — GET https://api.crossref.org/works (mapeamento a partir de tests/fixtures/crossref/).

Paginação por `offset`: com `cursor=*` a API descarta a ordem por relevância (teste prático, ESCOPO 15.3).
"""

from __future__ import annotations

from typing import AsyncIterator

from ..config import Enriquecimento, Filtros
from ..consulta import No, texto_simples
from ..enriquecimento import opencitations
from ..filtros import LOCAL, NATIVO, PlanoFiltros, planejar
from ..modelo import Registro, espacos, normalizar_doi, unicos
from ..segredos import Credenciais
from ..texto import data_iso, html_para_texto, idioma_iso1, orcid
from .base import Adaptador, Pagina

URL = "https://api.crossref.org/works"
MAX_OFFSET = 10000

TIPO_NATIVO = {"artigo": ["journal-article"], "preprint": ["posted-content"],
               "conferencia": ["proceedings-article"], "livro_capitulo": ["book", "book-chapter", "monograph"]}
TIPO_CANONICO = {t: c for c, ts in TIPO_NATIVO.items() for t in ts}


def _primeiro(lista) -> str | None:
    return espacos(lista[0]) if lista else None


def _data(item: dict) -> list:
    for campo in ("published", "issued", "published-print", "published-online"):
        partes = ((item.get(campo) or {}).get("date-parts") or [[]])[0]
        if partes and partes[0]:
            return partes
    return []


def acesso_aberto(item: dict) -> bool | None:
    """Sem campo de OA no Crossref: licença Creative Commons = aberto; outra licença = fechado; sem licença = ?"""
    urls = [lic.get("URL", "") for lic in item.get("license") or []]
    if not urls:
        return None
    return any("creativecommons.org" in u for u in urls)


class Crossref(Adaptador):
    chave = "crossref"
    nome = "Crossref"
    colunas_extras = ["x_crossref_isbn", "x_crossref_evento", "x_crossref_numero_artigo",
                      "x_crossref_subtitulo", "x_crossref_subtipo", "x_crossref_membro"]

    @classmethod
    def limites_padrao(cls, cred: Credenciais) -> tuple[float, int]:
        return (3, 3) if cred.CONTACT_EMAIL else (1, 1)

    def suporta(self, filtros: Filtros) -> PlanoFiltros:
        return planejar(filtros, nome_base=self.nome, periodo=NATIVO, idiomas=LOCAL, somente_oa=LOCAL,
                        tipos_nativos=lambda tipos: "revisao" not in tipos)

    def traduzir(self, arvore: No, plano: PlanoFiltros) -> str:
        return " & ".join(f"{k}={v}" for k, v in self.parametros(arvore, plano).items())

    def parametros(self, arvore: No, plano: PlanoFiltros) -> dict:
        f = self.ctx.config.filtros
        params: dict = {"query.bibliographic": texto_simples(arvore)}
        filtro = []
        if plano.nativo("periodo"):
            if f.ano_de is not None:
                filtro.append(f"from-pub-date:{f.ano_de}-01-01")
            if f.ano_ate is not None:
                filtro.append(f"until-pub-date:{f.ano_ate}-12-31")
        if plano.nativo("tipos"):
            # filtros repetidos com o mesmo nome são combinados com OU
            filtro += [f"type:{t}" for c in f.tipos for t in TIPO_NATIVO[c]]
        if filtro:
            params["filter"] = ",".join(filtro)
        return params

    async def paginas(self, arvore: No, plano: PlanoFiltros, tamanho: int) -> AsyncIterator[Pagina]:
        params = self.parametros(arvore, plano)
        email = self.ctx.credenciais.CONTACT_EMAIL
        if email:
            params["mailto"] = email  # pool "polite"; removido das URLs registradas
        offset = 0
        while True:
            resp = await self.ctx.cliente.get(URL, params={**params, "rows": tamanho, "offset": offset})
            msg = resp.json().get("message") or {}
            itens = msg.get("items") or []
            total = msg.get("total-results")
            offset += len(itens)
            ultima = not itens or (total is not None and offset >= total) or offset >= MAX_OFFSET
            yield Pagina([self.normalizar(i) for i in itens], total, ultima=ultima)
            if ultima:
                return

    async def enriquecer(self, registros: list[Registro], opcoes: Enriquecimento) -> list[Registro]:
        """Referências nativas (reference[].DOI); quando vazias e há DOI, OpenCitations (seção 8.1)."""
        if opcoes.referencias:
            await opencitations.enriquecer(registros, self.ctx.opencitations, self.log, citacoes=False)
        return registros

    def normalizar(self, i: dict) -> Registro:
        autores = i.get("author") or []
        data = _data(i)
        refs = unicos(normalizar_doi(r.get("DOI")) for r in i.get("reference") or [])
        n_ref = i.get("references-count", i.get("reference-count"))
        tipo = i.get("type")
        retratado = True if any((u.get("type") == "retraction") for u in i.get("updated-by") or []) else None
        pdfs = [lk.get("URL") for lk in i.get("link") or [] if lk.get("content-type") == "application/pdf"]
        reg = Registro(
            base=self.chave,
            id_na_base=normalizar_doi(i.get("DOI")) or "",
            doi=normalizar_doi(i.get("DOI")),
            url_pagina=i.get("URL") or (i.get("resource") or {}).get("primary", {}).get("URL"),
            titulo=_primeiro(i.get("title")),
            autores=[espacos(" ".join(x for x in (a.get("given"), a.get("family")) if x)) or a.get("name") or ""
                     for a in autores],
            autores_orcid=[orcid(a.get("ORCID")) for a in autores],
            afiliacoes=unicos(af.get("name") for a in autores for af in a.get("affiliation") or []),
            ano=data[0] if data else None,
            data_publicacao=data_iso(*data[:3]) if data else None,
            tipo=TIPO_CANONICO.get(tipo, tipo),
            idioma=idioma_iso1(i.get("language")),
            veiculo=_primeiro(i.get("container-title")),
            issn=unicos(i.get("ISSN") or []),
            editora=i.get("publisher"),
            volume=i.get("volume"),
            numero=i.get("issue"),
            paginas=i.get("page"),
            resumo=html_para_texto(i.get("abstract")),
            acesso_aberto=acesso_aberto(i),
            licenca=next((lic.get("URL") for lic in i.get("license") or []), None),
            url_pdf=pdfs[0] if pdfs else None,
            n_citacoes=i.get("is-referenced-by-count"),
            fonte_citacoes="nativa" if i.get("is-referenced-by-count") is not None else "nenhuma",
            n_referencias=n_ref,
            referencias=refs,
            fonte_referencias="nativa" if refs else "nenhuma",
            financiadores=unicos(f.get("name") for f in i.get("funder") or []),
            retratado=retratado,
            raw=i,
        )
        reg.extras = {
            "x_crossref_isbn": unicos(i.get("ISBN") or []),
            "x_crossref_evento": (i.get("event") or {}).get("name"),
            "x_crossref_numero_artigo": i.get("article-number"),
            "x_crossref_subtitulo": unicos(i.get("subtitle") or []),
            "x_crossref_subtipo": i.get("subtype"),
            "x_crossref_membro": i.get("member"),
        }
        return reg
