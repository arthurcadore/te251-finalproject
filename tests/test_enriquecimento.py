"""Enriquecimento (seção 8.1), a partir das respostas reais gravadas no teste prático."""

import csv
import json
import logging
import re

import httpx
import pytest
import respx

from coletor.bases.core import Core
from coletor.bases.crossref import Crossref
from coletor.bases.europepmc import EuropePMC
from coletor.bases.openalex import OpenAlex
from coletor.bases.pubmed import PubMed
from coletor.bases.semantic_scholar import SemanticScholar
from coletor.config import Enriquecimento
from coletor.enriquecimento import europepmc as epmc
from coletor.enriquecimento import openalex_ids
from coletor.enriquecimento.opencitations import RAIZ as OC, Indisponivel, OpenCitations, enriquecer, id_citado
from coletor.http import ClienteHTTP
from coletor.limitador import Limitador
from coletor.modelo import Registro
from coletor.orquestrador import executar
from coletor.segredos import Credenciais
from conftest import CRED, config, contexto, fixture, opcoes_rapidas

TUDO = Enriquecimento()
LOG = logging.getLogger("coletor.teste")
DOI = "10.1038/nature14539"


def oc_cliente(relogio, token="") -> OpenCitations:
    lim = Limitador("opencitations", 100, 3, **opcoes_rapidas(relogio))
    return OpenCitations(ClienteHTTP("opencitations", lim, logger=LOG), token)


def mock_oc():
    respx.get(OC + f"references/doi:{DOI}").mock(
        return_value=httpx.Response(200, text=fixture("opencitations", "referencias_doi_conhecido.json")))
    respx.get(OC + f"citation-count/doi:{DOI}").mock(
        return_value=httpx.Response(200, text=fixture("opencitations", "citation_count_doi_conhecido.json")))
    respx.get(url__startswith=OC + "references/").mock(return_value=httpx.Response(200, json=[]))
    respx.get(url__startswith=OC + "citation-count/").mock(return_value=httpx.Response(200, json=[{"count": "0"}]))


def reg(**kw) -> Registro:
    return Registro(base="arxiv", id_na_base=kw.pop("id_na_base", "1"), **kw)


# ---------------------------------------------------------------- OpenCitations


def test_id_citado():
    assert id_citado("omid:br/1 doi:10.1021/CI500747N openalex:W1 pmid:2") == "10.1021/ci500747n"
    assert id_citado("omid:br/1 pmid:25635324") == "pmid:25635324"
    assert id_citado("omid:br/9") == "omid:br/9"


@respx.mock
async def test_opencitations_referencias_e_citacoes(relogio):
    mock_oc()
    oc = oc_cliente(relogio, token="tok-oc")
    refs = await oc.referencias(f"doi:{DOI}")
    assert len(refs) == 40 and "10.1021/ci500747n" in refs
    assert await oc.citacoes(f"doi:{DOI}") == 73495
    assert respx.calls[0].request.headers["authorization"] == "tok-oc"


@respx.mock
async def test_enriquecer_preenche_so_o_que_falta(relogio):
    mock_oc()
    com_doi, sem_id = reg(doi=DOI), reg(id_na_base="2")
    ja_tem = reg(id_na_base="3", doi=DOI, referencias=["x"], fonte_referencias="nativa", n_citacoes=5)
    await enriquecer([com_doi, sem_id, ja_tem], oc_cliente(relogio), LOG)
    assert com_doi.fonte_referencias == "opencitations" and com_doi.n_referencias == 40
    assert com_doi.n_citacoes == 73495 and com_doi.fonte_citacoes == "opencitations"
    assert sem_id.fonte_referencias == "nenhuma" and sem_id.n_citacoes is None
    assert ja_tem.referencias == ["x"] and ja_tem.n_citacoes == 5
    assert len(respx.calls) == 2


@respx.mock
async def test_pmid_quando_nao_ha_doi(relogio):
    rota = respx.get(OC + "references/pmid:26017442").mock(
        return_value=httpx.Response(200, text=fixture("opencitations", "referencias_pmid_conhecido.json")))
    respx.get(url__startswith=OC + "citation-count/").mock(return_value=httpx.Response(200, json=[{"count": "3"}]))
    r = reg(pmid="26017442")
    await enriquecer([r], oc_cliente(relogio), LOG, usar_pmid=True)
    assert rota.called and r.fonte_referencias == "opencitations" and r.n_citacoes == 3
    r2 = reg(pmid="26017442")
    await enriquecer([r2], oc_cliente(relogio), LOG)  # sem usar_pmid: nada
    assert r2.fonte_referencias == "nenhuma"


