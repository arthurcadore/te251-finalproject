"""SciELO — desabilitada pelo teste prático (ESCOPO seções 4 e 15.1).

ArticleMeta não tem busca por palavra-chave (`q=` → 404); search.scielo.org proíbe robôs
(`robots.txt`: `Disallow: /`) e responde 403 com desafio anti-robô a `output=json/xml/rss`.
O adaptador fica registrado para aparecer em `--listar-bases` e no relatório como `pulada`.
"""

from __future__ import annotations

from typing import AsyncIterator

from ..config import Filtros
from ..consulta import No
from ..filtros import PlanoFiltros
from ..segredos import Credenciais
from .base import Adaptador, Pagina


class SciELO(Adaptador):
    chave = "scielo"
    nome = "SciELO"
    desabilitado = ("sem busca por palavra-chave via API: ArticleMeta só lista identificadores; "
                    "search.scielo.org proíbe robôs (robots.txt) e responde 403 a saídas JSON/XML/RSS")

    @classmethod
    def limites_padrao(cls, cred: Credenciais) -> tuple[float, int]:
        return 1, 1

    def suporta(self, filtros: Filtros) -> PlanoFiltros:
        return PlanoFiltros(incompativel=self.desabilitado)

    def traduzir(self, arvore: No, plano: PlanoFiltros) -> str:
        return ""

    async def paginas(self, arvore: No, plano: PlanoFiltros, tamanho: int) -> AsyncIterator[Pagina]:
        raise RuntimeError(self.desabilitado)
        yield  # pragma: no cover  (torna a função um gerador assíncrono)
