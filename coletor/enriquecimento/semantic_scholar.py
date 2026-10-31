"""Semantic Scholar: referências por `POST /graph/v1/paper/batch` (até 500 IDs por chamada) — seção 8.1."""

from __future__ import annotations

from ..http import ClienteHTTP
from ..modelo import Registro, normalizar_doi, unicos

URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
LOTE = 500
CAMPOS = "references.paperId,references.externalIds"


def referencia(ref: dict) -> str | None:
    """DOI quando houver, senão `s2:<paperId>`."""
    doi = normalizar_doi((ref.get("externalIds") or {}).get("DOI"))
    if doi:
        return doi
    return f"s2:{ref['paperId']}" if ref.get("paperId") else None


async def referencias_em_lote(regs: list[Registro], cliente: ClienteHTTP, headers: dict) -> None:
    ids = [r.id_na_base for r in regs if r.id_na_base]
    por_id = {r.id_na_base: r for r in regs}
    for i in range(0, len(ids), LOTE):
        lote = ids[i:i + LOTE]
        resp = await cliente.post(URL, params={"fields": CAMPOS}, json={"ids": lote}, headers=headers)
        for pid, item in zip(lote, resp.json()):  # mesma ordem; null para ID não encontrado
            if not item:
                continue
            refs = unicos(referencia(x) for x in item.get("references") or [])
            reg = por_id[pid]
            if refs:
                reg.referencias = refs
                reg.fonte_referencias = "nativa"
                if reg.n_referencias is None:
                    reg.n_referencias = len(refs)
