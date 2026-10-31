"""Gravador CSV (seções 9.2 e 9.3): RFC 4180, todos os campos entre aspas, UTF-8 com BOM, em fluxo."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from ..modelo import COLUNAS, Registro
from ..segredos import higienizar_texto


def cabecalho(extras: list[str], raw_json: bool) -> list[str]:
    return COLUNAS + list(extras) + (["raw_json"] if raw_json else [])


def _texto(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")


def formatar(valor: Any, separador: str = " | ") -> str:
    """Valor → célula: vazio para None, true/false, listas com separador, `AAAA:n` em ordem decrescente."""
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, dict):  # citacoes_por_ano
        return separador.join(f"{a}:{n}" for a, n in sorted(valor.items(), reverse=True))
    if isinstance(valor, (list, tuple)):
        itens = [_texto(formatar(v, separador)).replace("|", "/") for v in valor]
        if not any(i.strip() for i in itens):  # ex.: autores_orcid sem nenhum ORCID
            return ""
        return separador.join(itens)
    if isinstance(valor, float):
        return repr(valor) if valor == valor else ""
    return _texto(str(valor))


def linha(reg: Registro, extras: list[str], raw_json: bool, separador: str) -> list[str]:
    valores = [formatar(getattr(reg, c), separador) for c in COLUNAS]
    valores += [formatar(reg.extras.get(c), separador) for c in extras]
    if raw_json:
        bruto = json.dumps(reg.raw, ensure_ascii=False, separators=(",", ":")) if reg.raw is not None else ""
        valores.append(higienizar_texto(_texto(bruto)))
    return valores


class EscritorCSV:
    """Abre o arquivo e grava o cabeçalho na criação: toda base gera ao menos o cabeçalho."""

    def __init__(self, caminho: Path, extras: list[str], raw_json: bool = True, separador: str = " | "):
        self.caminho = Path(caminho)
        self.extras = list(extras)
        self.raw_json = raw_json
        self.separador = separador
        self.n = 0
        self._arq = open(self.caminho, "w", encoding="utf-8-sig", newline="")
        self._w = csv.writer(self._arq, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
        self._w.writerow(cabecalho(self.extras, raw_json))
        self._arq.flush()

    def escrever(self, registros: Iterable[Registro]) -> int:
        n = 0
        for r in registros:
            self._w.writerow(linha(r, self.extras, self.raw_json, self.separador))
            n += 1
        self._arq.flush()
        self.n += n
        return n

    def fechar(self) -> None:
        if not self._arq.closed:
            self._arq.close()