@respx.mock
async def test_disjuntor_quando_opencitations_cai(relogio):
    rota = respx.get(url__startswith=OC).mock(return_value=httpx.Response(503))
    oc = oc_cliente(relogio)
    regs = [reg(id_na_base=str(i), doi=f"10.1/{i}") for i in range(5)]
    await enriquecer(regs, oc, LOG)
    assert oc.indisponivel and all("enriquecimento_falhou" in r.avisos for r in regs)
    assert rota.call_count <= 6 * 3  # no máximo as retentativas das chamadas já em voo
    with pytest.raises(Indisponivel):
        await oc.referencias("doi:10.1/x")


# ---------------------------------------------------------------- OpenAlex


def _ids_doi(request):
    return httpx.Response(200, text=fixture("openalex", "enriq_ids_para_doi.json"),
                          headers={"x-ratelimit-remaining-usd": "0.9"})


@respx.mock
async def test_openalex_converte_ids_em_doi_com_cache(relogio):
    rota = respx.get("https://api.openalex.org/works").mock(side_effect=_ids_doi)
    w = json.loads(fixture("openalex", "busca.json"))["results"]
    a = OpenAlex(contexto(config(), "openalex", relogio))
    regs = [a.normalizar(x) for x in w]
    await a.aplicar_enriquecimento(regs, TUDO)
    r = regs[0]
    assert "10.1038/323533a0" in r.referencias or any(x.startswith("10.") for x in r.referencias + r.relacionados)
    assert any(x.startswith("openalex:W") for x in r.relacionados + r.referencias)  # sem DOI no lote gravado
    p = rota.calls[0].request.url.params
    assert p["select"] == "id,doi" and p["filter"].startswith("openalex_id:W") and p["filter"].count("|") <= 99
    n = rota.call_count
    regs2 = [a.normalizar(x) for x in w]
    await a.aplicar_enriquecimento(regs2, TUDO)
    assert rota.call_count == n and regs2[0].referencias == r.referencias  # tudo veio do cache
    assert a.ctx.estat.enriquecidos >= 1


@respx.mock
async def test_openalex_lotes_de_100(relogio):
    rota = respx.get("https://api.openalex.org/works").mock(return_value=httpx.Response(200, json={"results": []}))
    regs = [Registro(base="openalex", id_na_base="W0", referencias=[f"openalex:W{i}" for i in range(150)])]
    await openalex_ids.resolver(regs, ClienteHTTP("openalex", Limitador("o", 100, 1, **opcoes_rapidas(relogio))),
                                "k", {}, LOG, lambda h: False)
    assert rota.call_count == 2 and regs[0].referencias[0] == "openalex:W0"


@respx.mock
async def test_openalex_orcamento_esgotado_na_conversao(relogio):
    respx.get("https://api.openalex.org/works").mock(
        return_value=httpx.Response(429, headers={"x-ratelimit-remaining-usd": "0"}))
    a = OpenAlex(contexto(config(), "openalex", relogio))
    regs = [a.normalizar(json.loads(fixture("openalex", "busca.json"))["results"][1])]
    await a.aplicar_enriquecimento(regs, TUDO)
    assert regs[0].avisos == ["enriquecimento_falhou"] and any("orçamento" in x for x in a.ctx.estat.avisos)
    assert all(x.startswith("openalex:") for x in regs[0].relacionados)


# ---------------------------------------------------------------- Semantic Scholar


