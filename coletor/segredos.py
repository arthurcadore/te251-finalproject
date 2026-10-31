"""Credenciais (.env) e remoção de segredos de URLs, textos e logs."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, fields
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

PARAMS_SENSIVEIS = {"api_key", "mailto", "email"}


@dataclass(frozen=True)
class Credenciais:
    OPENALEX_API_KEY: str = ""
    CONTACT_EMAIL: str = ""
    NCBI_API_KEY: str = ""
    S2_API_KEY: str = ""
    CORE_API_KEY: str = ""
    OPENCITATIONS_TOKEN: str = ""

    @classmethod
    def do_ambiente(cls) -> "Credenciais":
        return cls(**{f.name: (os.getenv(f.name) or "").strip() for f in fields(cls)})

    def valores(self) -> list[str]:
        return [getattr(self, f.name) for f in fields(self) if getattr(self, f.name)]

    def nomes_definidos(self) -> list[str]:
        return [f.name for f in fields(self) if getattr(self, f.name)]


_SEGREDOS: set[str] = set()


def registrar(credenciais: Credenciais) -> None:
    """Registra os valores que nunca podem aparecer em saídas."""
    _SEGREDOS.update(v for v in credenciais.valores() if len(v) >= 4)


def higienizar_texto(texto: str) -> str:
    for s in _SEGREDOS:
        if s in texto:
            texto = texto.replace(s, "***")
        q = quote(s, safe="")
        if q != s and q in texto:
            texto = texto.replace(q, "***")
    return texto


def higienizar_url(url: str) -> str:
    p = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() not in PARAMS_SENSIVEIS]
    return higienizar_texto(urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), p.fragment)))


class FiltroSegredos(logging.Filter):
    """Aplicado aos handlers: troca segredos por *** em qualquer mensagem de log."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        limpa = higienizar_texto(msg)
        if limpa != msg:
            record.msg, record.args = limpa, None
        return True
