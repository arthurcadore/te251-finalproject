"""CORE: texto completo por `GET /v3/works/{id}` quando a busca não o trouxe (seção 8.1).

Só com `CORE_API_KEY`: sem chave a API devolve um texto fixo de indisponibilidade (ESCOPO 15.2).
"""

from __future__ import annotations

from ..http import ClienteHTTP
from ..modelo import Registro

URL = "https://api.core.ac.uk/v3/works/"
SEM_TEXTO = "Not available for public API users."


def texto_valido(texto: str | None) -> str | None:
    if not texto or texto.strip() == SEM_TEXTO:
        return None
    return texto.replace("\r\n", "\n").replace("\r", "\n").strip() or None


async def texto_completo(reg: Registro, cliente: ClienteHTTP, headers: dict) -> None:
    if reg.texto_completo or not reg.id_na_base:
        return
    w = (await cliente.get(URL + reg.id_na_base, headers=headers)).json()
    texto = texto_valido(w.get("fullText"))
    if texto:
        reg.texto_completo = texto
    else:
        reg.avisar("texto_completo_indisponivel")
