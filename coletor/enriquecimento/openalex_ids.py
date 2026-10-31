"""OpenAlex: converte IDs W de `referenced_works`/`related_works` em DOI por lote (seção 8.1).

`GET /works?filter=openalex_id:W1|W2…&select=id,doi`, até 100 IDs por chamada. ID sem DOI continua
como `openalex:W…`.
"""

from __future__ import annotations

import logging

from ..http import ClienteHTTP, ErroHTTP
from ..modelo import Registro, normalizar_doi

URL = "https://api.openalex.org/works"
LOTE = 100
PREFIXO = "openalex:"


class OrcamentoEsgotado(Exception):
    pass


async def resolver(
    regs: list[Registro],
    cliente: ClienteHTTP,
    api_key: str,
    cache: dict[str, str | None],
    log: logging.Logger,
    orcamento_esgotado,
) -> None:
    """Atualiza `referencias` e `relacionados` no lugar. `cache` (W → DOI|None) vale para a execução toda."""
    pendentes = []
    for r in regs:
        for x in r.referencias + r.relacionados:
            if x.startswith(PREFIXO):
                w = x[len(PREFIXO):]
                if w not in cache and w not in pendentes:
                    pendentes.append(w)
    for i in range(0, len(pendentes), LOTE):
        lote = pendentes[i:i + LOTE]
        try:
            resp = await cliente.get(URL, params={"filter": "openalex_id:" + "|".join(lote), "select": "id,doi",
                                                  "per_page": LOTE, "api_key": api_key},
                                     parar=lambda r: orcamento_esgotado(r.headers))  # 429 sem orçamento: não repetir
        except ErroHTTP as e:
            if e.status == 429:
                raise OrcamentoEsgotado("orçamento diário do OpenAlex esgotado na conversão de IDs") from e
            raise
        for w in lote:
            cache.setdefault(w, None)
        for item in resp.json().get("results") or []:
            w = (item.get("id") or "").rsplit("/", 1)[-1]
            cache[w] = normalizar_doi(item.get("doi"))
        if not resp.do_cache and orcamento_esgotado(resp.headers):
            raise OrcamentoEsgotado("orçamento diário do OpenAlex esgotado na conversão de IDs")
    log.debug("IDs OpenAlex convertidos: %d novos, %d no cache", len(pendentes), len(cache))

    def trocar(lista: list[str]) -> list[str]:
        saida, vistos = [], set()
        for x in lista:
            novo = cache.get(x[len(PREFIXO):]) if x.startswith(PREFIXO) else None
            v = novo or x
            if v not in vistos:
                vistos.add(v)
                saida.append(v)
        return saida

    for r in regs:
        r.referencias = trocar(r.referencias)
        r.relacionados = trocar(r.relacionados)
