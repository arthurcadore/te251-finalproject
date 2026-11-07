import asyncio
import csv
import json

import httpx
import respx

from coletor import cli
from coletor.bases.arxiv import URL as URL_ARXIV
from coletor.bases.openalex import URL as URL_OPENALEX
from coletor.modelo import COLUNAS
from coletor.orquestrador import executar, slug
from coletor.segredos import Credenciais
from conftest import CHAVE_FALSA, CRED, EMAIL_FALSO, config, fixture, opcoes_rapidas


def _openalex(request):
    nome = "busca.json" if request.url.params["cursor"] == "*" else "pagina2.json"
    return httpx.Response(200, text=fixture("openalex", nome), headers={"x-ratelimit-remaining-usd": "0.9"})


def _arxiv(request):
    nome = "busca.xml" if request.url.params["start"] == "0" else "pagina2.xml"
    return httpx.Response(200, text=fixture("arxiv", nome))


SEM_ENRIQ = {"referencias": False, "resolver_ids_para_doi": False, "texto_completo": False}


def cfg(tmp_path, **kw):
    dados = dict(bases_ativas=["openalex", "arxiv"], max_artigos_por_base=10, saida={"diretorio": str(tmp_path)},
                 enriquecimento=SEM_ENRIQ)
    dados.update(kw)
    return config(**dados)


def ler_csv(p):
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))


async def rodar(c, relogio, cred=CRED):
    return await executar(c, cred, opcoes_limitador=opcoes_rapidas(relogio))


@respx.mock
async def test_execucao_completa(tmp_path, relogio):
    respx.get(URL_OPENALEX).mock(side_effect=_openalex)
    respx.get(URL_ARXIV).mock(side_effect=_arxiv)
    codigo, d = await rodar(cfg(tmp_path), relogio)
    assert codigo == 0
    assert d.parent == tmp_path and d.name.endswith("_machine-learning")
    for nome in ("openalex.csv", "arxiv.csv", "consolidado.csv", "relatorio.md", "relatorio.json", "execucao.log",
                 "config_usada.yaml"):
        assert (d / nome).exists(), nome
    oa = ler_csv(d / "openalex.csv")
    assert oa[0][:45] == COLUNAS and oa[0][45].startswith("x_openalex_") and oa[0][-1] == "raw_json"
    assert len(oa) == 11
    ax = ler_csv(d / "arxiv.csv")
    assert len(ax) == 11 and ax[0][45] == "x_arxiv_comentario"
    rel = json.loads((d / "relatorio.json").read_text())
    por_base = {b["base"]: b for b in rel["bases"]}
    assert por_base["openalex"]["status"] == "ok" and por_base["openalex"]["gravados"] == 10
    # as fixtures têm 5 registros por página
    assert por_base["openalex"]["paginas"] == 2 and por_base["openalex"]["chamadas_http"] == 2
    assert por_base["arxiv"]["total_api"] == 358373 and por_base["arxiv"]["paginas"] == 2
    md = (d / "relatorio.md").read_text()
    assert "| openalex | **ok** | 10 / 10 |" in md and "machine learning" in md
    log = (d / "execucao.log").read_text()
    assert "coletor.openalex" in log and "coletor.arxiv" in log


@respx.mock
async def test_nenhum_segredo_nas_saidas(tmp_path, relogio):
    respx.get(URL_OPENALEX).mock(side_effect=_openalex)
    respx.get(URL_ARXIV).mock(side_effect=_arxiv)
    _, d = await rodar(cfg(tmp_path, execucao={"cache_http": False, "log_nivel": "DEBUG"}), relogio)
    for arq in d.iterdir():
        texto = arq.read_text(encoding="utf-8-sig")
        assert CHAVE_FALSA not in texto and EMAIL_FALSO not in texto, arq.name
    assert "api_key" not in (d / "execucao.log").read_text()


@respx.mock
async def test_base_que_falha_nao_derruba_as_outras(tmp_path, relogio):
    respx.get(URL_OPENALEX).mock(side_effect=_openalex)
    respx.get(URL_ARXIV).mock(return_value=httpx.Response(503))
    codigo, d = await rodar(cfg(tmp_path), relogio)
    rel = {b["base"]: b for b in json.loads((d / "relatorio.json").read_text())["bases"]}
    assert codigo == 0
    assert rel["openalex"]["status"] == "ok"
    assert rel["arxiv"]["status"] == "falhou" and "tentativas esgotadas" in rel["arxiv"]["motivo"]
    assert rel["arxiv"]["chamadas_http"] == 6
    assert ler_csv(d / "arxiv.csv") == [ler_csv(d / "arxiv.csv")[0]]  # só o cabeçalho
    assert "tentativa 2/6" in (d / "execucao.log").read_text()


@respx.mock
async def test_erro_4xx_encerra_a_base_sem_repetir(tmp_path, relogio):
    rota = respx.get(URL_OPENALEX).mock(return_value=httpx.Response(403, text="forbidden"))
    _, d = await rodar(cfg(tmp_path, bases_ativas=["openalex"]), relogio)
    rel = json.loads((d / "relatorio.json").read_text())["bases"][0]
    assert rel["status"] == "falhou" and "HTTP 403" in rel["motivo"] and rota.call_count == 1


