import pytest

from coletor.consulta import (ErroConsulta, Op, Termo, analisar, casa, para_arxiv, para_core, para_doaj,
                              para_europepmc, para_pubmed, texto_booleano, texto_simples)

EXEMPLO = '"machine learning" AND agriculture'


def test_frase_e_operador():
    assert analisar(EXEMPLO) == Op("AND", (Termo("machine learning", True), Termo("agriculture")))


def test_termos_lado_a_lado_valem_and():
    assert analisar("machine learning") == Op("AND", (Termo("machine"), Termo("learning")))


def test_and_tem_precedencia_sobre_or():
    assert analisar("a OR b AND c") == Op("OR", (Termo("a"), Op("AND", (Termo("b"), Termo("c")))))


def test_parenteses():
    assert analisar("(a OR b) c") == Op("AND", (Op("OR", (Termo("a"), Termo("b"))), Termo("c")))


def test_operador_minusculo_e_palavra():
    assert analisar("cats and dogs") == Op("AND", (Termo("cats"), Termo("and"), Termo("dogs")))


@pytest.mark.parametrize("q", ['"aberta', "(a OR b", "a OR", "AND a", "", "   ", "a )"])
def test_consultas_invalidas(q):
    with pytest.raises(ErroConsulta):
        analisar(q)


def test_openalex_booleano():
    assert texto_booleano(analisar(EXEMPLO)) == EXEMPLO
    assert texto_booleano(analisar("(a OR b) c")) == "(a OR b) AND c"


def test_texto_simples():
    assert texto_simples(analisar('"deep learning" OR cnn')) == "deep learning cnn"


@pytest.mark.parametrize("campo, esperado", [
    ("tudo", 'all:"machine learning" AND all:agriculture'),
    ("titulo", 'ti:"machine learning" AND ti:agriculture'),
    ("titulo_resumo", '(ti:"machine learning" OR abs:"machine learning") AND (ti:agriculture OR abs:agriculture)'),
])
def test_arxiv(campo, esperado):
    assert para_arxiv(analisar(EXEMPLO), campo) == esperado


def test_pubmed():
    assert para_pubmed(analisar(EXEMPLO), "titulo_resumo") == '"machine learning"[tiab] AND agriculture[tiab]'
    assert para_pubmed(analisar(EXEMPLO), "tudo") == EXEMPLO


def test_europepmc():
    assert para_europepmc(analisar(EXEMPLO), "titulo") == 'TITLE:"machine learning" AND TITLE:agriculture'


def test_core_e_doaj_escapam_lucene():
    assert para_core(analisar("c++ a:b"), "tudo") == r"c\+\+ AND a\:b"
    assert para_doaj(analisar('"x" y'), "titulo") == 'bibjson.title:"x" AND bibjson.title:y'


def test_casa():
    arv = analisar(EXEMPLO)
    assert casa(arv, "Machine-Learning applied to Agriculture")
    assert not casa(arv, "machine learning in medicine")
    assert not casa(analisar("learn"), "machine learning")  # palavra inteira
    assert casa(analisar("açúcar"), "Produção de ACUCAR")  # sem acentos/maiúsculas
    assert casa(analisar("x OR agriculture"), "smart agriculture")
