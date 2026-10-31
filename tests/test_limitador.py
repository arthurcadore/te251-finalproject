import asyncio
import email.utils
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from coletor.http import CacheDisco, ClienteHTTP, ErroHTTP
from coletor.limitador import Limitador, TentativasEsgotadas, retry_after
from conftest import CHAVE_FALSA, opcoes_rapidas

URL = "https://api.exemplo.org/busca"


def novo(relogio, taxa=1.0, conc=1, **kw) -> Limitador:
    return Limitador("teste", taxa, conc, **{**opcoes_rapidas(relogio), **kw})


async def chamar(lim: Limitador, cliente: httpx.AsyncClient):
    return await lim.executar(lambda: cliente.get(URL))


@respx.mock
async def test_429_com_retry_after_reduz_taxa_e_repete(relogio):
    rota = respx.get(URL).mock(side_effect=[httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200)])
    lim = novo(relogio, taxa=2.0)
    async with httpx.AsyncClient() as c:
        r = await chamar(lim, c)
    assert r.status_code == 200 and rota.call_count == 2
    assert lim.n_429 == 1 and lim.taxa == 1.0
    assert 7.0 in relogio.esperas


@respx.mock
async def test_429_sem_retry_after_usa_backoff(relogio):
    respx.get(URL).mock(side_effect=[httpx.Response(429), httpx.Response(429), httpx.Response(200)])
    lim = novo(relogio)
    async with httpx.AsyncClient() as c:
        await chamar(lim, c)
    backoffs = [e for e in relogio.esperas if e in (2, 4)]
    assert backoffs == [2, 4]  # jitter zerado nos testes


@respx.mock
async def test_5xx_repete_sem_reduzir_taxa(relogio):
    respx.get(URL).mock(side_effect=[httpx.Response(503), httpx.Response(502), httpx.Response(200)])
    lim = novo(relogio, taxa=3.0)
    async with httpx.AsyncClient() as c:
        r = await chamar(lim, c)
    assert r.status_code == 200 and lim.taxa == 3.0 and lim.n_429 == 0 and lim.n_chamadas == 3


@respx.mock
async def test_timeout_e_erro_de_conexao_repetem(relogio):
    respx.get(URL).mock(side_effect=[httpx.ConnectTimeout("t"), httpx.ConnectError("c"), httpx.Response(200)])
    lim = novo(relogio)
    async with httpx.AsyncClient() as c:
        assert (await chamar(lim, c)).status_code == 200


@respx.mock
async def test_seis_tentativas_e_piso_da_taxa(relogio):
    rota = respx.get(URL).mock(return_value=httpx.Response(429))
    lim = novo(relogio, taxa=1.0)
    async with httpx.AsyncClient() as c:
        with pytest.raises(TentativasEsgotadas) as e:
            await chamar(lim, c)
    assert rota.call_count == 6 and lim.n_429 == 6
    assert lim.taxa == pytest.approx(0.1)  # 1 → 0,5 → 0,25 → 0,125 → piso 0,1
    assert "429" in str(e.value)


@respx.mock
async def test_4xx_nao_repete(relogio):
    rota = respx.get(URL).mock(return_value=httpx.Response(404))
    lim = novo(relogio)
    async with httpx.AsyncClient() as c:
        r = await chamar(lim, c)
    assert r.status_code == 404 and rota.call_count == 1


@respx.mock
async def test_recuperacao_apos_20_sucessos_sem_passar_da_inicial(relogio):
    respx.get(URL).mock(side_effect=[httpx.Response(429)] + [httpx.Response(200)] * 60)
    lim = novo(relogio, taxa=4.0)
    async with httpx.AsyncClient() as c:
        await chamar(lim, c)  # 429 e depois 200: 1º sucesso
        assert lim.taxa == 2.0
        for _ in range(18):
            await chamar(lim, c)
        assert lim.taxa == 2.0
        await chamar(lim, c)  # 20º sucesso seguido
        assert lim.taxa == 2.5
        for _ in range(40):
            await chamar(lim, c)
    assert lim.taxa == pytest.approx(3.90625)  # 2,5 × 1,25 × 1,25
    assert lim.taxa <= lim.taxa_inicial


@respx.mock
async def test_parar_interrompe_429(relogio):
    rota = respx.get(URL).mock(return_value=httpx.Response(429))
    lim = novo(relogio)
    async with httpx.AsyncClient() as c:
        r = await lim.executar(lambda: c.get(URL), parar=lambda resp: True)
    assert r.status_code == 429 and rota.call_count == 1


