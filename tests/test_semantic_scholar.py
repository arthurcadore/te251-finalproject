import json

import httpx
import respx

from coletor.bases.semantic_scholar import URL_BUSCA, SemanticScholar, tipo_canonico
from coletor.consulta import analisar
from coletor.segredos import Credenciais
from conftest import CRED, coletar, config, contexto, fixture


def dados(nome):
    return json.loads(fixture("semantic_scholar", nome))["data"]


def adaptador(relogio, cred=CRED, **cfg):
    return SemanticScholar(contexto(config(**cfg), "semantic_scholar", relogio, cred))


def test_normaliza_registro_real(relogio):
    r = adaptador(relogio).normalizar(dados("busca_campos_completos.json")[0])
    assert r.id_na_base == "1b0f498d3d314d69850046574272404c52539302"
    assert r.doi == "10.1136/bmj-2023-078378" and r.pmid == "38626948" and r.pmcid == "PMC11019967"
    assert r.titulo.startswith("TRIPOD+AI statement") and r.autores[0] == "Gary S. Collins"
    assert r.ano == 2024 and r.data_publicacao == "2024-04-16" and r.tipo == "artigo"
    assert r.veiculo == "British medical journal" and r.issn == ["1759-2151"] and r.volume == "385"
    assert r.tldr and r.resumo.startswith("The TRIPOD")
    assert r.acesso_aberto is True and r.status_oa == "hybrid" and r.licenca == "CCBY"
    assert r.url_pdf.endswith(".pdf")
    assert (r.n_citacoes, r.n_citacoes_influentes, r.n_referencias) == (4752, 188, 101)
    assert r.extras["x_s2_corpus_id"] == 269184445 and r.extras["x_s2_tipo_veiculo"] == "journal"


def test_todas_as_fixtures_e_oa_vazio(relogio):
    a = adaptador(relogio)
    regs = [a.normalizar(p) for n in ("busca_campos_completos.json", "pagina2.json", "filtro_tipo_revisao.json",
                                      "filtro_tipo_conferencia.json", "filtro_tipo_artigo.json") for p in dados(n)]
    assert len(regs) == 25 and all(r.id_na_base and r.titulo for r in regs)
    sem_pdf = [r for r in regs if r.raw["openAccessPdf"].get("url") == ""]
    assert sem_pdf and all(r.url_pdf is None and r.status_oa in (None, "closed") for r in sem_pdf)
    assert {r.tipo for r in (a.normalizar(p) for p in dados("filtro_tipo_revisao.json"))} == {"revisao"}


def test_tipo_canonico():
    assert tipo_canonico({"publicationTypes": ["JournalArticle", "Review"]}) == "revisao"
    assert tipo_canonico({"publicationTypes": ["Book", "JournalArticle", "Conference"]}) == "conferencia"
    assert tipo_canonico({"publicationTypes": None, "externalIds": {"ArXiv": "1"}}) == "preprint"
    assert tipo_canonico({"publicationTypes": ["Dataset"]}) == "Dataset"


def test_parametros_e_plano(relogio):
    a = adaptador(relogio, query='"machine-learning" AND crops',
                  filtros={"ano_de": 2021, "tipos": ["revisao", "livro_capitulo"], "somente_oa": True,
                           "idiomas": ["pt"], "campo_busca": "titulo"})
    p = a.suporta(a.ctx.config.filtros)
    assert p.nativos == ["periodo", "somente_oa", "tipos"] and p.locais == ["campo_busca"]
    assert any("idiomas" in x for x in p.ignorados)
    assert a.parametros(analisar(a.ctx.config.query), p) == {
        "query": "machine learning crops", "year": "2021-", "publicationTypes": "Review,Book,BookSection",
        "openAccessPdf": ""}


def test_preprint_vira_filtro_local(relogio):
    a = adaptador(relogio, filtros={"tipos": ["preprint", "artigo"]})
    assert a.suporta(a.ctx.config.filtros).locais == ["tipos"]


def _paginas(request):
    nome = "busca_campos_completos.json" if request.url.params["offset"] == "0" else "pagina2.json"
    return httpx.Response(200, text=fixture("semantic_scholar", nome))


@respx.mock
async def test_buscar_por_offset_e_header_da_chave(relogio):
    rota = respx.get(URL_BUSCA).mock(side_effect=_paginas)
    a = adaptador(relogio, cred=Credenciais(S2_API_KEY="chave-s2-teste"))
    regs = await coletar(a, analisar("machine learning"), a.suporta(a.ctx.config.filtros), 8)
    assert len(regs) == 8 and rota.call_count == 2
    req = rota.calls[1].request
    assert req.url.params["offset"] == "5" and req.headers["x-api-key"] == "chave-s2-teste"
    assert "tldr" in req.url.params["fields"]


@respx.mock
async def test_sem_chave_nao_envia_header(relogio):
    rota = respx.get(URL_BUSCA).mock(side_effect=_paginas)
    a = adaptador(relogio, cred=Credenciais())
    await coletar(a, analisar("x"), a.suporta(a.ctx.config.filtros), 3)
    assert "x-api-key" not in rota.calls[0].request.headers
