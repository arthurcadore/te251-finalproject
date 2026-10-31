"""Registro normalizado: o esquema de colunas da seção 9.3 do ESCOPO.md."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

COLUNAS = [
    "base", "id_na_base", "doi", "pmid", "pmcid", "arxiv_id", "url_pagina", "consulta", "coletado_em",
    "titulo", "autores", "autores_orcid", "afiliacoes", "ano", "data_publicacao", "tipo", "idioma",
    "veiculo", "issn", "editora", "volume", "numero", "paginas", "resumo", "tldr", "palavras_chave",
    "assuntos", "texto_completo", "acesso_aberto", "status_oa", "licenca", "url_pdf", "n_citacoes",
    "n_citacoes_influentes", "citacoes_por_ano", "percentil_citacoes", "fwci", "n_referencias",
    "referencias", "relacionados", "fonte_referencias", "fonte_citacoes", "financiadores", "retratado",
    "avisos",
]

# Valores canônicos (seção 6)
TIPOS = ("artigo", "revisao", "preprint", "conferencia", "livro_capitulo")
CAMPOS_BUSCA = ("tudo", "titulo", "titulo_resumo")


@dataclass
class Registro:
    base: str
    id_na_base: str
    consulta: str = ""
    coletado_em: str = ""
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    arxiv_id: str | None = None
    url_pagina: str | None = None
    titulo: str | None = None
    autores: list[str] = field(default_factory=list)
    autores_orcid: list[str] = field(default_factory=list)  # alinhado a `autores`; "" quando não houver
    afiliacoes: list[str] = field(default_factory=list)
    ano: int | None = None
    data_publicacao: str | None = None
    tipo: str | None = None
    idioma: str | None = None
    veiculo: str | None = None
    issn: list[str] = field(default_factory=list)
    editora: str | None = None
    volume: str | None = None
    numero: str | None = None
    paginas: str | None = None
    resumo: str | None = None
    tldr: str | None = None
    palavras_chave: list[str] = field(default_factory=list)
    assuntos: list[str] = field(default_factory=list)
    texto_completo: str | None = None
    acesso_aberto: bool | None = None
    status_oa: str | None = None
    licenca: str | None = None
    url_pdf: str | None = None
    n_citacoes: int | None = None
    n_citacoes_influentes: int | None = None
    citacoes_por_ano: dict[int, int] = field(default_factory=dict)
    percentil_citacoes: float | None = None
    fwci: float | None = None
    n_referencias: int | None = None
    referencias: list[str] = field(default_factory=list)
    relacionados: list[str] = field(default_factory=list)
    fonte_referencias: str = "nenhuma"
    fonte_citacoes: str = "nenhuma"
    financiadores: list[str] = field(default_factory=list)
    retratado: bool | None = None
    avisos: list[str] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)  # colunas x_<base>_*
    raw: Any = None  # resposta original do registro (dict ou {"xml": ...})

    def avisar(self, codigo: str) -> None:
        if codigo not in self.avisos:
            self.avisos.append(codigo)


def normalizar_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = doi.strip().lower()
    for prefixo in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/", "doi:"):
        if d.startswith(prefixo):
            d = d[len(prefixo):]
    return d or None


def unicos(itens) -> list[str]:
    """Remove vazios e repetidos mantendo a ordem."""
    vistos: set[str] = set()
    saida = []
    for i in itens:
        if i is None:
            continue
        s = str(i).strip()
        if s and s not in vistos:
            vistos.add(s)
            saida.append(s)
    return saida


def espacos(texto: str | None) -> str | None:
    """Colapsa espaços e quebras de linha (títulos, resumos de uma linha)."""
    if texto is None:
        return None
    t = " ".join(texto.split())
    return t or None


@dataclass
class EstatisticasBase:
    """Linha do relatório da execução (seção 9.4)."""

    base: str
    status: str = "ok"  # ok · parcial · falhou · pulada
    motivo: str = ""
    pedidos: int = 0
    gravados: int = 0
    total_api: int | None = None
    paginas: int = 0
    chamadas_http: int = 0
    chamadas_cache: int = 0
    n_429: int = 0
    taxa_inicial: float | None = None
    taxa_final: float | None = None
    descartados_filtro_local: int = 0
    duplicados: int = 0
    teto_filtro_local_atingido: bool = False
    consulta_traduzida: str = ""
    filtros_nativos: list[str] = field(default_factory=list)
    filtros_locais: list[str] = field(default_factory=list)
    filtros_ignorados: list[str] = field(default_factory=list)
    filtros_atendidos: list[str] = field(default_factory=list)
    enriquecidos: int = 0
    avisos: list[str] = field(default_factory=list)
    duracao_s: float = 0.0
    arquivo_csv: str = ""
