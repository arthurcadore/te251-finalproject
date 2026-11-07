"""Modelo da configuração (seção 5.1). Chaves seguem exatamente o ESCOPO.md."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .consulta import ErroConsulta, analisar
from .modelo import CAMPOS_BUSCA, TIPOS

CHAVES_BASES = ("openalex", "semantic_scholar", "crossref", "arxiv", "pubmed", "europepmc", "core", "doaj", "scielo")


class ErroConfig(Exception):
    """Erro de configuração: código de saída 2."""


class _Estrito(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Filtros(_Estrito):
    ano_de: int | None = None
    ano_ate: int | None = None
    tipos: list[Literal[TIPOS]] = Field(default_factory=list)  # type: ignore[valid-type]
    idiomas: list[str] = Field(default_factory=list)
    somente_oa: bool = False
    campo_busca: Literal[CAMPOS_BUSCA] = "tudo"  # type: ignore[valid-type]

    @field_validator("idiomas")
    @classmethod
    def _iso_639_1(cls, v: list[str]) -> list[str]:
        saida = []
        for i in v:
            i = str(i).strip().lower()
            if not re.fullmatch(r"[a-z]{2}", i):
                raise ValueError(f"idioma {i!r} não é um código ISO 639-1 (duas letras, ex.: en, pt)")
            saida.append(i)
        return list(dict.fromkeys(saida))

    @model_validator(mode="after")
    def _periodo(self) -> "Filtros":
        if self.ano_de is not None and self.ano_ate is not None and self.ano_de > self.ano_ate:
            raise ValueError("ano_de maior que ano_ate")
        self.tipos = list(dict.fromkeys(self.tipos))
        return self

    @property
    def tem_periodo(self) -> bool:
        return self.ano_de is not None or self.ano_ate is not None


class Enriquecimento(_Estrito):
    referencias: bool = True
    resolver_ids_para_doi: bool = True
    texto_completo: bool = True


class Saida(_Estrito):
    diretorio: str = "saida"
    raw_json: bool = True
    separador_lista: str = " | "


class Execucao(_Estrito):
    max_paginas_extras_filtro_local: int = Field(10, ge=0)
    cache_http: bool = True
    timeout_s: float = Field(30, gt=0)
    # Tempo máximo da coleta (todas as bases em paralelo). Ao estourar, cada base para de buscar, fica com
    # status "parcial" e o consolidado é gerado com o que já foi gravado. None = sem limite.
    timeout_pesquisa_s: float | None = Field(None, gt=0)
    log_nivel: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class LimiteBase(_Estrito):
    taxa_rps: float | None = Field(None, gt=0)
    concorrencia: int | None = Field(None, ge=1)


class Config(_Estrito):
    query: str
    bases_ativas: list[str] = Field(default_factory=lambda: [b for b in CHAVES_BASES if b != "scielo"])
    max_artigos_por_base: int = Field(100, ge=1)
    filtros: Filtros = Field(default_factory=Filtros)
    enriquecimento: Enriquecimento = Field(default_factory=Enriquecimento)
    saida: Saida = Field(default_factory=Saida)
    execucao: Execucao = Field(default_factory=Execucao)
    limites: dict[str, LimiteBase] = Field(default_factory=dict)

    @field_validator("query")
    @classmethod
    def _query(cls, v: str) -> str:
        try:
            analisar(v)
        except ErroConsulta as e:
            raise ValueError(str(e)) from e
        return v.strip()

    @field_validator("bases_ativas")
    @classmethod
    def _bases(cls, v: list[str]) -> list[str]:
        desconhecidas = [b for b in v if b not in CHAVES_BASES]
        if desconhecidas:
            raise ValueError(f"bases desconhecidas: {', '.join(desconhecidas)} (válidas: {', '.join(CHAVES_BASES)})")
        return list(dict.fromkeys(v))

    @field_validator("limites")
    @classmethod
    def _limites(cls, v: dict) -> dict:
        desconhecidas = [b for b in v if b not in CHAVES_BASES + ("opencitations",)]
        if desconhecidas:
            raise ValueError(f"limites para bases desconhecidas: {', '.join(desconhecidas)}")
        return v


def _mensagem(e: ValidationError) -> str:
    linhas = []
    for err in e.errors():
        local = ".".join(str(x) for x in err["loc"]) or "config"
        linhas.append(f"  {local}: {err['msg']}")
    return "configuração inválida:\n" + "\n".join(linhas)


def carregar(caminho: str | Path | None, sobrescritas: dict | None = None) -> Config:
    """Lê o YAML (se houver), aplica as sobrescritas da CLI e valida."""
    dados: dict = {}
    if caminho is not None:
        p = Path(caminho)
        if not p.exists():
            raise ErroConfig(f"arquivo de configuração não encontrado: {p}")
        try:
            dados = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            raise ErroConfig(f"YAML inválido em {p}: {e}") from e
        if not isinstance(dados, dict):
            raise ErroConfig(f"{p}: o conteúdo deve ser um mapeamento YAML")
        # seção presente mas vazia no YAML (ex.: "limites:" só com comentários) = valores padrão
        for secao in ("filtros", "enriquecimento", "saida", "execucao", "limites"):
            if secao in dados and dados[secao] is None:
                del dados[secao]
    for chave, valor in (sobrescritas or {}).items():
        alvo = dados
        *caminho_chave, ultima = chave.split(".")
        for k in caminho_chave:
            if not isinstance(alvo.get(k), dict):
                alvo[k] = {}
            alvo = alvo[k]
        alvo[ultima] = valor
    try:
        return Config.model_validate(dados)
    except ValidationError as e:
        raise ErroConfig(_mensagem(e)) from e
