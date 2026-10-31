import glob
import json

import httpx
import respx

from coletor.bases.crossref import URL, Crossref, acesso_aberto
from coletor.consulta import analisar
from coletor.segredos import Credenciais
from conftest import CRED, EMAIL_FALSO, FIXTURES, coletar, config, contexto, fixture


def itens(nome):
    return json.loads(fixture("crossref", nome))["message"]["items"]


def adaptador(relogio, cred=CRED, **cfg):
    return Crossref(contexto(config(**cfg), "crossref", relogio, cred))


def test_normaliza_registro_real(relogio):
    r = adaptador(relogio).normalizar(itens("busca_sem_cursor.json")[0])
    assert r.id_na_base == r.doi == "10.1093/oso/9780198828044.003.0003"
    assert r.titulo == "Machine learning with sklearn" and r.autores == ["Thomas P. Trappenberg"]
    assert r.ano == 2019 and r.data_publicacao == "2019-11-28" and r.tipo == "livro_capitulo"
    assert r.veiculo == "Fundamentals of Machine Learning" and r.editora == "Oxford University Press"
    assert r.paginas == "38-65" and r.idioma == "en" and r.n_citacoes == 19
    assert "<" not in r.resumo and r.resumo.startswith("This chapter")
    assert r.extras["x_crossref_isbn"] == ["9780198828044", "9780191883873"]


def test_todas_as_fixtures(relogio):
    a = adaptador(relogio)
    regs = [a.normalizar(i) for p in sorted(glob.glob(str(FIXTURES / "crossref" / "*.json")))
            if not p.endswith("_index.json") for i in json.load(open(p))["message"]["items"]]
    assert len(regs) == 50 and all(r.doi for r in regs)
    com_refs = [r for r in regs if r.referencias]
    assert com_refs and all(r.fonte_referencias == "nativa" for r in com_refs)
    assert all("/" in d for r in com_refs for d in r.referencias)  # DOIs
    assert {len(r.data_publicacao) for r in regs} <= {4, 7, 10}  # precisão variável
    assert any(r.autores_orcid and any(r.autores_orcid) for r in regs)
    assert any(r.financiadores for r in regs)


def test_acesso_aberto_por_licenca():
    assert acesso_aberto({"license": [{"URL": "http://creativecommons.org/licenses/by/4.0/"}]}) is True
    assert acesso_aberto({"license": [{"URL": "http://www.elsevier.com/tdm/userlicense/1.0/"}]}) is False
    assert acesso_aberto({}) is None


def test_parametros(relogio):
    a = adaptador(relogio, query='"machine learning" OR ai',
                  filtros={"ano_de": 2021, "ano_ate": 2022, "tipos": ["artigo", "livro_capitulo"],
                           "idiomas": ["en"], "somente_oa": True, "campo_busca": "titulo"})
    p = a.suporta(a.ctx.config.filtros)
    assert p.nativos == ["periodo", "tipos"] and set(p.locais) == {"idiomas", "somente_oa", "campo_busca"}
    assert a.parametros(analisar(a.ctx.config.query), p) == {
        "query.bibliographic": "machine learning ai",
        "filter": "from-pub-date:2021-01-01,until-pub-date:2022-12-31,type:journal-article,type:book,"
                  "type:book-chapter,type:monograph"}


def test_revisao_vira_local(relogio):
    a = adaptador(relogio, filtros={"tipos": ["revisao", "artigo"]})
    assert a.suporta(a.ctx.config.filtros).locais == ["tipos"]


def test_limites_com_e_sem_email():
    assert Crossref.limites_padrao(CRED) == (3, 3)
    assert Crossref.limites_padrao(Credenciais()) == (1, 1)


def _paginas(request):
    nome = "busca_sem_cursor.json" if request.url.params["offset"] == "0" else "pagina2_offset.json"
    return httpx.Response(200, text=fixture("crossref", nome))


@respx.mock
async def test_buscar_por_offset_com_mailto(relogio):
    rota = respx.get(URL).mock(side_effect=_paginas)
    a = adaptador(relogio)
    regs = await coletar(a, analisar("machine learning"), a.suporta(a.ctx.config.filtros), 8)
    assert len(regs) == 8 and rota.call_count == 2
    params = [c.request.url.params for c in rota.calls]
    assert params[0]["mailto"] == EMAIL_FALSO and "cursor" not in params[0]
    assert params[1]["offset"] == "5" and params[0]["rows"] == "8"
    assert a.ctx.estat.total_api == 3054951
