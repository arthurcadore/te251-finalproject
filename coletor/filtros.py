"""Filtros (seção 6): plano nativo / local / ignorado / incompatível por base, e aplicação local.

Modos declarados por cada adaptador para período, idiomas e somente_oa:
  NATIVO   — enviado à API
  LOCAL    — aplicado ao registro normalizado depois da coleta
  SEM_DADO — a base não tem o dado: filtro ignorado com aviso no relatório (regra 3)
  TODOS    — todo registro da base já atende (ex.: só acesso aberto): nada a fazer
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .config import Filtros
from .consulta import No, casa
from .modelo import Registro

NATIVO, LOCAL, SEM_DADO, TODOS = "nativo", "local", "sem_dado", "todos"


@dataclass
class PlanoFiltros:
    modos: dict[str, str] = field(default_factory=dict)  # filtro → NATIVO | LOCAL
    ignorados: list[str] = field(default_factory=list)   # descrições para o relatório
    atendidos: list[str] = field(default_factory=list)   # filtros que a base já satisfaz por natureza
    incompativel: str | None = None

    def nativo(self, filtro: str) -> bool:
        return self.modos.get(filtro) == NATIVO

    @property
    def locais(self) -> list[str]:
        return [f for f, m in self.modos.items() if m == LOCAL]

    @property
    def nativos(self) -> list[str]:
        return [f for f, m in self.modos.items() if m == NATIVO]


def planejar(
    f: Filtros,
    *,
    nome_base: str,
    periodo: str,
    idiomas: str,
    somente_oa: str,
    tipos_unicos: frozenset[str] | None = None,
    tipos_nativos: Callable[[list[str]], bool] = lambda tipos: False,
    campos_nativos: frozenset[str] = frozenset({"tudo"}),
) -> PlanoFiltros:
    p = PlanoFiltros()

    def modo(filtro: str, m: str, descricao: str) -> None:
        if m in (NATIVO, LOCAL):
            p.modos[filtro] = m
        elif m == SEM_DADO:
            p.ignorados.append(f"{descricao}: {nome_base} não informa esse dado")
        elif m == TODOS:
            p.atendidos.append(descricao)

    if f.tem_periodo:
        modo("periodo", periodo, "período")
    if f.idiomas:
        modo("idiomas", idiomas, "idiomas")
    if f.somente_oa:
        modo("somente_oa", somente_oa, "somente_oa (todos os registros são de acesso aberto)" if somente_oa == TODOS else "somente_oa")
    if f.tipos:
        if tipos_unicos is not None:
            if not set(f.tipos) & tipos_unicos:
                p.incompativel = (f"tipos {', '.join(f.tipos)} incompatíveis: {nome_base} só tem "
                                  f"{', '.join(sorted(tipos_unicos))}")
            else:
                p.atendidos.append(f"tipos (a base só tem {', '.join(sorted(tipos_unicos))})")
        else:
            p.modos["tipos"] = NATIVO if tipos_nativos(f.tipos) else LOCAL
    if f.campo_busca != "tudo":
        p.modos["campo_busca"] = NATIVO if f.campo_busca in campos_nativos else LOCAL
    return p


def aplicar_locais(
    reg: Registro,
    plano: PlanoFiltros,
    f: Filtros,
    arvore: No,
    idiomas_do_registro: Callable[[Registro], list[str]] | None = None,
) -> bool:
    """True = mantém. Registro sem o dado é mantido com aviso `<filtro>_nao_verificado` (regra 2)."""
    for filtro in plano.locais:
        if filtro == "periodo":
            if reg.ano is None:
                reg.avisar("periodo_nao_verificado")
            elif (f.ano_de is not None and reg.ano < f.ano_de) or (f.ano_ate is not None and reg.ano > f.ano_ate):
                return False
        elif filtro == "tipos":
            if not reg.tipo:
                reg.avisar("tipo_nao_verificado")
            elif reg.tipo not in f.tipos:
                return False
        elif filtro == "idiomas":
            idiomas = idiomas_do_registro(reg) if idiomas_do_registro else ([reg.idioma] if reg.idioma else [])
            if not idiomas:
                reg.avisar("idioma_nao_verificado")
            elif not set(idiomas) & set(f.idiomas):
                return False
        elif filtro == "somente_oa":
            if reg.acesso_aberto is None:
                reg.avisar("oa_nao_verificado")
            elif not reg.acesso_aberto:
                return False
        elif filtro == "campo_busca":
            texto = reg.titulo or ""
            if f.campo_busca == "titulo_resumo":
                texto += " " + (reg.resumo or "")
            if not texto.strip():
                reg.avisar("campo_busca_nao_verificado")
            elif not casa(arvore, texto):
                return False
    return True