@respx.mock
async def test_intervalo_entre_requisicoes(relogio):
    respx.get(URL).mock(return_value=httpx.Response(200))
    lim = novo(relogio, taxa=2.0)
    async with httpx.AsyncClient() as c:
        for _ in range(4):
            await chamar(lim, c)
    assert relogio.esperas == [0.5, 0.5, 0.5]
    assert relogio.t == pytest.approx(1.5)


async def test_semaforo_limita_concorrencia():
    em_voo = maximo = 0

    async def handler(request):
        nonlocal em_voo, maximo
        em_voo += 1
        maximo = max(maximo, em_voo)
        await asyncio.sleep(0.01)
        em_voo -= 1
        return httpx.Response(200)

    lim = Limitador("teste", 1000, 2)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        await asyncio.gather(*(lim.executar(lambda: c.get(URL)) for _ in range(8)))
    assert maximo == 2


def test_retry_after_formatos():
    assert retry_after(httpx.Response(429, headers={"Retry-After": "12"})) == 12
    assert retry_after(httpx.Response(429, headers={"Retry-After": "99999"})) == 300
    data = email.utils.format_datetime(datetime.now(timezone.utc) + timedelta(seconds=30), usegmt=True)
    assert 25 <= retry_after(httpx.Response(429, headers={"Retry-After": data})) <= 31
    assert retry_after(httpx.Response(429)) is None


# ---------------------------------------------------------------- cliente HTTP


@respx.mock
async def test_cliente_remove_segredos_da_url_e_usa_user_agent(relogio):
    rota = respx.get(URL).mock(return_value=httpx.Response(200, json={"ok": 1}))
    cli = ClienteHTTP("teste", novo(relogio), email="a@b.org")
    r = await cli.get(URL, params={"q": "x", "api_key": CHAVE_FALSA, "mailto": "a@b.org"})
    await cli.fechar()
    assert CHAVE_FALSA not in r.url and "mailto" not in r.url and "q=x" in r.url
    assert rota.calls[0].request.headers["User-Agent"] == "coletor-artigos/1.0 (mailto:a@b.org)"


@respx.mock
async def test_cliente_erro_4xx_sem_segredo(relogio):
    respx.get(URL).mock(return_value=httpx.Response(401, text=f"chave {CHAVE_FALSA} inválida"))
    cli = ClienteHTTP("teste", novo(relogio))
    with pytest.raises(ErroHTTP) as e:
        await cli.get(URL, params={"api_key": CHAVE_FALSA})
    await cli.fechar()
    assert e.value.status == 401 and CHAVE_FALSA not in str(e.value)


@respx.mock
async def test_cache_em_disco(relogio, tmp_path):
    rota = respx.get(URL).mock(return_value=httpx.Response(200, text="conteúdo"))
    cache = CacheDisco(tmp_path)
    cli = ClienteHTTP("teste", novo(relogio), cache=cache)
    a = await cli.get(URL, params={"q": "1", "api_key": CHAVE_FALSA})
    b = await cli.get(URL, params={"q": "1", "api_key": CHAVE_FALSA})
    c = await cli.get(URL, params={"q": "2"})
    await cli.fechar()
    assert rota.call_count == 2 and b.do_cache and b.texto == a.texto and not c.do_cache
    assert cli.n_do_cache == 1
    gravados = "".join(p.read_text() for p in tmp_path.rglob("*.json"))
    assert CHAVE_FALSA not in gravados


@respx.mock
async def test_cache_expira(relogio, tmp_path):
    respx.get(URL).mock(return_value=httpx.Response(200, text="x"))
    cache = CacheDisco(tmp_path, ttl_s=-1)
    cli = ClienteHTTP("teste", novo(relogio), cache=cache)
    await cli.get(URL)
    assert not (await cli.get(URL)).do_cache
    await cli.fechar()


def test_retry_after_iso_do_core():
    futuro = (datetime.now(timezone.utc) + timedelta(seconds=20)).strftime("%Y-%m-%dT%H:%M:%S+0000")
    assert 15 <= retry_after(httpx.Response(429, headers={"x-ratelimit-retry-after": futuro})) <= 21
    passado = "2026-01-01T00:00:00+0000"
    assert retry_after(httpx.Response(429, headers={"x-ratelimit-retry-after": passado})) is None


def test_suite_offline_bloqueia_rede():
    with pytest.raises(RuntimeError, match="rede"):
        httpx.get("https://api.openalex.org/works", timeout=2)
