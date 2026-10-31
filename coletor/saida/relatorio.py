"""Relatório da execução (seção 9.4): relatorio.md e relatorio.json com o mesmo conteúdo."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ..modelo import EstatisticasBase
from ..segredos import higienizar_texto


def _n(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.3g}"
    return str(v)


def _lista(itens: list[str]) -> str:
    return "; ".join(itens) if itens else "—"


def montar(cabecalho: dict, bases: list[EstatisticasBase]) -> dict:
    return {**cabecalho, "bases": [asdict(b) for b in bases]}


def escrever(diretorio: Path, dados: dict) -> None:
    (diretorio / "relatorio.json").write_text(
        higienizar_texto(json.dumps(dados, ensure_ascii=False, indent=2)), encoding="utf-8")
    (diretorio / "relatorio.md").write_text(higienizar_texto(markdown(dados)), encoding="utf-8")


def markdown(d: dict) -> str:
    f = d["filtros"]
    L = [
        "# Relatório da execução",
        "",
        f"- **Consulta:** `{d['query']}`",
        f"- **Início:** {d['inicio']} · **Fim:** {d['fim']} · **Duração total:** {d['duracao_s']:.1f} s",
        f"- **Máximo de artigos por base:** {d['max_artigos_por_base']}",
        "- **Filtros:** " + ", ".join([
            f"ano_de={_n(f['ano_de'])}", f"ano_ate={_n(f['ano_ate'])}",
            f"tipos={_lista(f['tipos'])}", f"idiomas={_lista(f['idiomas'])}",
            f"somente_oa={'true' if f['somente_oa'] else 'false'}", f"campo_busca={f['campo_busca']}"]),
        "- **Enriquecimento:** " + ", ".join(f"{k}={'true' if v else 'false'}" for k, v in d["enriquecimento"].items()),
        "",
        "## Resumo por base",
        "",
        "| Base | Status | Gravados / pedidos | Total na API | Páginas | Chamadas HTTP (cache) | 429 | Taxa final (req/s) | Descartados (filtro local) | Enriquecidos | Duração (s) |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for b in d["bases"]:
        L.append(
            f"| {b['base']} | **{b['status']}** | {b['gravados']} / {b['pedidos']} | {_n(b['total_api'])} | "
            f"{b['paginas']} | {b['chamadas_http']} ({b['chamadas_cache']}) | {b['n_429']} | {_n(b['taxa_final'])} | "
            f"{b['descartados_filtro_local']}{' (teto atingido)' if b['teto_filtro_local_atingido'] else ''} | "
            f"{b['enriquecidos']} | {b['duracao_s']:.1f} |")
    oc = d.get("opencitations")
    if oc:
        L += ["", f"**OpenCitations** (enriquecedor compartilhado): {oc['chamadas_http']} chamadas HTTP "
                  f"({oc['chamadas_cache']} do cache), {oc['n_429']} respostas 429, taxa "
                  f"{_n(oc['taxa_inicial'])} → {_n(oc['taxa_final'])} req/s"
                  + (f"; **{oc['indisponivel']}**" if oc["indisponivel"] else "") + "."]
    c = d.get("consolidado")
    if c:
        L += ["", "**Consolidado** (`consolidado.csv`): " + (
            f"falhou — {c['erro']}" if c.get("erro") else
            f"{c['registros_entrada']} registros das bases; {c['duplicatas_removidas']} duplicatas removidas; "
            f"{c['sem_doi_ou_resumo']} artigos sem DOI ou sem resumo descartados; {c['linhas']} artigos gravados, "
            f"{c['em_varias_bases']} deles em 2 ou mais bases.")]
    L += ["", "## Detalhes", ""]
    for b in d["bases"]:
        L += [f"### {b['base']} — {b['status']}", ""]
        if b["motivo"]:
            L.append(f"- **Motivo:** {b['motivo']}")
        if b["consulta_traduzida"]:
            L.append(f"- **Consulta enviada:** `{b['consulta_traduzida']}`")
        L += [
            f"- **Filtros nativos:** {_lista(b['filtros_nativos'])}",
            f"- **Filtros locais:** {_lista(b['filtros_locais'])}"
            + (f" — {b['descartados_filtro_local']} registros descartados"
               + ("; **teto de páginas extras atingido**" if b["teto_filtro_local_atingido"] else "")
               if b["filtros_locais"] else ""),
            f"- **Filtros ignorados:** {_lista(b['filtros_ignorados'])}",
        ]
        if b["filtros_atendidos"]:
            L.append(f"- **Filtros já atendidos pela base:** {_lista(b['filtros_atendidos'])}")
        if b["duplicados"]:
            L.append(f"- **Duplicatas removidas:** {b['duplicados']}")
        L.append(f"- **Taxa:** inicial {_n(b['taxa_inicial'])} → final {_n(b['taxa_final'])} req/s; 429 recebidos: {b['n_429']}")
        if b["avisos"]:
            L.append(f"- **Avisos:** {_lista(b['avisos'])}")
        if b["arquivo_csv"]:
            L.append(f"- **Arquivo:** `{b['arquivo_csv']}`")
        L.append("")
    return "\n".join(L)
