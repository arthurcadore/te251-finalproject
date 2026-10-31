import glob
import json

import httpx
import respx

from coletor.bases.europepmc import RAIZ, EuropePMC, tipo_canonico
from coletor.consulta import analisar
from conftest import FIXTURES, coletar, config, contexto, fixture


def resultados(nome):
    return json.loads(fixture("europepmc", nome))["resultList"]["result"]


def adaptador(relogio, **cfg):
    return EuropePMC(contexto(config(**cfg), "europepmc", relogio))


def test_normaliza_registro_real(relogio):
    r = adaptador(relogio).normalizar(resultados("busca_oa_pmc.json")[0])
    assert r.id_na_base == r.pmid == "42875498" and r.pmcid == "PMC13686947"
    assert r.doi == "10.1038/s41586-026-11126-x"
    assert r.url_pagina == "https://europepmc.org/article/MED/42875498"
    assert r.titulo == "Advancing subseasonal forecasting with machine learning."
    assert r.autores[0] == "Guan H" and "Microsoft Research, Cambridge, MA, USA." in r.afiliacoes
    assert r.ano == 2026 and r.tipo == "artigo" and r.idioma == "en"
    assert r.veiculo == "Nature" and r.issn == ["0028-0836", "1476-4687"] and r.paginas == "951-957"
    assert r.acesso_aberto is True and r.licenca == "cc by-nc-nd" and "pdf=render" in r.url_pdf
    assert "<sup>" not in r.resumo and r.fonte_citacoes == "nativa"
    assert r.extras["x_epmc_fonte"] == "MED" and r.extras["x_epmc_tem_dados"] is True


def test_todas_as_fixtures(relogio):
    a = adaptador(relogio)
    regs = [a.normalizar(x) for p in glob.glob(str(FIXTURES / "europepmc" / "*.json"))
            if "_index" not in p and "enriq" not in p for x in json.load(open(p))["resultList"]["result"]]
    assert len(regs) == 60 and all(r.id_na_base and r.titulo for r in regs)
    pprs = [r for r in regs if r.extras["x_epmc_fonte"] == "PPR"]
    assert pprs and {r.tipo for r in pprs} == {"preprint"} and all(r.veiculo for r in pprs)
    assert any(r.idioma == "pt" for r in regs)
    assert any(any(r.autores_orcid) for r in regs)
    assert any(r.extras["x_epmc_grants"] for r in regs) and any(r.extras["x_epmc_mesh_qualificadores"] for r in regs)


def test_tipo_canonico():
    assert tipo_canonico({"source": "MED", "pubTypeList": {"pubType": ["review-article", "Journal Article"]}}) == "revisao"
    assert tipo_canonico({"source": "PPR", "pubTypeList": {"pubType": ["Preprint"]}}) == "preprint"
    assert tipo_canonico({"source": "MED", "pubTypeList": {"pubType": ["Editorial"]}}) == "Editorial"


def test_traducao_com_filtros(relogio):
    a = adaptador(relogio, query='"machine learning"', filtros={
        "ano_de": 2021, "idiomas": ["pt"], "tipos": ["revisao", "preprint"], "somente_oa": True, "campo_busca": "titulo"})
    p = a.suporta(a.ctx.config.filtros)
    assert not p.locais
    assert a.traduzir(analisar(a.ctx.config.query), p) == (
        '(TITLE:"machine learning") AND (PUB_YEAR:[2021 TO 3000]) AND (LANG:"por") '
        'AND (PUB_TYPE:"review" OR SRC:PPR) AND (OPEN_ACCESS:y)')


def test_conferencia_vira_local(relogio):
    a = adaptador(relogio, filtros={"tipos": ["artigo", "conferencia"]})
    assert a.suporta(a.ctx.config.filtros).locais == ["tipos"]


def _paginas(request):
    nome = "busca.json" if request.url.params["cursorMark"] == "*" else "pagina2.json"
    return httpx.Response(200, text=fixture("europepmc", nome))


@respx.mock
async def test_buscar_por_cursor_mark(relogio):
    rota = respx.get(RAIZ + "search").mock(side_effect=_paginas)
    a = adaptador(relogio)
    regs = await coletar(a, analisar("machine learning"), a.suporta(a.ctx.config.filtros), 8)
    assert len(regs) == 8 and rota.call_count == 2
    p = [c.request.url.params for c in rota.calls]
    assert p[0]["resultType"] == "core" and p[0]["format"] == "json" and p[1]["cursorMark"] != "*"
    assert a.ctx.estat.total_api == 657876