@respx.mock
async def test_s2_paper_batch(relogio):
    rota = respx.post("https://api.semanticscholar.org/graph/v1/paper/batch").mock(
        return_value=httpx.Response(200, text=fixture("semantic_scholar", "enriq_batch_referencias.json")))
    a = SemanticScholar(contexto(config(), "semantic_scholar", relogio, Credenciais(S2_API_KEY="s2")))
    regs = [a.normalizar(p) for p in json.loads(fixture("semantic_scholar", "busca_campos_completos.json"))["data"]]
    await a.aplicar_enriquecimento(regs, TUDO)
    corpo = json.loads(rota.calls[0].request.content)
    assert corpo["ids"] == [r.id_na_base for r in regs] and rota.calls[0].request.headers["x-api-key"] == "s2"
    refs = [x for r in regs for x in r.referencias]
    assert len(refs) > 300 and any(x.startswith("s2:") for x in refs) and any(x.startswith("10.") for x in refs)
    assert regs[0].fonte_referencias == "nativa" and regs[0].referencias[0] == "10.1136/bmj-2023-074821"


@respx.mock
async def test_s2_batch_com_429_mantem_registros_com_aviso(relogio):
    respx.post("https://api.semanticscholar.org/graph/v1/paper/batch").mock(return_value=httpx.Response(429))
    a = SemanticScholar(contexto(config(), "semantic_scholar", relogio))
    regs = [a.normalizar(p) for p in json.loads(fixture("semantic_scholar", "busca_campos_completos.json"))["data"]]
    out = await a.aplicar_enriquecimento(regs, TUDO)
    assert len(out) == 5 and all(r.avisos == ["enriquecimento_falhou"] for r in out)


# ---------------------------------------------------------------- Europe PMC


def test_jats_para_texto():
    t = epmc.jats_para_texto(fixture("europepmc", "enriq_texto_completo.xml"))
    assert t.startswith("Main\nSubseasonal forecasts") and t.count("\n") > 100
    assert not re.search(r"</?[a-zA-Z]", t) and "mml" not in t  # "P < 0.05" é texto legítimo
    assert epmc.jats_para_texto("<article><front/></article>") is None


@respx.mock
async def test_europepmc_referencias_e_texto_completo(relogio):
    raiz = "https://www.ebi.ac.uk/europepmc/webservices/rest/"
    respx.get(raiz + "MED/42955678/references").mock(
        return_value=httpx.Response(200, text=fixture("europepmc", "enriq_referencias.json")))
    respx.get(raiz + "PMC13686947/fullTextXML").mock(
        return_value=httpx.Response(200, text=fixture("europepmc", "enriq_texto_completo.xml")))
    a = EuropePMC(contexto(config(), "europepmc", relogio))
    com_refs = next(x for x in json.loads(fixture("europepmc", "busca.json"))["resultList"]["result"]
                    if x["id"] == "42955678")
    oa = json.loads(fixture("europepmc", "busca_oa_pmc.json"))["resultList"]["result"][0]
    regs = [a.normalizar(com_refs), a.normalizar({**oa, "hasReferences": "N"})]
    await a.aplicar_enriquecimento(regs, TUDO)
    assert regs[0].n_referencias == 10 and regs[0].referencias[0] == "pmid:22094949"
    assert regs[0].fonte_referencias == "nativa"
    assert regs[1].texto_completo.startswith("Main") and a.ctx.estat.enriquecidos == 2
    sem = [a.normalizar(com_refs)]
    await a.aplicar_enriquecimento(sem, Enriquecimento(referencias=False, texto_completo=False))
    assert sem[0].referencias == []


@respx.mock
async def test_europepmc_falha_em_um_artigo_nao_afeta_outro(relogio):
    raiz = "https://www.ebi.ac.uk/europepmc/webservices/rest/"
    respx.get(url__startswith=raiz).mock(return_value=httpx.Response(404))
    a = EuropePMC(contexto(config(), "europepmc", relogio))
    oa = json.loads(fixture("europepmc", "busca_oa_pmc.json"))["resultList"]["result"][0]
    regs = [a.normalizar(oa)]
    await a.aplicar_enriquecimento(regs, TUDO)
    assert regs[0].avisos == ["enriquecimento_falhou"] and regs[0].titulo


# ---------------------------------------------------------------- CORE, Crossref, PubMed


@respx.mock
async def test_core_texto_completo_por_works_com_chave(relogio):
    obra = {**json.loads(fixture("core", "enriq_work.json")), "fullText": "Texto\r\ncompleto"}
    rota = respx.get("https://api.core.ac.uk/v3/works/8916209").mock(return_value=httpx.Response(200, json=obra))
    cred = Credenciais(CORE_API_KEY="core-k")
    ctx = contexto(config(), "core", relogio, cred)
    a = Core(ctx)
    w = {**json.loads(fixture("core", "busca.json"))["results"][1], "fullText": None}
    regs = [a.normalizar(w)]
    await a.aplicar_enriquecimento(regs, TUDO)
    assert regs[0].texto_completo == "Texto\ncompleto" and rota.calls[0].request.headers["Authorization"] == "Bearer core-k"


