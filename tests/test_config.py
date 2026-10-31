import pytest

from coletor.config import ErroConfig, carregar

YAML = """
query: '"machine learning" AND agriculture'
bases_ativas: [openalex, arxiv]
max_artigos_por_base: 20
filtros:
  ano_de: 2020
  tipos: [artigo]
  idiomas: [PT]
limites:
  # arxiv: {taxa_rps: 0.33}
"""


def escrever(tmp_path, texto):
    p = tmp_path / "config.yaml"
    p.write_text(texto, encoding="utf-8")
    return p


def test_carrega_e_aplica_padroes(tmp_path):
    c = carregar(escrever(tmp_path, YAML))
    assert c.bases_ativas == ["openalex", "arxiv"] and c.max_artigos_por_base == 20
    assert c.filtros.idiomas == ["pt"] and c.filtros.campo_busca == "tudo"
    assert c.saida.raw_json is True and c.execucao.max_paginas_extras_filtro_local == 10
    assert c.limites == {}


def test_config_de_exemplo_do_repositorio():
    c = carregar("config.yaml")
    assert "scielo" not in c.bases_ativas and len(c.bases_ativas) == 8


def test_sobrescritas_da_cli(tmp_path):
    c = carregar(escrever(tmp_path, YAML), {"query": "deep learning", "max_artigos_por_base": 50,
                                             "bases_ativas": ["arxiv"], "saida.raw_json": False})
    assert c.query == "deep learning" and c.max_artigos_por_base == 50
    assert c.bases_ativas == ["arxiv"] and c.saida.raw_json is False


@pytest.mark.parametrize("trecho, mensagem", [
    ("bases_ativas: [openalex, scopus]", "scopus"),
    ("filtros: {tipos: [tese]}", "filtros.tipos"),
    ("filtros: {idiomas: [portugues]}", "ISO 639-1"),
    ("filtros: {ano_de: 2022, ano_ate: 2020}", "ano_de"),
    ("filtros: {campo_busca: resumo}", "campo_busca"),
    ("max_artigos_por_base: 0", "max_artigos_por_base"),
    ("chave_inventada: 1", "chave_inventada"),
    ("limites: {scopus: {taxa_rps: 1}}", "scopus"),
])
def test_erros_de_validacao(tmp_path, trecho, mensagem):
    with pytest.raises(ErroConfig, match=mensagem):
        carregar(escrever(tmp_path, "query: x\n" + trecho))


def test_query_invalida(tmp_path):
    with pytest.raises(ErroConfig, match="aspas"):
        carregar(escrever(tmp_path, "query: '\"aberta'"))


def test_arquivo_inexistente_e_yaml_quebrado(tmp_path):
    with pytest.raises(ErroConfig, match="não encontrado"):
        carregar(tmp_path / "nao.yaml")
    with pytest.raises(ErroConfig, match="YAML"):
        carregar(escrever(tmp_path, "query: [x"))
