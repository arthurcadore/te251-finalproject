import csv

import pytest

from coletor import ranking


def test_score_considera_aderencia_ano_e_citacoes() -> None:
    score_citacoes_baixas = ranking.compute_score(0.5, 2020, 0, 2000, 2020, 0, 1000)
    score_citacoes_altas = ranking.compute_score(0.5, 2020, 1000, 2000, 2020, 0, 1000)
    assert score_citacoes_altas > score_citacoes_baixas
    assert ranking.compute_score(1, 2020, 1000, 2000, 2020, 0, 1000, tipo="artigo") == 1.0


def test_score_usa_valor_neutro_para_metadados_ausentes() -> None:
    assert ranking.compute_score(0.5, None, None, 2000, 2020, 0, 100) == 0.5


def test_match_aceita_apenas_as_tres_classes() -> None:
    with pytest.raises(ValueError):
        ranking.Screening(justification="", quote="", match=0.7)


def test_screen_rejeita_citacao_que_nao_existe_no_resumo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ranking,
        "_chat",
        lambda prompt, model, temperatura=0.0: ranking.Screening(
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
        lambda title, abstract, keywords, criteria, model, temperatura=0.0: ranking.Screening(
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

    def avaliar(titulo, abstract, keywords, criteria, model, temperatura=0.0):
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


def test_chat_desativa_raciocinio_e_limita_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas = {}

    class _Mensagem:
        content = '{"justification": "Critério 1.", "quote": "x", "match": 1}'

    class _Resposta:
        message = _Mensagem()
        done_reason = "stop"

    def _falso_chat(**kwargs):
        chamadas.update(kwargs)
        return _Resposta()

    monkeypatch.setattr(ranking.ollama, "chat", _falso_chat)
    ranking._chat("prompt", "modelo")
    assert chamadas["think"] is False
    assert chamadas["options"]["num_predict"] == ranking.MAX_TOKENS_RESPOSTA


def test_chat_rejeita_resposta_truncada(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Mensagem:
        content = '{"justification": "Critério 1.'

    class _Resposta:
        message = _Mensagem()
        done_reason = "length"

    monkeypatch.setattr(ranking.ollama, "chat", lambda **kwargs: _Resposta())
    with pytest.raises(ValueError, match="limite de tokens"):
        ranking._chat("prompt", "modelo")


def test_screen_sem_resumo_nao_chama_o_modelo(monkeypatch: pytest.MonkeyPatch) -> None:
    def _nao_chamar(prompt, model, temperatura=0.0):
        raise AssertionError("o modelo não deveria ser chamado")

    monkeypatch.setattr(ranking, "_chat", _nao_chamar)
    with pytest.raises(ValueError, match="sem resumo"):
        ranking.screen("Título", "  ", "", "Critério 1", "modelo")


def test_score_com_pesos_dinamicos_e_minimo_de_aderencia() -> None:
    score_padrao = ranking.compute_score(1, 2000, 1000, 2000, 2020, 0, 1000)
    score_so_aderencia = ranking.compute_score(
        1, 2000, 0, 2000, 2020, 0, 1000,
        pesos={"aderencia": 1.0, "ano": 0.0, "citacoes": 0.0},
    )
    score_percentual = ranking.compute_score(
        1, 2000, 1000, 2000, 2020, 0, 1000,
        pesos={"aderencia": 50, "ano": 10, "citacoes": 40},
    )
    assert score_padrao == 0.85
    assert score_so_aderencia == 1.0
    assert score_percentual == 0.9

    with pytest.raises(ValueError):
        ranking.normalizar_pesos({"aderencia": 0.45, "ano": 0.30, "citacoes": 0.25})
    with pytest.raises(ValueError):
        ranking.normalizar_pesos({"aderencia": 0.70, "ano": 0.20, "citacoes": 0.20})


def test_chat_usa_temperatura_informada(monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas = {}

    class _Mensagem:
        content = '{"justification": "Critério 1.", "quote": "x", "match": 1}'

    class _Resposta:
        message = _Mensagem()
        done_reason = "stop"

    monkeypatch.setattr(ranking.ollama, "chat", lambda **kwargs: chamadas.update(kwargs) or _Resposta())
    ranking._chat("prompt", "modelo", 0.3)
    assert chamadas["options"]["temperature"] == 0.3


def test_gerar_ranking_rejeita_temperatura_invalida(tmp_path) -> None:
    consolidado = tmp_path / "consolidado.csv"
    consolidado.write_text("doi,titulo,ano,resumo,n_citacoes\n", encoding="utf-8")
    with pytest.raises(ValueError, match="temperatura"):
        ranking.gerar_ranking(consolidado, "Critério 1", temperatura=2)


def test_falha_registra_motivo_na_justificativa(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    consolidado = tmp_path / "consolidado.csv"
    consolidado.write_text('doi,titulo,ano,resumo,n_citacoes\n10.1/x,T,2020,"Resumo.",1\n', encoding="utf-8")

    def falhar(*args, **kwargs):
        raise ValueError("a citação devolvida pelo modelo não aparece literalmente no resumo")

    monkeypatch.setattr(ranking, "screen", falhar)
    with ranking.gerar_ranking(consolidado, "Critério 1").open(encoding="utf-8-sig") as arquivo:
        linha = list(csv.DictReader(arquivo))[0]
    assert linha["llm_status"] == "erro"
    assert "não aparece literalmente" in linha["llm_justification"]


def test_citacoes_por_ano_divide_pela_idade() -> None:
    assert ranking.citacoes_por_ano(100, 2016, ano_referencia=2025) == 10.0
    assert ranking.citacoes_por_ano(30, 2025, ano_referencia=2025) == 30.0
    # Ano futuro (data de publicação adiantada) conta como 1 ano.
    assert ranking.citacoes_por_ano(5, 2027, ano_referencia=2025) == 5.0
    assert ranking.citacoes_por_ano(None, 2020) is None
    assert ranking.citacoes_por_ano(10, "") is None


def test_valor_tipo_usa_tabela_neutro_e_outros() -> None:
    assert ranking.valor_tipo("artigo") == 1.0
    assert ranking.valor_tipo("preprint") == 0.5
    assert ranking.valor_tipo("dissertation") == ranking.VALORES_TIPO_PADRAO["outros"]
    assert ranking.valor_tipo("") == 0.5
    assert ranking.valor_tipo("preprint", {"preprint": 0.9, "outros": 0.1}) == 0.9


def test_score_inclui_tipo_de_publicacao() -> None:
    pesos = {"aderencia": 0.5, "ano": 0.0, "citacoes": 0.0, "tipo": 0.5}
    artigo = ranking.compute_score(1, None, None, None, None, None, None, tipo="artigo", pesos=pesos)
    preprint = ranking.compute_score(1, None, None, None, None, None, None, tipo="preprint", pesos=pesos)
    custom = ranking.compute_score(
        1, None, None, None, None, None, None, tipo="preprint", pesos=pesos,
        valores_tipo={"artigo": 100, "revisao": 100, "conferencia": 80, "livro_capitulo": 60, "preprint": 20, "outros": 0},
    )
    assert artigo == 1.0 and preprint == 0.75 and custom == 0.6


def test_pesos_antigos_sem_tipo_continuam_validos() -> None:
    assert ranking.normalizar_pesos({"aderencia": 70, "ano": 15, "citacoes": 15})["tipo"] == 0.0
    assert ranking.normalizar_pesos(None) == ranking.PESOS_SCORE
    with pytest.raises(ValueError):
        ranking.normalizar_pesos({"aderencia": 0.7, "ano": 0.1, "citacoes": 0.1, "tipo": 0.6})


def test_gerar_ranking_usa_citacoes_por_ano(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Mesmo número de citações: o artigo mais novo tem mais citações por ano e fica à frente.
    consolidado = tmp_path / "consolidado.csv"
    consolidado.write_text(
        "doi,titulo,ano,resumo,n_citacoes,tipo\n"
        '10.1/velho,Velho,2000,"Resumo A.",100,artigo\n'
        '10.1/novo,Novo,2000,"Resumo B.",100,artigo\n'
        '10.1/recente,Recente,2020,"Resumo C.",100,artigo\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        ranking, "screen",
        lambda title, abstract, keywords, criteria, model, temperatura=0.0: ranking.Screening(
            justification="Critério 1.", quote=abstract, match=1),
    )
    saida = ranking.gerar_ranking(
        consolidado, "Critério 1", pesos={"aderencia": 0.5, "ano": 0.0, "citacoes": 0.5, "tipo": 0.0}
    )
    with saida.open(encoding="utf-8-sig") as arquivo:
        linhas = list(csv.DictReader(arquivo))
    assert linhas[0]["doi"] == "10.1/recente"
    assert float(linhas[0]["llm_score"]) == 1.0