async def test_core_sem_chave_nao_busca_texto(relogio):
    a = Core(contexto(config(), "core", relogio, Credenciais()))
    regs = [a.normalizar(json.loads(fixture("core", "busca.json"))["results"][1])]
    await a.aplicar_enriquecimento(regs, TUDO)  # sem OpenCitations no contexto e sem chave: nenhuma chamada
    assert regs[0].avisos == ["texto_completo_requer_chave"]


@respx.mock
async def test_crossref_usa_opencitations_so_sem_referencias_nativas(relogio):
    rota = respx.get(url__startswith=OC).mock(return_value=httpx.Response(200, json=[]))
    ctx = contexto(config(), "crossref", relogio)
    ctx.opencitations = oc_cliente(relogio)
    a = Crossref(ctx)
    itens = json.loads(fixture("crossref", "filtro_com_referencias.json"))["message"]["items"]
    regs = [a.normalizar(i) for i in itens]
    sem = [r for r in regs if not r.referencias]
    await a.aplicar_enriquecimento(regs, TUDO)
    pedidos = [str(c.request.url) for c in rota.calls]
    assert len(pedidos) == len(sem) and all("/references/" in p for p in pedidos)  # sem citation-count


@respx.mock
async def test_pubmed_mantem_referencias_nativas(relogio):
    mock_oc()
    ctx = contexto(config(), "pubmed", relogio)
    ctx.opencitations = oc_cliente(relogio)
    a = PubMed(ctx)
    regs = a.analisar_efetch(fixture("pubmed", "efetch_indexados.xml"))
    nativas = {r.pmid: list(r.referencias) for r in regs if r.referencias}
    await a.aplicar_enriquecimento(regs, TUDO)
    assert all(r.referencias == nativas[r.pmid] and r.fonte_referencias == "nativa" for r in regs if r.pmid in nativas)
    assert all(r.n_citacoes == 0 and r.fonte_citacoes == "opencitations" for r in regs)


# ---------------------------------------------------------------- de ponta a ponta


@respx.mock
async def test_execucao_com_enriquecimento(tmp_path, relogio):
    def openalex(request):
        if "cursor" in request.url.params:
            return httpx.Response(200, text=fixture("openalex", "busca.json"), headers={"x-ratelimit-remaining-usd": "0.9"})
        return _ids_doi(request)

    respx.get("https://api.openalex.org/works").mock(side_effect=openalex)
    respx.get("https://export.arxiv.org/api/query").mock(return_value=httpx.Response(200, text=fixture("arxiv", "busca.xml")))
    respx.get(url__startswith=OC + "references/").mock(
        return_value=httpx.Response(200, text=fixture("opencitations", "referencias_doi_conhecido.json")))
    respx.get(url__startswith=OC + "citation-count/").mock(return_value=httpx.Response(200, json=[{"count": "7"}]))
    c = config(bases_ativas=["openalex", "arxiv"], max_artigos_por_base=5, saida={"diretorio": str(tmp_path)})
    codigo, d = await executar(c, CRED, opcoes_limitador=opcoes_rapidas(relogio))
    assert codigo == 0
    arxiv = list(csv.DictReader(open(d / "arxiv.csv", encoding="utf-8-sig", newline="")))
    com_doi = [r for r in arxiv if r["doi"]]
    assert com_doi and all(r["fonte_referencias"] == "opencitations" and r["n_citacoes"] == "7" for r in com_doi)
    assert all(r["fonte_referencias"] == "nenhuma" for r in arxiv if not r["doi"])
    rel = json.loads((d / "relatorio.json").read_text())
    assert rel["opencitations"]["chamadas_http"] == 2 * len(com_doi)
    por_base = {b["base"]: b for b in rel["bases"]}
    assert por_base["arxiv"]["enriquecidos"] == len(com_doi) and por_base["openalex"]["enriquecidos"] >= 1
    assert "OpenCitations" in (d / "relatorio.md").read_text()
