import json

import httpx
import pytest
import respx

from coletor.bases.base import EncerrarBase
from coletor.bases.openalex import URL, OpenAlex, resumo
from coletor.consulta import analisar
from conftest import CHAVE_FALSA, coletar, config, contexto, fixture


def resultados(nome: str) -> list[dict]:
    return json.loads(fixture("openalex", nome))["results"]


def adaptador(relogio, **cfg) -> OpenAlex:
    return OpenAlex(contexto(config(**cfg), "openalex", relogio))


def test_normaliza_registro_real(relogio):
    r = adaptador(relogio).normalizar(resultados("busca.json")[0])
    assert r.id_na_base == "W3153990350"
    assert r.doi == "10.1007/s12525-021-00475-2"
    assert r.titulo == "Machine learning and deep learning"
    assert r.autores[0] == "Christian Janiesch" and r.autores_orcid[0] == "0000-0002-8050-123X"
    assert len(r.autores) == len(r.autores_orcid)
    assert "University of Würzburg" in r.afiliacoes
    assert r.ano == 2021 and r.tipo == "artigo" and r.idioma == "en"
    assert r.veiculo == "Electronic Markets" and r.issn == ["1019-6781", "1422-8890"]
    assert r.volume == "31" and r.numero == "3" and r.paginas == "685-695"
    assert r.acesso_aberto is True and r.status_oa == "hybrid" and r.licenca == "cc-by"
    assert r.url_pdf.endswith(".pdf")
    assert r.citacoes_por_ano[2025] == 872 and r.fwci == pytest.approx(143.8104)
    assert r.percentil_citacoes == pytest.approx(0.99992779)
    assert r.fonte_citacoes == "nativa" and r.retratado is False
    assert all(x.startswith("openalex:W") for x in r.relacionados)
    assert r.palavras_chave[0] == "machine learning"
    assert r.financiadores and r.extras["x_openalex_indexado_em"] == ["arxiv", "crossref", "datacite"]
    assert r.extras["x_openalex_paises"] and r.raw["id"] == "https://openalex.org/W3153990350"


def test_todos_os_registros_das_fixtures_normalizam(relogio):
    a = adaptador(relogio)
    n = 0
    for nome in ("busca.json", "pagina2.json", "filtro_periodo.json", "filtro_idioma.json", "filtro_tipo_revisao.json",
                 "filtro_tipo_preprint.json", "filtro_tipo_conferencia.json", "filtro_tipo_livro.json",
                 "filtro_oa.json", "campo_titulo.json", "campo_titulo_resumo.json"):
        for w in resultados(nome):
            r = a.normalizar(w)
            assert r.id_na_base.startswith("W") and r.titulo
            n += 1
    assert n == 55


def test_ids_externos_e_tipos(relogio):
    a = adaptador(relogio)
    com_pmid = [a.normalizar(w) for nome in ("busca.json", "filtro_tipo_revisao.json", "pagina2.json",
                                              "filtro_periodo.json", "filtro_oa.json")
                for w in resultados(nome) if (w.get("ids") or {}).get("pmid")]
    assert com_pmid and all(r.pmid.isdigit() for r in com_pmid)
    conf = [a.normalizar(w) for w in resultados("filtro_tipo_conferencia.json")]
    assert {r.tipo for r in conf} == {"conferencia"}
    livros = {a.normalizar(w).tipo for w in resultados("filtro_tipo_livro.json")}
    assert livros == {"livro_capitulo"}
    arx = [a.normalizar(w) for w in resultados("filtro_tipo_preprint.json")]
    assert any(r.arxiv_id and "v" not in r.arxiv_id[-3:] for r in arx)


def test_resumo_invertido():
    assert resumo({"mundo": [1], "olá": [0], "!": [2]}) == "olá mundo !"
    assert resumo(None) is None
    w = resultados("busca.json")[0]
    assert resumo(w["abstract_inverted_index"]).startswith("Abstract Today, intelligent systems")


