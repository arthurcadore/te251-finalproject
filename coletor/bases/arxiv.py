"""arXiv — GET https://export.arxiv.org/api/query, Atom XML (mapeamento a partir de tests/fixtures/arxiv/)."""

from __future__ import annotations

import re
from datetime import date
from typing import AsyncIterator

from lxml import etree

from ..config import Enriquecimento, Filtros
from ..consulta import No, para_arxiv
from ..enriquecimento import opencitations
from ..filtros import NATIVO, SEM_DADO, TODOS, PlanoFiltros, planejar
from ..modelo import Registro, espacos, normalizar_doi, unicos
from ..segredos import Credenciais
from .base import Adaptador, EncerrarBase, Pagina

URL = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom",
      "opensearch": "http://a9.com/-/spec/opensearch/1.1/"}
_ID = re.compile(r"arxiv\.org/abs/(?P<id>.+?)(?P<versao>v\d+)?$")


def _texto(el, caminho: str) -> str | None:
    r = el.xpath(caminho, namespaces=NS)
    return espacos(r[0]) if r else None


class ArXiv(Adaptador):
    chave = "arxiv"
    nome = "arXiv"
    backoff = (6, 12, 24, 48, 96)  # até ~3 min no total (seção 7, regra 1)
    colunas_extras = ["x_arxiv_comentario", "x_arxiv_journal_ref", "x_arxiv_categoria_primaria",
                      "x_arxiv_atualizado_em", "x_arxiv_versao"]

    @classmethod
    def limites_padrao(cls, cred: Credenciais) -> tuple[float, int]:
        return 1 / 3, 1

    def suporta(self, filtros: Filtros) -> PlanoFiltros:
        return planejar(filtros, nome_base=self.nome, periodo=NATIVO, idiomas=SEM_DADO, somente_oa=TODOS,
                        tipos_unicos=frozenset({"preprint"}),
                        campos_nativos=frozenset({"tudo", "titulo", "titulo_resumo"}))

    def traduzir(self, arvore: No, plano: PlanoFiltros) -> str:
        f = self.ctx.config.filtros
        q = para_arxiv(arvore, f.campo_busca if plano.nativo("campo_busca") else "tudo")
        if plano.nativo("periodo"):
            de = f.ano_de if f.ano_de is not None else 1991
            ate = f.ano_ate if f.ano_ate is not None else date.today().year
            q = f"({q}) AND submittedDate:[{de}01010000 TO {ate}12312359]"
        return q

    async def paginas(self, arvore: No, plano: PlanoFiltros, tamanho: int) -> AsyncIterator[Pagina]:
        q = self.traduzir(arvore, plano)
        inicio = 0
        while True:
            resp = await self.ctx.cliente.get(URL, params={"search_query": q, "start": inicio,
                                                           "max_results": tamanho})
            raiz = etree.fromstring(resp.texto.encode("utf-8"))
            entradas = raiz.xpath("a:entry", namespaces=NS)
            # erro de sintaxe vem como HTTP 200 com uma entrada cujo id aponta para /api/errors
            if entradas and "/api/errors" in (_texto(entradas[0], "a:id/text()") or ""):
                raise EncerrarBase(f"arXiv rejeitou a consulta: {_texto(entradas[0], 'a:summary/text()')}", "falhou")
            total_txt = _texto(raiz, "opensearch:totalResults/text()")
            total = int(total_txt) if total_txt and total_txt.isdigit() else None
            inicio += len(entradas)
            ultima = not entradas or (total is not None and inicio >= total)
            yield Pagina([self.normalizar(e) for e in entradas], total, ultima=ultima)
            if ultima:
                return

    async def enriquecer(self, registros: list[Registro], opcoes: Enriquecimento) -> list[Registro]:
        """Referências e contagem de citações pelo OpenCitations, a partir do DOI (seção 8.1)."""
        if opcoes.referencias:
            await opencitations.enriquecer(registros, self.ctx.opencitations, self.log)
        return registros

    def normalizar(self, e) -> Registro:
        url_id = _texto(e, "a:id/text()") or ""
        m = _ID.search(url_id)
        arxiv_id = m.group("id") if m else url_id
        versao = (m.group("versao") if m else None) or None
        publicado = _texto(e, "a:published/text()")
        autores = e.xpath("a:author", namespaces=NS)
        reg = Registro(
            base=self.chave,
            id_na_base=arxiv_id,
            doi=normalizar_doi(_texto(e, "arxiv:doi/text()")),
            arxiv_id=arxiv_id,
            url_pagina=_texto(e, "a:link[@rel='alternate']/@href") or url_id,
            titulo=_texto(e, "a:title/text()"),
            autores=[_texto(a, "a:name/text()") or "" for a in autores],
            afiliacoes=unicos(espacos(x) for x in e.xpath("a:author/arxiv:affiliation/text()", namespaces=NS)),
            ano=int(publicado[:4]) if publicado else None,
            data_publicacao=publicado[:10] if publicado else None,
            tipo="preprint",
            veiculo="arXiv",
            resumo=_texto(e, "a:summary/text()"),
            assuntos=unicos(e.xpath("a:category/@term", namespaces=NS)),
            acesso_aberto=True,
            url_pdf=_texto(e, "a:link[@title='pdf']/@href"),
            raw={"atom_entry": etree.tostring(e, encoding="unicode")},
        )
        reg.extras = {
            "x_arxiv_comentario": _texto(e, "arxiv:comment/text()"),
            "x_arxiv_journal_ref": _texto(e, "arxiv:journal_ref/text()"),
            "x_arxiv_categoria_primaria": _texto(e, "arxiv:primary_category/@term"),
            "x_arxiv_atualizado_em": _texto(e, "a:updated/text()"),
            "x_arxiv_versao": versao,
        }
        return reg
