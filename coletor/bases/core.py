"""CORE — GET https://api.core.ac.uk/v3/search/works/ (mapeamento a partir de tests/fixtures/core/).

Sem `CORE_API_KEY` a busca funciona, mas `fullText` vem como texto fixo de indisponibilidade:
`texto_completo` fica vazio com o aviso `texto_completo_requer_chave` (ESCOPO 15.2).
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from ..config import Enriquecimento, Filtros
from ..consulta import No, para_core
from ..enriquecimento import core as core_texto
from ..enriquecimento import opencitations
from ..filtros import NATIVO, TODOS, PlanoFiltros, planejar
from ..modelo import Registro, espacos, normalizar_doi, unicos
from ..segredos import Credenciais
from ..texto import idioma_iso1
from .base import Adaptador, Pagina

URL = "https://api.core.ac.uk/v3/search/works/"  # a barra final é obrigatória
TIPO_CANONICO = {
    "research article": "artigo", "journal article": "artigo", "article": "artigo",
    "review": "revisao", "preprint": "preprint",
    "conference paper": "conferencia", "conference": "conferencia",
    "book": "livro_capitulo", "book chapter": "livro_capitulo", "book part": "livro_capitulo",
}


class Core(Adaptador):
    chave = "core"
    nome = "CORE"
    colunas_extras = ["x_core_provedores", "x_core_oai", "x_core_data_deposito"]

    @classmethod
    def limites_padrao(cls, cred: Credenciais) -> tuple[float, int]:
        return (2 if cred.CORE_API_KEY else 0.5), 1

    def suporta(self, filtros: Filtros) -> PlanoFiltros:
        return planejar(filtros, nome_base=self.nome, periodo=NATIVO, idiomas=NATIVO, somente_oa=TODOS,
                        tipos_nativos=lambda tipos: False,
                        campos_nativos=frozenset({"tudo", "titulo", "titulo_resumo"}))

    def traduzir(self, arvore: No, plano: PlanoFiltros) -> str:
        f = self.ctx.config.filtros
        partes = [para_core(arvore, f.campo_busca if plano.nativo("campo_busca") else "tudo")]
        if plano.nativo("periodo"):
            if f.ano_de is not None:
                partes.append(f"yearPublished>={f.ano_de}")
            if f.ano_ate is not None:
                partes.append(f"yearPublished<={f.ano_ate}")
        if plano.nativo("idiomas"):
            partes.append(" OR ".join(f"language.code:{i}" for i in f.idiomas))
        return partes[0] if len(partes) == 1 else " AND ".join(f"({p})" for p in partes)

    def _headers(self) -> dict:
        chave = self.ctx.credenciais.CORE_API_KEY
        return {"Authorization": f"Bearer {chave}"} if chave else {}

    async def paginas(self, arvore: No, plano: PlanoFiltros, tamanho: int) -> AsyncIterator[Pagina]:
        q = self.traduzir(arvore, plano)
        offset = 0
        while True:
            resp = await self.ctx.cliente.get(URL, params={"q": q, "limit": tamanho, "offset": offset},
                                              headers=self._headers())
            d = resp.json()
            res = d.get("results") or []
            total = d.get("totalHits")
            offset += len(res)
            ultima = not res or (total is not None and offset >= total)
            yield Pagina([self.normalizar(w) for w in res], total, ultima=ultima)
            if ultima:
                return

    async def enriquecer(self, registros: list[Registro], opcoes: Enriquecimento) -> list[Registro]:
        """Referências e citações pelo OpenCitations; texto completo por /v3/works/{id} (só com chave)."""
        etapas = []
        if opcoes.referencias:
            etapas.append(opencitations.enriquecer(registros, self.ctx.opencitations, self.log))
        if opcoes.texto_completo and self.ctx.credenciais.CORE_API_KEY:
            etapas += [self.com_aviso(r, core_texto.texto_completo(r, self.ctx.cliente, self._headers()))
                       for r in registros if not r.texto_completo]
        await asyncio.gather(*etapas)
        return registros

    def normalizar(self, w: dict) -> Registro:
        links = {lk.get("type"): lk.get("url") for lk in w.get("links") or []}
        doc = (w.get("documentType") or "").strip()
        lang = w.get("language") or {}
        issn = [str(i).split(":", 1)[-1] for j in w.get("journals") or [] for i in j.get("identifiers") or []
                if str(i).lower().startswith("issn:") or ":" not in str(i)]
        texto = w.get("fullText")
        reg = Registro(
            base=self.chave,
            id_na_base=str(w.get("id") or ""),
            doi=normalizar_doi(w.get("doi")),
            pmid=w.get("pubmedId") or None,
            arxiv_id=w.get("arxivId") or None,
            url_pagina=links.get("display") or (f"https://core.ac.uk/works/{w['id']}" if w.get("id") else None),
            titulo=espacos(w.get("title")),
            autores=[espacos(a.get("name")) or "" for a in w.get("authors") or []],
            ano=w.get("yearPublished"),
            data_publicacao=(w.get("publishedDate") or "")[:10] or None,
            tipo=TIPO_CANONICO.get(doc.lower(), doc or None),
            idioma=idioma_iso1(lang.get("code")),
            veiculo=next((j.get("title") for j in w.get("journals") or [] if j.get("title")), None),
            issn=unicos(issn),
            editora=espacos(w.get("publisher")),
            resumo=espacos(w.get("abstract")),
            assuntos=unicos([w.get("fieldOfStudy")]),
            acesso_aberto=True,
            url_pdf=w.get("downloadUrl") or links.get("download") or None,
            raw=w,
        )
        if self.ctx.config.enriquecimento.texto_completo:
            reg.texto_completo = core_texto.texto_valido(texto)
            if not reg.texto_completo and texto and not self.ctx.credenciais.CORE_API_KEY:
                reg.avisar("texto_completo_requer_chave")
        reg.extras = {
            "x_core_provedores": unicos(p.get("name") for p in w.get("dataProviders") or []),
            "x_core_oai": unicos(w.get("oaiIds") or []),
            "x_core_data_deposito": (w.get("depositedDate") or "")[:10] or None,
        }
        return reg
