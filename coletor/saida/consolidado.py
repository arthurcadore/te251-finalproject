"""CSV consolidado (ESCOPO 9.5): uma linha por artigo, duplicatas entre bases fundidas.

Agrupamento: registros com DOI, PMID, PMCID ou ID arXiv em comum (transitivo); depois, título
normalizado (≥ 5 palavras) + ano, sem juntar grupos com DOIs diferentes. Depois da fusão, só
ficam os artigos com DOI e resumo (de qualquer uma das bases do grupo).
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from ..modelo import TIPOS, Registro, unicos
from .csv_writer import formatar

COLUNAS_CONSOLIDADO = [
    "doi", "bases", "ids_por_base", "titulo", "autores", "ano", "data_publicacao", "tipo", "idioma", "resumo",
    "palavras_chave", "assuntos", "url_pdf", "n_citacoes", "n_referencias", "referencias",
]
PRIORIDADE = ["crossref", "openalex", "pubmed", "europepmc", "semantic_scholar", "doaj", "core", "arxiv"]
PRIORIDADE_RESUMO = ["pubmed", "europepmc", "openalex", "semantic_scholar", "doaj", "core", "arxiv", "crossref"]
MIN_PALAVRAS_TITULO = 5


@dataclass
class ResumoConsolidado:
    registros_entrada: int = 0
    linhas: int = 0
    duplicatas_removidas: int = 0
    sem_doi_ou_resumo: int = 0  # artigos (já fundidos) descartados
    em_varias_bases: int = 0
    arquivo: str = "consolidado.csv"
    erro: str | None = None


def titulo_normalizado(t: str | None) -> str:
    t = unicodedata.normalize("NFKD", (t or "").casefold())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w]+", " ", t).split())


def _chaves_fortes(r: Registro) -> list[str]:
    chaves = []
    if r.doi:
        chaves.append(f"doi:{r.doi.lower()}")
    if r.pmid:
        chaves.append(f"pmid:{r.pmid}")
    if r.pmcid:
        chaves.append(f"pmcid:{r.pmcid.upper()}")
    if r.arxiv_id:
        chaves.append("arxiv:" + re.sub(r"v\d+$", "", r.arxiv_id.lower()))
    return chaves


class _Uniao:
    def __init__(self, n: int):
        self.pai = list(range(n))

    def raiz(self, i: int) -> int:
        while self.pai[i] != i:
            self.pai[i] = self.pai[self.pai[i]]
            i = self.pai[i]
        return i

    def unir(self, a: int, b: int) -> None:
        ra, rb = self.raiz(a), self.raiz(b)
        if ra != rb:
            self.pai[max(ra, rb)] = min(ra, rb)  # a raiz é sempre o registro que apareceu primeiro


def agrupar(regs: list[Registro]) -> list[list[Registro]]:
    """Grupos de registros do mesmo artigo, na ordem da primeira aparição."""
    u = _Uniao(len(regs))
    dono: dict[str, int] = {}
    for i, r in enumerate(regs):
        for k in _chaves_fortes(r):
            if k in dono:
                u.unir(dono[k], i)
            else:
                dono[k] = i

    def dois(raiz: int) -> set[str]:
        return {regs[j].doi for j in range(len(regs)) if u.raiz(j) == raiz and regs[j].doi}

    por_titulo: dict[str, int] = {}
    for i, r in enumerate(regs):
        t = titulo_normalizado(r.titulo)
        if len(t.split()) < MIN_PALAVRAS_TITULO or r.ano is None:
            continue
        k = f"{t}|{r.ano}"
        if k not in por_titulo:
            por_titulo[k] = i
            continue
        a, b = u.raiz(por_titulo[k]), u.raiz(i)
        if a != b and len(dois(a) | dois(b)) <= 1:  # nunca junta artigos com DOIs diferentes
            u.unir(a, b)

    grupos: dict[int, list[Registro]] = {}
    for i, r in enumerate(regs):
        grupos.setdefault(u.raiz(i), []).append(r)
    return [grupos[k] for k in sorted(grupos)]


def _ordenar(grupo: list[Registro], prioridade: list[str]) -> list[Registro]:
    pos = {b: i for i, b in enumerate(prioridade)}
    return sorted(grupo, key=lambda r: pos.get(r.base, len(pos)))  # sorted é estável: mantém a ordem na base


def _primeiro(grupo: list[Registro], campo: str, prioridade: list[str] = PRIORIDADE):
    for r in _ordenar(grupo, prioridade):
        v = getattr(r, campo)
        if v not in (None, "", []):
            return v
    return None


def _uniao(grupo: list[Registro], campo: str, sem_caixa: bool = False) -> list[str]:
    vistos, saida = set(), []
    for r in _ordenar(grupo, PRIORIDADE):
        for x in getattr(r, campo) or []:
            k = str(x).casefold() if sem_caixa else str(x)
            if x and k not in vistos:
                vistos.add(k)
                saida.append(x)
    return saida


def fundir(grupo: list[Registro], ordem_bases: list[str]) -> dict:
    """Uma linha do consolidado a partir dos registros de um mesmo artigo (regras da seção 9.5)."""
    bases = [b for b in ordem_bases if any(r.base == b for r in grupo)]
    bases += [b for b in unicos(r.base for r in grupo) if b not in bases]
    tipos = [r.tipo for r in _ordenar(grupo, PRIORIDADE) if r.tipo]
    cit = [r.n_citacoes for r in grupo if r.n_citacoes is not None]
    nrefs = [r.n_referencias for r in grupo if r.n_referencias is not None]
    return {
        "doi": _primeiro(grupo, "doi"),
        "bases": bases,
        "ids_por_base": unicos(f"{r.base}:{r.id_na_base}" for r in grupo),
        "titulo": _primeiro(grupo, "titulo"),
        "autores": _primeiro(grupo, "autores") or [],
        "ano": _primeiro(grupo, "ano"),
        "data_publicacao": _primeiro(grupo, "data_publicacao"),
        "tipo": next((t for t in tipos if t in TIPOS), tipos[0] if tipos else None),
        "idioma": _primeiro(grupo, "idioma"),
        "resumo": _primeiro(grupo, "resumo", PRIORIDADE_RESUMO),
        "palavras_chave": _uniao(grupo, "palavras_chave", sem_caixa=True),
        "assuntos": _uniao(grupo, "assuntos", sem_caixa=True),
        "url_pdf": _primeiro(grupo, "url_pdf"),
        "n_citacoes": max(cit) if cit else None,
        "n_referencias": max(nrefs) if nrefs else None,
        "referencias": _uniao(grupo, "referencias"),
    }


def consolidar(regs: list[Registro], ordem_bases: list[str]) -> tuple[list[dict], ResumoConsolidado]:
    grupos = agrupar(regs)
    fundidas = [fundir(g, ordem_bases) for g in grupos]
    linhas = [x for x in fundidas if x["doi"] and x["resumo"]]  # filtro depois da fusão
    resumo = ResumoConsolidado(
        registros_entrada=len(regs),
        linhas=len(linhas),
        duplicatas_removidas=len(regs) - len(fundidas),
        sem_doi_ou_resumo=len(fundidas) - len(linhas),
        em_varias_bases=sum(1 for linha in linhas if len(linha["bases"]) > 1),
    )
    return linhas, resumo


def escrever(caminho: Path, linhas: list[dict], separador: str = " | ") -> None:
    """Mesmo formato dos CSVs por base (seção 9.2)."""
    with open(caminho, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
        w.writerow(COLUNAS_CONSOLIDADO)
        for linha in linhas:
            w.writerow([formatar(linha.get(c), separador) for c in COLUNAS_CONSOLIDADO])
