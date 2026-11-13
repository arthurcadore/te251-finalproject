"""Gera as figuras da apresentação (PDF em figuras/).

Dados copiados de saida/2026-10-31_170240_sar-and-agricultura/relatorio.json
(execução real da consulta `SAR AND Agricultura`, 100 artigos por base).
A pasta saida/ não é versionada, por isso os números ficam embutidos aqui.

Uso: python gerar_graficos.py   (requer matplotlib)
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SAIDA = Path(__file__).resolve().parent / "figuras"
SAIDA.mkdir(exist_ok=True)

# Paleta do tema (versões escuras das cores, legíveis em fundo branco)
AZUL = "#3C8CFF"      # accentblue
CIANO = "#00A5C8"     # radarcyan escurecido
DOURADO = "#E0A800"   # accentgold escurecido
CINZA = "#5A6478"
TEXTO = "#1C2333"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 11.5,
    "axes.edgecolor": CINZA,
    "axes.labelcolor": TEXTO,
    "xtick.color": TEXTO,
    "ytick.color": TEXTO,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.facecolor": "white",
})

# ── Artigos gravados por base ─────────────────────────────────
# (base, gravados, status) — bases que falharam (OpenAlex, Semantic Scholar) ficam de fora
BASES = [
    ("Crossref", 100, "ok"),
    ("Europe PMC", 100, "ok"),
    ("CORE", 100, "ok"),
    ("DOAJ", 22, "ok"),
    ("PubMed", 10, "ok"),
    ("arXiv", 0, "ok"),
]
MOTIVO = {
    "arXiv": "0 resultados",
}


def grafico_bases() -> None:
    nomes = [b[0] for b in BASES][::-1]
    valores = [b[1] for b in BASES][::-1]
    cores = [CINZA if b[1] == 0 else CIANO for b in BASES][::-1]
    fig, ax = plt.subplots(figsize=(5.0, 3.5))
    barras = ax.barh(nomes, valores, color=cores, height=0.62)
    for barra, nome, valor in zip(barras, nomes, valores):
        rotulo = MOTIVO.get(nome, str(valor))
        if valor == 0:
            ax.text(1.5, barra.get_y() + barra.get_height() / 2, rotulo,
                    va="center", ha="left", fontsize=10, color=cores[nomes.index(nome)])
        else:
            ax.text(valor + 1.5, barra.get_y() + barra.get_height() / 2, str(valor),
                    va="center", ha="left", fontsize=10, color=TEXTO)
    ax.set_xlim(0, 118)
    ax.set_xlabel("artigos gravados (máximo 100 por base)")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x", color="#DDE2EA", linewidth=0.7)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(SAIDA / "bases_gravados.pdf")
    plt.close(fig)


# ── Funil da consolidação ─────────────────────────────────────
REGISTROS = 332        # registros vindos das bases
DUPLICATAS = 25        # fundidos (mesmo DOI/PMID/PMCID/arXiv ou título+ano)
SEM_DOI_RESUMO = 136   # descartados por não terem DOI ou resumo
LINHAS = 171           # linhas no consolidado.csv


def grafico_funil() -> None:
    etapas = [
        ("Registros das bases", REGISTROS, AZUL),
        ("Após deduplicação", REGISTROS - DUPLICATAS, CIANO),
        ("Com DOI e resumo\n(consolidado.csv)", LINHAS, DOURADO),
    ]
    fig, ax = plt.subplots(figsize=(5.0, 3.5))
    largura_max = REGISTROS
    for i, (rotulo, valor, cor) in enumerate(etapas):
        y = len(etapas) - 1 - i
        esquerda = (largura_max - valor) / 2
        ax.barh(y, valor, left=esquerda, color=cor, height=0.7)
        ax.text(largura_max / 2, y, str(valor), ha="center", va="center",
                fontsize=14, fontweight="bold", color="white")
        ax.text(-6, y, rotulo, ha="right", va="center", fontsize=11, color=TEXTO)
    ax.text(largura_max + 6, 1.5, f"−{DUPLICATAS} duplicatas", va="center", fontsize=10.5, color=CINZA)
    ax.text(largura_max + 6, 0.5, f"−{SEM_DOI_RESUMO} sem DOI\nou resumo", va="center", fontsize=10.5, color=CINZA)
    ax.set_xlim(-125, largura_max + 100)
    ax.set_ylim(-0.6, len(etapas) - 0.4)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(SAIDA / "funil_consolidacao.pdf")
    plt.close(fig)


if __name__ == "__main__":
    grafico_bases()
    grafico_funil()
    print(f"figuras gravadas em {SAIDA}")
