import glob
import json

import httpx
import respx

from coletor.bases.core import URL, Core
from coletor.consulta import analisar
from coletor.segredos import Credenciais
from conftest import CRED, FIXTURES, coletar, config, contexto, fixture


def resultados(nome):
    return json.loads(fixture("core", nome))["results"]


def adaptador(relogio, cred=CRED, **cfg):
    return Core(contexto(config(**cfg), "core", relogio, cred))


def test_normaliza_registro_real(relogio):
    r = adaptador(relogio).normalizar(resultados("busca.json")[1])
    assert r.id_na_base == "8916209" and r.titulo == "The need for open source software in machine learning"
    assert r.autores[0] == "Ratsch, Gunnar" and r.ano == 2007 and r.idioma == "en" and r.editora == "JMLR"
    assert r.url_pdf == "https://core.ac.uk/download/29197653.pdf" and r.acesso_aberto is True
    assert r.extras["x_core_provedores"][0] == "Research Commons@Waikato"
    assert r.extras["x_core_data_deposito"] == "2016-10-09"


def test_sem_chave_texto_completo_vazio_com_aviso(relogio):
    a = adaptador(relogio)
    for w in resultados("busca.json"):
        r = a.normalizar(w)
        assert r.texto_completo is None and r.avisos == ["texto_completo_requer_chave"]
    sem_enriq = adaptador(relogio, enriquecimento={"texto_completo": False}).normalizar(resultados("busca.json")[0])
    assert sem_enriq.avisos == [] and sem_enriq.texto_completo is None


def test_com_texto_disponivel(relogio):
    w = {**resultados("busca.json")[0], "fullText": "Parágrafo 1\r\nParágrafo 2"}
    r = adaptador(relogio, cred=Credenciais(CORE_API_KEY="core-teste")).normalizar(w)
    assert r.texto_completo == "Parágrafo 1\nParágrafo 2" and not r.avisos


def test_todas_as_fixtures_e_tipos(relogio):
    a = adaptador(relogio)
    regs = [a.normalizar(w) for p in glob.glob(str(FIXTURES / "core" / "*.json"))
            if "_index" not in p and "enriq" not in p for w in json.load(open(p))["results"]]
    assert len(regs) == 30 and all(r.id_na_base and r.titulo for r in regs)
    tipos = {r.tipo for r in regs}
    assert {"artigo", "conferencia"} <= tipos and "thesis" in tipos
    assert {r.idioma for r in regs} >= {"pt", "en"}


def test_traducao_com_filtros(relogio):
    a = adaptador(relogio, query='"machine learning" c++', filtros={
        "ano_de": 2021, "ano_ate": 2022, "idiomas": ["pt", "en"], "tipos": ["artigo"], "somente_oa": True,
        "campo_busca": "titulo"})
    p = a.suporta(a.ctx.config.filtros)
    assert p.locais == ["tipos"] and p.atendidos
    assert a.traduzir(analisar(a.ctx.config.query), p) == (
        r'(title:"machine learning" AND title:c\+\+) AND (yearPublished>=2021) AND (yearPublished<=2022) '
        "AND (language.code:pt OR language.code:en)")


@respx.mock
async def test_buscar_por_offset_e_header_da_chave(relogio):
    def paginas(request):
        nome = "busca.json" if request.url.params["offset"] == "0" else "pagina2.json"
        return httpx.Response(200, text=fixture("core", nome))

    rota = respx.get(URL).mock(side_effect=paginas)
    a = adaptador(relogio, cred=Credenciais(CORE_API_KEY="core-teste"))
    regs = await coletar(a, analisar("machine learning"), a.suporta(a.ctx.config.filtros), 7)
    assert len(regs) == 7 and rota.call_count == 2
    assert rota.calls[0].request.headers["Authorization"] == "Bearer core-teste"
    assert rota.calls[1].request.url.params["offset"] == "5"
    assert Core.limites_padrao(Credenciais()) == (0.5, 1) and Core.limites_padrao(Credenciais(CORE_API_KEY="x")) == (2, 1)
