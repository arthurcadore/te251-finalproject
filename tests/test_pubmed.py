import json

import httpx
import respx

from coletor.bases.pubmed import EUTILS, PubMed, tipo_canonico
from coletor.consulta import analisar
from coletor.segredos import Credenciais
from conftest import CRED, EMAIL_FALSO, coletar, config, contexto, fixture


def adaptador(relogio, cred=CRED, **cfg):
    return PubMed(contexto(config(**cfg), "pubmed", relogio, cred))


def test_normaliza_artigo_real(relogio):
    r = adaptador(relogio).analisar_efetch(fixture("pubmed", "efetch_relevancia.xml"))[0]
    assert r.id_na_base == r.pmid == "30102808" and r.doi == "10.1111/joim.12822"
    assert r.url_pagina == "https://pubmed.ncbi.nlm.nih.gov/30102808/"
    assert r.titulo == "eDoctor: machine learning and the future of medicine."
    assert r.autores[0] == "G S Handelman" and r.autores_orcid[0] == "0000-0003-4275-783X"
    assert len(r.autores) == len(r.autores_orcid)
    assert r.ano == 2018 and r.data_publicacao == "2018-09-03" and r.tipo == "revisao" and r.idioma == "en"
    assert r.veiculo == "Journal of internal medicine" and r.volume == "284" and r.paginas == "603-619"
    assert "Algorithms" in r.assuntos and r.palavras_chave[0] == "artificial intelligence"
    assert r.extras["x_pubmed_mesh_qualificadores"] == ["Medicine/trends"]
    assert r.extras["x_pubmed_status"] == "MEDLINE" and r.retratado is False
    assert r.raw["pubmed_xml"].startswith("<PubmedArticle")


def test_referencias_nativas(relogio):
    regs = adaptador(relogio).analisar_efetch(fixture("pubmed", "efetch_indexados.xml"))
    com = [r for r in regs if r.referencias]
    assert len(com) == 3 and all(r.fonte_referencias == "nativa" for r in com)
    assert max(r.n_referencias for r in com) == 76
    todas = [x for r in com for x in r.referencias]
    assert any(x.startswith("10.") for x in todas) and any(x.startswith("pmid:") for x in todas)
    assert all(r.n_referencias is None for r in regs if not r.referencias)


def test_livro(relogio):
    regs = adaptador(relogio).analisar_efetch(fixture("pubmed", "efetch_livro.xml"))
    assert len(regs) == 2
    r = regs[0]
    assert r.tipo == "livro_capitulo" and r.titulo == "Peritoneal Dialysis"
    assert r.veiculo == "StatPearls" and r.editora == "StatPearls Publishing" and r.data_publicacao == "2026-01"
    assert r.autores == ["Raphaël Harrisson", "Preeti Rout"] and r.resumo


def test_todas_as_fixtures_e_ordem(relogio):
    a = adaptador(relogio)
    for nome in ("efetch.xml", "efetch_indexados.xml", "efetch_relevancia.xml"):
        regs = a.analisar_efetch(fixture("pubmed", nome))
        assert regs and all(r.pmid and r.titulo and r.ano for r in regs)
    ordem = ["34560276", "30102808"]
    assert [r.pmid for r in a.analisar_efetch(fixture("pubmed", "efetch_relevancia.xml"), ordem)][:2] == ordem


def test_tipo_canonico():
    assert tipo_canonico(["Journal Article", "Review"]) == "revisao"
    assert tipo_canonico(["Congress"]) == "conferencia"
    assert tipo_canonico(["Preprint"]) == "preprint"
    assert tipo_canonico(["Editorial"]) == "Editorial"


def test_traducao_com_filtros(relogio):
    a = adaptador(relogio, query='"machine learning" agriculture',
                  filtros={"ano_de": 2021, "ano_ate": 2022, "idiomas": ["pt", "en"], "tipos": ["revisao", "livro_capitulo"],
                           "somente_oa": True, "campo_busca": "titulo_resumo"})
    p = a.suporta(a.ctx.config.filtros)
    assert not p.locais
    assert a.traduzir(analisar(a.ctx.config.query), p) == (
        '("machine learning"[tiab] AND agriculture[tiab]) AND (2021:2022[dp]) AND (por[la] OR eng[la]) '
        "AND (Review[pt] OR booksdocs[filter]) AND (free full text[sb])")


def test_conferencia_e_idioma_desconhecido_viram_locais(relogio):
    a = adaptador(relogio, filtros={"tipos": ["conferencia"], "idiomas": ["xx"]})
    assert set(a.suporta(a.ctx.config.filtros).locais) == {"tipos", "idiomas"}


@respx.mock
async def test_buscar_esearch_efetch(relogio):
    ids = json.loads(fixture("pubmed", "esearch_sort_relevance.json"))["esearchresult"]["idlist"]
    es = respx.get(EUTILS + "esearch.fcgi").mock(
        return_value=httpx.Response(200, text=fixture("pubmed", "esearch_sort_relevance.json")))
    ef = respx.get(EUTILS + "efetch.fcgi").mock(
        return_value=httpx.Response(200, text=fixture("pubmed", "efetch_relevancia.xml")))
    a = adaptador(relogio, cred=Credenciais(CONTACT_EMAIL=EMAIL_FALSO, NCBI_API_KEY="ncbi-teste-123"))
    regs = await coletar(a, analisar("machine learning"), a.suporta(a.ctx.config.filtros), 5)
    assert [r.pmid for r in regs] == ids
    p = es.calls[0].request.url.params
    assert p["sort"] == "relevance" and p["retmax"] == "5" and p["tool"] == "coletor-artigos"
    assert p["email"] == EMAIL_FALSO and p["api_key"] == "ncbi-teste-123"
    assert ef.calls[0].request.url.params["id"] == ",".join(ids)
    assert a.ctx.estat.total_api == 288778
    assert PubMed.limites_padrao(Credenciais(NCBI_API_KEY="x")) == (9, 3)