@pytest.mark.parametrize("filtros, esperado", [
    ({}, {"search": '"machine learning" AND agriculture'}),
    ({"ano_de": 2020, "ano_ate": 2022, "idiomas": ["pt", "en"], "somente_oa": True, "tipos": ["artigo", "livro_capitulo"]},
     {"search": '"machine learning" AND agriculture',
      "filter": "from_publication_date:2020-01-01,to_publication_date:2022-12-31,language:pt|en,"
                "type:article|book|book-chapter,open_access.is_oa:true"}),
    ({"tipos": ["conferencia"], "campo_busca": "titulo"},
     {"filter": 'title.search:"machine learning" AND agriculture,primary_location.source.type:conference'}),
    ({"campo_busca": "titulo_resumo"}, {"filter": 'title_and_abstract.search:"machine learning" AND agriculture'}),
])
def test_parametros(relogio, filtros, esperado):
    a = adaptador(relogio, query='"machine learning" AND agriculture', filtros=filtros)
    plano = a.suporta(a.ctx.config.filtros)
    assert a.parametros(analisar(a.ctx.config.query), plano) == esperado
    assert not plano.locais


def test_conferencia_com_outros_tipos_vira_local(relogio):
    a = adaptador(relogio, filtros={"tipos": ["artigo", "conferencia"]})
    plano = a.suporta(a.ctx.config.filtros)
    assert plano.locais == ["tipos"] and "filter" not in a.parametros(analisar("x"), plano)


def _paginas(request):
    cursor = request.url.params["cursor"]
    nome = "busca.json" if cursor == "*" else "pagina2.json"
    return httpx.Response(200, text=fixture("openalex", nome), headers={"x-ratelimit-remaining-usd": "0.9"})


@respx.mock
async def test_buscar_pagina_por_cursor(relogio):
    rota = respx.get(URL).mock(side_effect=_paginas)
    a = adaptador(relogio, max_artigos_por_base=8)
    regs = await coletar(a, analisar("machine learning"), a.suporta(a.ctx.config.filtros), 8)
    assert len(regs) == 8 and rota.call_count == 2
    pedidos = [c.request.url.params for c in rota.calls]
    assert pedidos[0]["per_page"] == "8" and pedidos[0]["api_key"] == CHAVE_FALSA
    assert pedidos[1]["cursor"] != "*"
    assert a.ctx.estat.total_api == 6214372 and a.ctx.estat.paginas == 2
    assert len({r.id_na_base for r in regs}) == 8
    assert all(r.consulta == "machine learning" and r.coletado_em.endswith("Z") for r in regs)


@respx.mock
async def test_filtro_local_descarta_e_respeita_teto(relogio):
    rota = respx.get(URL).mock(side_effect=_paginas)
    # conferência + artigo = filtro local; busca.json/pagina2.json não têm conferências nem 2 artigos
    a = adaptador(relogio, filtros={"tipos": ["conferencia"], "ano_de": 2000}, execucao={
        "cache_http": False, "max_paginas_extras_filtro_local": 1})
    plano = a.suporta(a.ctx.config.filtros)
    plano.modos["tipos"] = "local"
    regs = await coletar(a, analisar("x"), plano, 100)
    assert regs == [] and rota.call_count == 2
    assert a.ctx.estat.teto_filtro_local_atingido and a.ctx.estat.descartados_filtro_local > 0


@respx.mock
async def test_orcamento_esgotado_encerra_depois_da_pagina(relogio):
    respx.get(URL).mock(return_value=httpx.Response(200, text=fixture("openalex", "busca.json"),
                                                    headers={"x-ratelimit-remaining-usd": "0.0004"}))
    a = adaptador(relogio)
    regs = []
    with pytest.raises(EncerrarBase, match="orçamento"):
        async for lote in a.buscar(analisar("x"), a.suporta(a.ctx.config.filtros), 100):
            regs += lote
    assert len(regs) == 5


@respx.mock
async def test_429_por_orcamento_nao_repete(relogio):
    rota = respx.get(URL).mock(return_value=httpx.Response(429, headers={"x-ratelimit-remaining-usd": "0"}))
    a = adaptador(relogio)
    with pytest.raises(EncerrarBase, match="429"):
        await coletar(a, analisar("x"), a.suporta(a.ctx.config.filtros), 10)
    assert rota.call_count == 1
