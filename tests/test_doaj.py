import glob
import json
from urllib.parse import unquote

import httpx
import respx

from coletor.bases.doaj import RAIZ, DOAJ
from coletor.config import Filtros
from coletor.consulta import analisar
from coletor.filtros import aplicar_locais
from conftest import FIXTURES, coletar, config, contexto, fixture


def resultados(nome):
    return json.loads(fixture("doaj", nome))["results"]


def adaptador(relogio, **cfg):
    return DOAJ(contexto(config(**cfg), "doaj", relogio))


def test_normaliza_registro_real(relogio):
    r = adaptador(relogio).normalizar(resultados("busca.json")[0])
    assert r.id_na_base == "000122f776cb4f27b0f575971a4bed38" and r.doi == "10.46481/jnsps.2025.2273"
    assert r.url_pagina.startswith("https://journal.nsps.org.ng/")
    assert r.autores[1] == "christopher ifeanyi Eke"  # espaços duplicados colapsados
    assert r.ano == 2025 and r.data_publicacao == "2025-02" and r.tipo == "artigo" and r.idioma == "en"
    assert r.issn == ["2714-2817", "2714-4704"] and r.volume == "7" and r.numero == "1"
    assert r.acesso_aberto is True and r.extras == {"x_doaj_pais_periodico": "NG", "x_doaj_assunto_lcc": ["QC1-999"]}


def test_todas_as_fixtures(relogio):
    a = adaptador(relogio)
    regs = [a.normalizar(x) for p in glob.glob(str(FIXTURES / "doaj" / "*.json"))
            if "_index" not in p and "limite" not in p for x in json.load(open(p))["results"]]
    assert len(regs) == 25 and all(r.doi and r.titulo for r in regs)
    assert any(r.autores_orcid and r.autores_orcid[0].startswith("0000-") for r in regs)
    assert any(r.url_pdf for r in regs)


def test_idioma_local_usa_idiomas_do_periodico(relogio):
    a = adaptador(relogio, filtros={"idiomas": ["fr"]})
    w = resultados("busca.json")[0]
    w = {**w, "bibjson": {**w["bibjson"], "journal": {**w["bibjson"]["journal"], "language": ["EN", "FR"]}}}
    r = a.normalizar(w)
    assert r.idioma is None and a.idiomas_do_registro(r) == ["en", "fr"]
    f = Filtros(idiomas=["fr"])
    assert aplicar_locais(r, a.suporta(f), f, analisar("x"), a.idiomas_do_registro)


def test_plano_e_traducao(relogio):
    a = adaptador(relogio, query='"machine learning"', filtros={"ano_de": 2021, "campo_busca": "titulo_resumo",
                                                                 "somente_oa": True, "tipos": ["artigo"]})
    p = a.suporta(a.ctx.config.filtros)
    assert p.incompativel is None and not p.locais and len(p.atendidos) == 2
    assert a.traduzir(analisar(a.ctx.config.query), p) == \
        '((bibjson.title:"machine learning" OR bibjson.abstract:"machine learning")) AND bibjson.year:[2021 TO *]'
    assert "incompatíveis" in a.suporta(Filtros(tipos=["revisao"])).incompativel


@respx.mock
async def test_buscar_por_pagina(relogio):
    def paginas(request):
        nome = "busca.json" if request.url.params["page"] == "1" else "pagina2.json"
        return httpx.Response(200, text=fixture("doaj", nome))

    rota = respx.get(url__startswith=RAIZ).mock(side_effect=paginas)
    a = adaptador(relogio, query='"machine learning" AND x:y')
    regs = await coletar(a, analisar(a.ctx.config.query), a.suporta(a.ctx.config.filtros), 7)
    assert len(regs) == 7 and rota.call_count == 2
    assert unquote(rota.calls[0].request.url.path).endswith('/"machine learning" AND x\\:y')


@respx.mock
async def test_para_no_limite_de_1000(relogio):
    pagina = json.loads(fixture("doaj", "busca.json"))
    rota = respx.get(url__startswith=RAIZ).mock(
        side_effect=lambda req: httpx.Response(200, json={**pagina, "results": [
            {**x, "id": f"{req.url.params['page']}-{i}"} for i, x in enumerate(pagina["results"] * 20)]}))
    a = adaptador(relogio, max_artigos_por_base=2000)
    regs = await coletar(a, analisar("x"), a.suporta(a.ctx.config.filtros), 2000)
    # 100 por página, até 1.000; duplicatas de DOI (mesmos 5 artigos repetidos) são removidas
    assert rota.call_count == 10 and len(regs) == 5
    assert any("1000" in x for x in a.ctx.estat.avisos)
