import httpx
import pytest
import respx
from lxml import etree

from coletor.bases.arxiv import NS, URL, ArXiv
from coletor.bases.base import EncerrarBase
from coletor.consulta import analisar
from conftest import coletar, config, contexto, fixture


def entradas(nome: str):
    return etree.fromstring(fixture("arxiv", nome).encode()).xpath("a:entry", namespaces=NS)


def adaptador(relogio, **cfg) -> ArXiv:
    return ArXiv(contexto(config(**cfg), "arxiv", relogio))


def test_normaliza_registro_real(relogio):
    r = adaptador(relogio).normalizar(entradas("busca.xml")[0])
    assert r.id_na_base == "2306.04338" and r.arxiv_id == "2306.04338"
    assert r.titulo == "Changing Data Sources in the Age of Machine Learning for Official Statistics"
    assert r.url_pagina == "https://arxiv.org/abs/2306.04338v1"
    assert r.url_pdf == "https://arxiv.org/pdf/2306.04338v1"
    assert r.ano == 2023 and r.data_publicacao == "2023-06-07"
    assert r.tipo == "preprint" and r.veiculo == "arXiv" and r.acesso_aberto is True
    assert r.assuntos == ["stat.ML", "cs.LG"]
    assert "\n" not in r.resumo and r.resumo.startswith("Data science has become")
    assert r.autores and all(r.autores)
    assert r.extras["x_arxiv_versao"] == "v1"
    assert r.extras["x_arxiv_categoria_primaria"] == "stat.ML"
    assert r.extras["x_arxiv_comentario"].startswith("Presented at UNECE")
    assert r.raw["atom_entry"].startswith("<entry")


def test_doi_quando_existe(relogio):
    a = adaptador(relogio)
    dois = [a.normalizar(e).doi for e in entradas("busca.xml")]
    assert "10.1007/s10994-024-06619-7" in dois


def test_todas_as_fixtures_normalizam(relogio):
    a = adaptador(relogio)
    for nome in ("busca.xml", "pagina2.xml", "busca_frase.xml", "filtro_periodo.xml", "campo_titulo.xml",
                 "campo_titulo_resumo.xml"):
        regs = [a.normalizar(e) for e in entradas(nome)]
        assert len(regs) == 5 and all(r.id_na_base and r.titulo for r in regs)
    periodo = [a.normalizar(e).ano for e in entradas("filtro_periodo.xml")]
    assert all(2021 <= x <= 2022 for x in periodo)


def test_traducao_com_periodo_e_campo(relogio):
    a = adaptador(relogio, query='"machine learning" agriculture',
                  filtros={"ano_de": 2021, "ano_ate": 2022, "campo_busca": "titulo"})
    plano = a.suporta(a.ctx.config.filtros)
    assert a.traduzir(analisar(a.ctx.config.query), plano) == \
        '(ti:"machine learning" AND ti:agriculture) AND submittedDate:[202101010000 TO 202212312359]'


def test_plano_de_filtros(relogio):
    a = adaptador(relogio, filtros={"idiomas": ["pt"], "somente_oa": True, "tipos": ["preprint", "artigo"]})
    p = a.suporta(a.ctx.config.filtros)
    assert p.incompativel is None and not p.locais
    assert any("idiomas" in x for x in p.ignorados)
    assert len(p.atendidos) == 2
    assert "incompatíveis" in a.suporta(config(filtros={"tipos": ["revisao"]}).filtros).incompativel


def _paginas(request):
    nome = "busca.xml" if request.url.params["start"] == "0" else "pagina2.xml"
    return httpx.Response(200, text=fixture("arxiv", nome))


@respx.mock
async def test_buscar_pagina_por_start(relogio):
    rota = respx.get(URL).mock(side_effect=_paginas)
    a = adaptador(relogio)
    regs = await coletar(a, analisar("machine learning"), a.suporta(a.ctx.config.filtros), 7)
    assert len(regs) == 7 and rota.call_count == 2
    p = [c.request.url.params for c in rota.calls]
    assert p[0]["search_query"] == "all:machine AND all:learning" and p[0]["max_results"] == "7"
    assert p[1]["start"] == "5"
    assert a.ctx.estat.total_api == 358373


@respx.mock
async def test_pagina_vazia_encerra(relogio):
    vazio = fixture("arxiv", "busca.xml").split("<entry>")[0] + "</feed>"
    respx.get(URL).mock(return_value=httpx.Response(200, text=vazio))
    a = adaptador(relogio)
    assert await coletar(a, analisar("x"), a.suporta(a.ctx.config.filtros), 10) == []


@respx.mock
async def test_erro_de_consulta_do_arxiv(relogio):
    erro = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/api/errors#bad</id>'
            "<title>Error</title><summary>malformed query</summary></entry></feed>")
    respx.get(URL).mock(return_value=httpx.Response(200, text=erro))
    a = adaptador(relogio)
    with pytest.raises(EncerrarBase, match="malformed"):
        await coletar(a, analisar("x"), a.suporta(a.ctx.config.filtros), 10)
