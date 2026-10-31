"""Parser da consulta (AND / OR / aspas / parênteses) e tradução para cada base (seção 6, regra 5).

Gramática: `ou := e ("OR" e)*`, `e := primario ("AND"? primario)*`, `primario := "(" ou ")" | termo`.
Operadores só em maiúsculas; termos lado a lado equivalem a AND; AND tem precedência sobre OR.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Callable, Union


class ErroConsulta(ValueError):
    pass


@dataclass(frozen=True)
class Termo:
    texto: str
    frase: bool = False  # veio entre aspas


@dataclass(frozen=True)
class Op:
    op: str  # "AND" | "OR"
    filhos: tuple["No", ...]


No = Union[Termo, Op]

_TOKEN = re.compile(r'\s*(?:(?P<aspas>"[^"]*")|(?P<abre>\()|(?P<fecha>\))|(?P<palavra>[^\s()"]+))')


def _tokens(q: str) -> list[tuple[str, str]]:
    if q.count('"') % 2:
        raise ErroConsulta("aspas não fechadas na consulta")
    toks, pos = [], 0
    q = q.strip()
    while pos < len(q):
        m = _TOKEN.match(q, pos)
        if not m or m.end() == pos:
            break
        pos = m.end()
        if m.group("aspas") is not None:
            texto = " ".join(m.group("aspas")[1:-1].split())
            if texto:
                toks.append(("frase", texto))
        elif m.group("abre"):
            toks.append(("(", "("))
        elif m.group("fecha"):
            toks.append((")", ")"))
        else:
            p = m.group("palavra")
            toks.append(("op", p) if p in ("AND", "OR") else ("palavra", p))
    return toks


def analisar(q: str) -> No:
    toks = _tokens(q)
    if not toks:
        raise ErroConsulta("consulta vazia")
    pos = 0

    def ver():
        return toks[pos] if pos < len(toks) else (None, None)

    def ou() -> No:
        nonlocal pos
        filhos = [e()]
        while ver() == ("op", "OR"):
            pos += 1
            filhos.append(e())
        return filhos[0] if len(filhos) == 1 else Op("OR", tuple(filhos))

    def e() -> No:
        nonlocal pos
        filhos = [primario()]
        while True:
            tipo, val = ver()
            if (tipo, val) == ("op", "AND"):
                pos += 1
                filhos.append(primario())
            elif tipo in ("palavra", "frase", "("):
                filhos.append(primario())
            else:
                break
        return filhos[0] if len(filhos) == 1 else Op("AND", tuple(filhos))

    def primario() -> No:
        nonlocal pos
        tipo, val = ver()
        if tipo == "(":
            pos += 1
            n = ou()
            if ver()[0] != ")":
                raise ErroConsulta("parêntese não fechado na consulta")
            pos += 1
            return n
        if tipo in ("palavra", "frase"):
            pos += 1
            return Termo(val, tipo == "frase")
        raise ErroConsulta(f"operador ou parêntese inesperado na consulta: {val!r}")

    arvore = ou()
    if pos != len(toks):
        raise ErroConsulta(f"trecho inesperado na consulta: {toks[pos][1]!r}")
    return arvore


def termos(n: No) -> list[Termo]:
    if isinstance(n, Termo):
        return [n]
    return [t for f in n.filhos for t in termos(f)]


# ---------------------------------------------------------------- renderização


def _render(n: No, fmt: Callable[[Termo], str], raiz: bool = True) -> str:
    if isinstance(n, Termo):
        return fmt(n)
    s = f" {n.op} ".join(_render(f, fmt, False) for f in n.filhos)
    return s if raiz else f"({s})"


def _aspas(t: Termo) -> str:
    return f'"{t.texto}"' if t.frase else t.texto


_LUCENE = re.compile(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)')


def _lucene(t: Termo) -> str:
    if t.frase:
        return '"' + t.texto.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return _LUCENE.sub(r"\\\1", t.texto)


def _campos(fmt_valor: Callable[[Termo], str], prefixos: list[str], sep: str = ":") -> Callable[[Termo], str]:
    def f(t: Termo) -> str:
        v = fmt_valor(t)
        partes = [f"{p}{sep}{v}" if p else v for p in prefixos]
        return partes[0] if len(partes) == 1 else "(" + " OR ".join(partes) + ")"
    return f


def texto_booleano(n: No) -> str:
    """OpenAlex: aceita AND/OR, aspas e parênteses no próprio texto."""
    return _render(n, _aspas)


def texto_simples(n: No) -> str:
    """S2 e Crossref: busca por relevância sem sintaxe; só as palavras (hífen vira espaço no S2)."""
    return " ".join(t.texto for t in termos(n))


def para_arxiv(n: No, campo: str) -> str:
    pref = {"tudo": ["all"], "titulo": ["ti"], "titulo_resumo": ["ti", "abs"]}[campo]
    return _render(n, _campos(_aspas, pref))


def para_pubmed(n: No, campo: str) -> str:
    tag = {"tudo": "", "titulo": "[ti]", "titulo_resumo": "[tiab]"}[campo]
    return _render(n, lambda t: _aspas(t) + tag)


def para_europepmc(n: No, campo: str) -> str:
    pref = {"tudo": [""], "titulo": ["TITLE"], "titulo_resumo": ["TITLE", "ABSTRACT"]}[campo]
    return _render(n, _campos(_aspas, pref))


def para_core(n: No, campo: str) -> str:
    pref = {"tudo": [""], "titulo": ["title"], "titulo_resumo": ["title", "abstract"]}[campo]
    return _render(n, _campos(_lucene, pref))


def para_doaj(n: No, campo: str) -> str:
    pref = {"tudo": [""], "titulo": ["bibjson.title"], "titulo_resumo": ["bibjson.title", "bibjson.abstract"]}[campo]
    return _render(n, _campos(_lucene, pref))


# ---------------------------------------------------------------- avaliação local (filtro de campo)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.casefold())
    return "".join(c for c in s if not unicodedata.combining(c))


def casa(n: No, texto: str) -> bool:
    """A consulta casa com o texto? Palavras e frases inteiras, sem diferenciar maiúsculas e acentos."""
    alvo = _norm(texto)

    def avaliar(x: No) -> bool:
        if isinstance(x, Termo):
            palavras = [re.escape(p) for p in _norm(x.texto).split()]
            return re.search(r"(?<!\w)" + r"\W+".join(palavras) + r"(?!\w)", alvo) is not None
        res = (avaliar(f) for f in x.filhos)
        return all(res) if x.op == "AND" else any(res)

    return avaliar(n)
