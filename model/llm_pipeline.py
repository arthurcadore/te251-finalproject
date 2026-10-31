"""CLI fino para a triagem LLM do CSV consolidado.

Requer que o serviço Ollama esteja ativo e que o modelo local esteja baixado.
Exemplo: ollama pull qwen3.5:0.8b; python model/llm_pipeline.py saida/.../consolidado.csv --criteria "Critérios..."
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from coletor.ranking import (
    DEFAULT_MODEL,
    Screening,
    compute_score as _compute_score,
    gerar_ranking,
    screen as _screen,
)

MODEL = DEFAULT_MODEL


def compute_score(
    match: float,
    year: Any,
    n_citacoes: Any,
    year_min: float | None,
    year_max: float | None,
    citacoes_min: float | None,
    citacoes_max: float | None,
) -> float:
    """Combina match da LLM, ano e citações (citações com normalização logarítmica)."""
    return _compute_score(match, year, n_citacoes, year_min, year_max, citacoes_min, citacoes_max)


def screen(title: str, abstract: str, kwds: str, criteria: str) -> Screening:
    """Avalia um artigo e exige uma citação literal presente no resumo."""
    return _screen(title, abstract, kwds, criteria, MODEL)


def screen_csv(
    input_csv: str | Path,
    criteria: str,
    *,
    output: str | Path | None = None,
    model: str = MODEL,
) -> Path:
    """Gera ranking.csv, mantendo as colunas originais e acrescentando campos LLM."""
    return gerar_ranking(input_csv, criteria, modelo=model, output=output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida e ranqueia artigos de um consolidado.csv via Ollama.")
    parser.add_argument("consolidado", type=Path, help="caminho do consolidado.csv gerado pelo coletor")
    parser.add_argument("--criteria", required=True, help="texto dos critérios de inclusão e exclusão")
    parser.add_argument("--model", default=MODEL, help="modelo Ollama instalado localmente")
    parser.add_argument("--output", type=Path, help="destino de ranking.csv (padrão: ao lado do consolidado)")
    args = parser.parse_args()
    destino = screen_csv(args.consolidado, args.criteria, output=args.output, model=args.model)
    print(f"ranking salvo em {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())