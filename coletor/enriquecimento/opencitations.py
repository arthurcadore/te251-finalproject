"""OpenCitations Index v2 — referências e contagem de citações por `doi:` ou `pmid:` (seção 8.1).

Um único cliente compartilhado entre as bases, com limitador próprio (~180 req/min por IP).
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote

from ..http import ClienteHTTP, ErroHTTP
from ..limitador import TentativasEsgotadas
from ..modelo import Registro, normalizar_doi, unicos

RAIZ = "https://api.opencitations.net/index/v2/"


class Indisponivel(Exception):
    pass


def id_citado(cited: str) -> str | None:
    """'omid:br/1 doi:10.1/x openalex:W1 pmid:2' → '10.1/x' (DOI), senão 'pmid:2', senão o 1º ID."""
    ids = cited.split()
    for i in ids:
        if i.startswith("doi:"):
            return normalizar_doi(i[4:])
    for i in ids:
        if i.startswith("pmid:"):
            return i
    return ids[0] if ids else None


class OpenCitations:
    def __init__(self, cliente: ClienteHTTP, token: str = ""):
        self.cliente = cliente
        self.headers = {"authorization": token} if token else {}
        self.log = cliente.log
        self.indisponivel: str | None = None  # motivo, depois que as retentativas se esgotam

    async def _get(self, caminho: str):
        if self.indisponivel:
            raise Indisponivel(self.indisponivel)
        try:
            return (await self.cliente.get(RAIZ + quote(caminho, safe=":/()"), headers=self.headers)).json()
        except TentativasEsgotadas as e:
            self.indisponivel = f"OpenCitations indisponível ({e.ultimo})"
            self.log.error("%s: enriquecimento via OpenCitations interrompido", self.indisponivel)
            raise Indisponivel(self.indisponivel) from e

    async def referencias(self, ident: str) -> list[str]:
        dados = await self._get(f"references/{ident}")
        return unicos(id_citado(x.get("cited", "")) for x in dados or [])

    async def citacoes(self, ident: str) -> int | None:
        dados = await self._get(f"citation-count/{ident}")
        try:
            return int(dados[0]["count"])
        except (IndexError, KeyError, TypeError, ValueError):
            return None


def identificador(reg: Registro, usar_pmid: bool) -> str | None:
    if reg.doi:
        return f"doi:{reg.doi}"
    if usar_pmid and reg.pmid:
        return f"pmid:{reg.pmid}"
    return None


async def enriquecer(
    regs: list[Registro],
    oc: OpenCitations | None,
    log: logging.Logger,
    *,
    referencias: bool = True,
    citacoes: bool = True,
    usar_pmid: bool = False,
) -> None:
    """Preenche referências (se vazias) e contagem de citações (se ausente). Sem ID: nada a fazer."""
    if oc is None:
        return

    async def um(reg: Registro) -> None:
        ident = identificador(reg, usar_pmid)
        if not ident:
            return
        try:
            if referencias and not reg.referencias:
                refs = await oc.referencias(ident)
                if refs:
                    reg.referencias = refs
                    reg.n_referencias = len(refs)
                    reg.fonte_referencias = "opencitations"
            if citacoes and reg.n_citacoes is None:
                n = await oc.citacoes(ident)
                if n is not None:
                    reg.n_citacoes = n
                    reg.fonte_citacoes = "opencitations"
        except (Indisponivel, ErroHTTP) as e:
            reg.avisar("enriquecimento_falhou")
            log.debug("OpenCitations falhou para %s: %s", ident, e)

    await asyncio.gather(*(um(r) for r in regs))
