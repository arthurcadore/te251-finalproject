"""Classe abstrata dos adaptadores e laço comum de paginação (seção 8, passos 2–6)."""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator, ClassVar

from ..config import Config, Enriquecimento, Filtros
from ..consulta import No
from ..enriquecimento.opencitations import OpenCitations
from ..filtros import PlanoFiltros, aplicar_locais
from ..http import ClienteHTTP
from ..limitador import BACKOFF_PADRAO
from ..modelo import EstatisticasBase, Registro
from ..segredos import Credenciais


class EncerrarBase(Exception):
    """Encerra a coleta da base mantendo o que já foi gravado (ex.: orçamento esgotado)."""

    def __init__(self, motivo: str, status: str | None = None):
        super().__init__(motivo)
        self.motivo = motivo
        self.status = status  # None → "parcial" se gravou algo, senão "falhou"


@dataclass
class Pagina:
    registros: list[Registro]
    total: int | None = None
    ultima: bool = False


@dataclass
class Contexto:
    config: Config
    credenciais: Credenciais
    cliente: ClienteHTTP
    estat: EstatisticasBase
    log: logging.Logger
    opencitations: OpenCitations | None = None  # compartilhado entre as bases
    coletado_em: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))


class Adaptador(ABC):
    chave: ClassVar[str]
    nome: ClassVar[str]
    credencial_obrigatoria: ClassVar[str | None] = None
    desabilitado: ClassVar[str | None] = None  # motivo, quando a base não pode ser usada
    tamanho_pagina: ClassVar[int] = 100
    backoff: ClassVar[tuple[float, ...]] = BACKOFF_PADRAO
    colunas_extras: ClassVar[list[str]] = []  # x_<base>_*, nesta ordem no CSV

    def __init__(self, ctx: Contexto):
        self.ctx = ctx
        self.log = ctx.log

    @classmethod
    @abstractmethod
    def limites_padrao(cls, cred: Credenciais) -> tuple[float, int]:
        """(taxa inicial em req/s, concorrência) — seção 7."""

    @abstractmethod
    def suporta(self, filtros: Filtros) -> PlanoFiltros:
        """Plano de filtros: nativo / local / ignorado / incompatível."""

    @abstractmethod
    def traduzir(self, arvore: No, plano: PlanoFiltros) -> str:
        """Consulta na sintaxe da base (para o log e o relatório)."""

    @abstractmethod
    def paginas(self, arvore: No, plano: PlanoFiltros, tamanho: int) -> AsyncIterator[Pagina]:
        """Páginas de resultados já normalizados, na ordem padrão da API."""

    async def enriquecer(self, registros: list[Registro], opcoes: Enriquecimento) -> list[Registro]:
        """Seção 8.1. Padrão: nada além do que a busca já trouxe."""
        return registros

    async def aplicar_enriquecimento(self, regs: list[Registro], opcoes: Enriquecimento) -> list[Registro]:
        """Chama `enriquecer` e conta os artigos que ganharam algo. Falha não descarta artigos."""
        antes = [_assinatura(r) for r in regs]
        try:
            regs = await self.enriquecer(regs, opcoes)
        except Exception as e:  # noqa: BLE001 — o artigo é gravado mesmo assim
            self.log.warning("enriquecimento falhou para o lote: %s: %s", type(e).__name__, e)
            for r in regs:
                r.avisar("enriquecimento_falhou")
            return regs
        self.ctx.estat.enriquecidos += sum(1 for a, r in zip(antes, regs) if a != _assinatura(r))
        return regs

    async def com_aviso(self, reg: Registro, coro) -> None:
        """Executa uma etapa de enriquecimento de um artigo; em caso de erro, só marca o aviso."""
        try:
            await coro
        except Exception as e:  # noqa: BLE001
            reg.avisar("enriquecimento_falhou")
            self.log.debug("enriquecimento de %s falhou: %s: %s", reg.id_na_base, type(e).__name__, e)

    def idiomas_do_registro(self, reg: Registro) -> list[str]:
        """Idiomas usados pelo filtro local (DOAJ, por exemplo, tem vários por periódico)."""
        return [reg.idioma] if reg.idioma else []

    # ------------------------------------------------------------ laço comum

    async def buscar(self, arvore: No, plano: PlanoFiltros, limite: int) -> AsyncIterator[list[Registro]]:
        """Pagina até `limite` registros aprovados; com filtro local, para no teto de páginas extras.

        Entrega um lote por página (escrita do CSV em fluxo). Remove duplicatas dentro da base
        por `id_na_base` e depois por `doi`.
        """
        cfg, est = self.ctx.config, self.ctx.estat
        tamanho = self.tamanho_pagina if plano.locais else min(limite, self.tamanho_pagina)
        teto = None
        if plano.locais:
            teto = math.ceil(limite / tamanho) + cfg.execucao.max_paginas_extras_filtro_local
        ids: set[str] = set()
        dois: set[str] = set()
        aceitos = 0
        async for pag in self.paginas(arvore, plano, tamanho):
            est.paginas += 1
            if pag.total is not None:
                est.total_api = pag.total
            lote = []
            for reg in pag.registros:
                if reg.id_na_base in ids or (reg.doi and reg.doi in dois):
                    est.duplicados += 1
                    continue
                ids.add(reg.id_na_base)
                if reg.doi:
                    dois.add(reg.doi)
                if not aplicar_locais(reg, plano, cfg.filtros, arvore, self.idiomas_do_registro):
                    est.descartados_filtro_local += 1
                    continue
                reg.consulta = cfg.query
                reg.coletado_em = self.ctx.coletado_em
                lote.append(reg)
                aceitos += 1
                if aceitos >= limite:
                    break
            self.log.info("página %d: %d registros recebidos, %d aprovados (acumulado %d de %d)",
                          est.paginas, len(pag.registros), len(lote), aceitos, limite)
            if lote:
                yield lote
            if aceitos >= limite or pag.ultima or not pag.registros:
                return
            if teto is not None and est.paginas >= teto:
                est.teto_filtro_local_atingido = True
                self.log.warning("teto de páginas do filtro local atingido (%d páginas): %d de %d registros",
                                 teto, aceitos, limite)
                return


def _assinatura(r: Registro) -> tuple:
    return (tuple(r.referencias), tuple(r.relacionados), r.n_citacoes, r.n_referencias, r.texto_completo)
