import csv

import pytest

from coletor import ranking


def test_score_considera_aderencia_ano_e_citacoes() -> None:
    score_citacoes_baixas = ranking.compute_score(0.5, 2020, 0, 2000, 2020, 0, 1000)
    score_citacoes_altas = ranking.compute_score(0.5, 2020, 1000, 2000, 2020, 0, 1000)
    assert score_citacoes_altas > score_citacoes_baixas
    assert ranking.compute_score(1, 2020, 1000, 2000, 2020, 0, 1000) == 1.0


def test_score_usa_valor_neutro_para_metadados_ausentes() -> None:
    assert ranking.compute_score(0.5, None, None, 2000, 2020, 0, 100) == 0.5


def test_match_aceita_apenas_as_tres_classes() -> None:
    with pytest.raises(ValueError):
        ranking.Screening(justification="", quote="", match=0.7)


def test_screen_rejeita_citacao_que_nao_existe_no_resumo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ranking,
        "_chat",
        lambda prompt, model: ranking.Screening(
            justification="Critério 1 aplicável.", quote="texto inventado", match=1
        ),
    )
    with pytest.raises(ValueError, match="não aparece literalmente"):
        ranking.screen("Título", "Resumo original.", "palavra-chave", "Critério 1", "modelo")


def test_gerar_ranking_preserva_colunas_e_ordena_por_score(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    consolidado = tmp_path / "consolidado.csv"
    colunas = ["doi", "bases", "titulo", "ano", "resumo", "palavras_chave", "n_citacoes"]
    linhas = [
        {"doi": "10.1/antigo", "bases": "openalex", "titulo": "Paper antigo", "ano": "2020", "resumo": "Evidence A.", "palavras_chave": "a", "n_citacoes": "0"},
        {"doi": "10.1/citado", "bases": "crossref", "titulo": "Paper citado", "ano": "2020", "resumo": "Evidence B.", "palavras_chave": "b", "n_citacoes": "100"},
    ]
    with consolidado.open("w", encoding="utf-8-sig", newline="") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=colunas, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(linhas)

    monkeypatch.setattr(
        ranking,
        "screen",
        lambda title, abstract, keywords, criteria, model: ranking.Screening(
            justification="Critério 1 aplicável.", quote=abstract, match=1
        ),
    )
    output = ranking.gerar_ranking(consolidado, "Critério 1", modelo="qwen3.5:0.8b")

    with output.open("r", encoding="utf-8-sig", newline="") as arquivo:
        reader = csv.DictReader(arquivo)
        resultados = list(reader)
        assert reader.fieldnames == colunas + ranking.COLUNAS_LLM
    assert [linha["doi"] for linha in resultados] == ["10.1/citado", "10.1/antigo"]
    assert resultados[0]["llm_label"] == "incluido"
    assert resultados[0]["llm_status"] == "ok"
    assert '"Evidence B."' in resultados[0]["llm_justification"]


def test_falha_de_um_artigo_nao_interrompe_o_lote(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    consolidado = tmp_path / "consolidado.csv"
    colunas = ["doi", "titulo", "ano", "resumo", "n_citacoes"]
    with consolidado.open("w", encoding="utf-8-sig", newline="") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=colunas, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows([
            {"doi": "10.1/erro", "titulo": "Falha", "ano": "2020", "resumo": "Resumo A.", "n_citacoes": "1"},
            {"doi": "10.1/ok", "titulo": "Sucesso", "ano": "2021", "resumo": "Resumo B.", "n_citacoes": "2"},
        ])

    def avaliar(titulo, abstract, keywords, criteria, model):
        if titulo == "Falha":
            raise RuntimeError("erro simulado")
        return ranking.Screening(justification="Critério 1.", quote=abstract, match=1)

    monkeypatch.setattr(ranking, "screen", avaliar)
    output = ranking.gerar_ranking(consolidado, "Critério 1")
    with output.open("r", encoding="utf-8-sig", newline="") as arquivo:
        resultados = list(csv.DictReader(arquivo))

    assert len(resultados) == 2
    assert resultados[0]["llm_status"] == "ok"
    assert resultados[1]["llm_status"] == "erro"
    assert resultados[1]["llm_score"] == ""