@respx.mock
async def test_sem_credencial_obrigatoria_base_pulada(tmp_path, relogio):
    respx.get(URL_ARXIV).mock(side_effect=_arxiv)
    codigo, d = await rodar(cfg(tmp_path), relogio, cred=Credenciais())
    rel = {b["base"]: b for b in json.loads((d / "relatorio.json").read_text())["bases"]}
    assert codigo == 0 and rel["openalex"]["status"] == "pulada"
    assert "OPENALEX_API_KEY" in rel["openalex"]["motivo"] and rel["arxiv"]["status"] == "ok"
    assert len(ler_csv(d / "openalex.csv")) == 1


async def test_todas_puladas_codigo_1(tmp_path, relogio):
    codigo, d = await rodar(cfg(tmp_path, bases_ativas=["scielo", "openalex"]), relogio, cred=Credenciais())
    rel = {b["base"]: b for b in json.loads((d / "relatorio.json").read_text())["bases"]}
    assert codigo == 1 and {b["status"] for b in rel.values()} == {"pulada"}
    assert "desabilitada" in rel["scielo"]["motivo"]
    assert len(ler_csv(d / "scielo.csv")) == 1 and len(ler_csv(d / "openalex.csv")) == 1


@respx.mock
async def test_filtro_incompativel_pula_base(tmp_path, relogio):
    respx.get(URL_OPENALEX).mock(side_effect=_openalex)
    _, d = await rodar(cfg(tmp_path, filtros={"tipos": ["revisao"]}), relogio)
    rel = {b["base"]: b for b in json.loads((d / "relatorio.json").read_text())["bases"]}
    assert rel["arxiv"]["status"] == "pulada" and "incompatíveis" in rel["arxiv"]["motivo"]
    assert rel["openalex"]["filtros_nativos"] == ["tipos"]


@respx.mock
async def test_bases_rodam_em_paralelo(tmp_path):
    async def lento(request):
        await asyncio.sleep(0.3)
        return _openalex(request) if "openalex" in str(request.url) else _arxiv(request)

    respx.get(URL_OPENALEX).mock(side_effect=lento)
    respx.get(URL_ARXIV).mock(side_effect=lento)
    c = cfg(tmp_path, max_artigos_por_base=5, limites={"arxiv": {"taxa_rps": 100}})
    t0 = asyncio.get_running_loop().time()
    await executar(c, CRED)
    assert asyncio.get_running_loop().time() - t0 < 0.55  # 2 × 0,3 s em série


def test_slug():
    assert slug('"Machine learning" AND agricultura de precisão!') == "machine-learning-and-agricultura-de-precisao"
    assert slug("***") == "consulta"


# ---------------------------------------------------------------- CLI


def test_cli_listar_bases(capsys, monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "x" * 10)
    assert cli.main(["--listar-bases", "--config", "config.yaml"]) == 0
    saida = capsys.readouterr().out
    assert "openalex" in saida and "definida" in saida and "x" * 10 not in saida


def test_cli_erro_de_configuracao(tmp_path, capsys):
    p = tmp_path / "c.yaml"
    p.write_text("query: x\nbases_ativas: [scopus]\n")
    assert cli.main(["--config", str(p)]) == 2
    assert "scopus" in capsys.readouterr().err


@respx.mock
def test_cli_sobrescritas_e_sem_raw_json(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENALEX_API_KEY", CHAVE_FALSA)
    respx.get(URL_ARXIV).mock(side_effect=_arxiv)
    p = tmp_path / "c.yaml"
    p.write_text(f"query: x\nsaida: {{diretorio: '{tmp_path / 'out'}'}}\nexecucao: {{cache_http: false}}\n")
    codigo = cli.main(["--config", str(p), "--query", "deep learning", "--max", "3", "--bases", "arxiv",
                       "--sem-raw-json"])
    assert codigo == 0
    d = next((tmp_path / "out").iterdir())
    linhas = ler_csv(d / "arxiv.csv")
    assert len(linhas) == 4 and "raw_json" not in linhas[0]
    assert "deep learning" in (d / "config_usada.yaml").read_text()
    assert not (d / "openalex.csv").exists()


@respx.mock
async def test_tempo_limite_da_pesquisa_encerra_bases_e_gera_consolidado(tmp_path):
    async def openalex_lento_na_pagina2(request):
        if request.url.params["cursor"] != "*":
            await asyncio.sleep(5)  # a segunda página não chega antes do prazo
        return _openalex(request)

    respx.get(URL_OPENALEX).mock(side_effect=openalex_lento_na_pagina2)
    respx.get(URL_ARXIV).mock(side_effect=_arxiv)
    c = cfg(tmp_path, max_artigos_por_base=10, limites={"arxiv": {"taxa_rps": 100}},
            execucao={"timeout_pesquisa_s": 0.6})
    t0 = asyncio.get_running_loop().time()
    codigo, d = await executar(c, CRED)
    duracao = asyncio.get_running_loop().time() - t0

    rel = {b["base"]: b for b in json.loads((d / "relatorio.json").read_text())["bases"]}
    assert duracao < 3
    assert codigo == 0
    assert rel["openalex"]["status"] == "parcial"
    assert "tempo limite da pesquisa" in rel["openalex"]["motivo"]
    assert rel["openalex"]["gravados"] > 0  # a primeira página foi mantida
    assert (d / "consolidado.csv").exists()


def test_config_timeout_pesquisa_opcional():
    assert config().execucao.timeout_pesquisa_s is None
    assert config(execucao={"timeout_pesquisa_s": 300}).execucao.timeout_pesquisa_s == 300
