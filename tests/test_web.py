from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from ollama._types import ListResponse

from coletor import cli
from coletor import config as config_mod
from coletor import web


async def test_interface_assets_endpoints_and_initial_state() -> None:
    transport = httpx.ASGITransport(app=web.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        pagina = await client.get("/")
        login_page = await client.get("/login")
        login_css = await client.get("/assets/login.css")
        login_js = await client.get("/assets/login.js")
        css = await client.get("/assets/styles.css")
        session_css = await client.get("/assets/session.css")
        model_css = await client.get("/assets/model.css")
        js = await client.get("/assets/app.js")
        configuracao = await client.get("/api/config")
        status = await client.get("/api/status")

    assert pagina.status_code == 200 and "HISTÓRICO DE PESQUISAS" in pagina.text
    assert 'id="history-list"' in pagina.text
    assert login_page.status_code == 200 and "Token de acesso" in login_page.text
    assert login_css.status_code == 200 and ".login-card" in login_css.text
    assert login_js.status_code == 200 and "/api/auth/login" in login_js.text
    assert 'id="model"' in pagina.text and "<select id=\"model\"" in pagina.text
    assert css.status_code == 200 and ".sidebar" in css.text
    assert session_css.status_code == 200 and ".logout-button" in session_css.text
    assert model_css.status_code == 200 and ".model-panel" in model_css.text
    assert js.status_code == 200 and "refreshHistory" in js.text
    assert configuracao.status_code == 200
    assert configuracao.json()["config"]["query"] == "SAR AND Agricultura"
    assert "SAR AND Agricultura" in configuracao.json()["criteria"]
    assert configuracao.json()["defaults_version"]
    assert configuracao.json()["temperature"] == 0.1
    assert configuracao.json()["model"] == "qwen3.5:0.8b"
    assert configuracao.json()["weights"] == {"aderencia": 70, "ano": 10, "citacoes": 10, "tipo": 10}
    assert configuracao.json()["type_values"]["artigo"] == 100
    assert set(configuracao.json()["type_values"]) == {"artigo", "revisao", "conferencia", "livro_capitulo", "preprint", "outros"}
    assert status.json()["running"] is False


async def test_history_lists_files_and_rejects_path_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pesquisa = tmp_path / "2026-10-31_120000_busca-teste"
    pesquisa.mkdir()
    (pesquisa / "ranking.csv").write_text("doi,llm_score\n", encoding="utf-8")
    monkeypatch.setattr(web, "SAIDA_PATH", tmp_path)

    transport = httpx.ASGITransport(app=web.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        historico = await client.get("/api/history")
        arquivo = await client.get(f"/api/history/{pesquisa.name}/ranking.csv")
        traversal = await client.get("/api/history/../README.md")

    assert historico.json() == [{"id": pesquisa.name, "query": "busca teste", "files": ["ranking.csv"]}]
    assert arquivo.status_code == 200 and "llm_score" in arquivo.text
    assert traversal.status_code in {404, 422}


async def test_models_endpoint_lists_installed_ollama_models(monkeypatch: pytest.MonkeyPatch) -> None:
    model = ListResponse.Model(model="qwen3.5:0.8b", size=1_300_000_000)
    monkeypatch.setattr(web.ollama, "list", lambda: ListResponse(models=[model]))
    transport = httpx.ASGITransport(app=web.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        response = await client.get("/api/models")

    assert response.status_code == 200
    assert response.json()["models"][0]["name"] == "qwen3.5:0.8b"


async def test_remote_login_session_logout_and_origin_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "x" * 40
    monkeypatch.setenv("COLETOR_WEB_TOKEN", token)
    transport = httpx.ASGITransport(app=web.app, client=("192.0.2.10", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="https://coletor.example") as client:
        login_redirect = await client.get("/", follow_redirects=False)
        login_page = await client.get("/login")
        unauthorized = await client.get("/api/status")
        bad_login = await client.post(
            "/api/auth/login", headers={"Origin": "https://coletor.example"}, json={"token": "wrong"}
        )
        wrong_origin = await client.post(
            "/api/auth/login",
            headers={"Origin": "https://evil.example"},
            json={"token": token},
        )
        wrong_scheme = await client.post(
            "/api/auth/login",
            headers={"Origin": "http://coletor.example"},
            json={"token": token},
        )
        valid_login = await client.post(
            "/api/auth/login", headers={"Origin": "https://coletor.example"}, json={"token": token}
        )
        authenticated = await client.get("/api/status")
        logout = await client.post("/api/auth/logout", headers={"Origin": "https://coletor.example"})
        expired_session = await client.get("/api/status")

    assert login_redirect.status_code == 303 and login_redirect.headers["location"] == "/login"
    assert login_page.status_code == 200
    assert unauthorized.status_code == 401 and unauthorized.headers.get("www-authenticate") is None
    assert bad_login.status_code == 401
    assert wrong_origin.status_code == 403
    assert wrong_scheme.status_code == 403
    assert valid_login.status_code == 200
    assert "coletor_session" in valid_login.headers.get("set-cookie", "")
    assert "httponly" in valid_login.headers.get("set-cookie", "").lower()
    assert "secure" in valid_login.headers.get("set-cookie", "").lower()
    assert authenticated.status_code == 200
    assert logout.status_code == 200
    assert expired_session.status_code == 401


def test_ollama_runtime_reports_gpu_and_cpu_split() -> None:
    process = SimpleNamespace(model="qwen3.5:0.8b", size=1000, size_vram=750)
    assert web._resumo_acelerador([process], "qwen3.5:0.8b") == "75% GPU · 25% CPU"
    assert web._resumo_acelerador([], "qwen3.5:0.8b") == "nenhum modelo ativo"


def test_web_defaults_to_all_interfaces_and_requires_remote_token(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(cli, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("COLETOR_WEB_TOKEN", raising=False)
    assert cli.main(["--gui"]) == 2
    assert "COLETOR_WEB_TOKEN" in capsys.readouterr().err


def test_web_allows_loopback_without_remote_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("COLETOR_WEB_TOKEN", raising=False)
    invoked = {}
    monkeypatch.setitem(__import__("sys").modules, "uvicorn", SimpleNamespace(
        run=lambda app, **kwargs: invoked.update({"app": app, **kwargs}),
    ))

    assert cli.main(["--web", "--host", "127.0.0.1"]) == 0
    assert invoked["host"] == "127.0.0.1"


async def test_lifespan_starts_local_model(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[str] = []

    class ImmediateThread:
        def __init__(self, *, target, daemon):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(web.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(web, "_carregar_modelo", lambda model: started.append(model))
    async with web.lifespan(web.app):
        assert started == [web.DEFAULT_MODEL]
        assert web._job_state["ollama_status"] == "pronto"


def test_job_saves_yaml_and_criteria_in_research_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web, "SAIDA_PATH", tmp_path)
    monkeypatch.setattr(web, "_carregar_modelo", lambda model: None)
    monkeypatch.setattr(web, "Credenciais", SimpleNamespace(do_ambiente=lambda: object()))
    monkeypatch.setattr(web, "registrar", lambda credentials: None)

    async def execute(config, credentials, *, dir_saida_override):
        assert dir_saida_override is not None
        (dir_saida_override / "consolidado.csv").write_text("doi\n", encoding="utf-8")
        return 0, dir_saida_override

    def generate(consolidado, criteria, *, modelo, progresso, **kwargs):
        ranking = consolidado.parent / "ranking.csv"
        ranking.write_text("doi,llm_score\n", encoding="utf-8")
        return ranking

    monkeypatch.setattr(web, "executar", execute)
    monkeypatch.setattr(web, "gerar_ranking", generate)
    config = config_mod.Config.model_validate({
        "query": "busca teste",
        "bases_ativas": ["arxiv"],
        "saida": {"diretorio": str(tmp_path)},
    })

    web._executar_job(config, "Critério de inclusão", "modelo-teste")
    pesquisa = next(path for path in tmp_path.iterdir() if path.is_dir())

    assert (pesquisa / "config.yaml").is_file()
    assert "busca teste" in (pesquisa / "config.yaml").read_text(encoding="utf-8")
    assert (pesquisa / "criterios.txt").read_text(encoding="utf-8") == "Critério de inclusão\n"
    assert (pesquisa / "ranking.csv").is_file()
    assert web._job_state["stage"] == "concluído"


async def test_remote_login_over_plain_http_keeps_session(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "x" * 40
    monkeypatch.setenv("COLETOR_WEB_TOKEN", token)
    origin = {"Origin": "http://192.168.0.5:8000"}
    transport = httpx.ASGITransport(app=web.app, client=("192.168.0.20", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://192.168.0.5:8000") as client:
        login = await client.post("/api/auth/login", headers=origin, json={"token": token})
        authenticated = await client.get("/api/status")
        index = await client.get("/", follow_redirects=False)
        logout = await client.post("/api/auth/logout", headers=origin)
        after_logout = await client.get("/api/status")

    assert login.status_code == 200
    assert "secure" not in login.headers["set-cookie"].lower()
    assert authenticated.status_code == 200
    assert index.status_code == 200
    assert logout.status_code == 200 and "secure" not in logout.headers["set-cookie"].lower()
    assert after_logout.status_code == 401


async def test_every_private_route_requires_remote_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLETOR_WEB_TOKEN", "x" * 40)
    public = {"/login", "/api/auth/login", "/api/auth/session", "/api/auth/logout"}
    transport = httpx.ASGITransport(app=web.app, client=("192.0.2.10", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="https://coletor.example") as client:
        for route in web.app.routes:
            path = getattr(route, "path", "")
            if path in public or path.startswith("/assets"):
                continue
            url = path.replace("{research_id}", "x").replace("{filename}", "y")
            for method in getattr(route, "methods", None) or {"GET"}:
                if method == "HEAD":
                    continue
                headers = {"Origin": "https://coletor.example"}
                response = await client.request(method, url, headers=headers, json={}, follow_redirects=False)
                expected = 303 if url == "/" else 401
                assert response.status_code == expected, (method, url, response.status_code)


async def test_loopback_request_through_reverse_proxy_requires_session(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "x" * 40
    monkeypatch.setenv("COLETOR_WEB_TOKEN", token)
    transport = httpx.ASGITransport(app=web.app, client=("127.0.0.1", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        proxied = await client.get("/api/status", headers={"X-Real-IP": "203.0.113.9"})
        login = await client.post(
            "/api/auth/login",
            headers={"X-Forwarded-Host": "coletor.example", "Origin": "http://coletor.example"},
            json={"token": token},
        )
        direct_local = await client.get("/api/status")

    assert proxied.status_code == 401
    assert login.status_code == 200
    assert direct_local.status_code == 200


async def test_history_detail_informa_situacao_do_ranking(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web, "SAIDA_PATH", tmp_path)
    cabecalho = "doi,titulo,ano,bases,llm_score,llm_justification\n"
    completa = tmp_path / "2026-10-31_120000_completa"
    completa.mkdir()
    (completa / "ranking.csv").write_text(cabecalho + "10.1/a,A,2020,arxiv,0.9,Critério 1.\n", encoding="utf-8")
    parcial = tmp_path / "2026-10-31_130000_parcial"
    parcial.mkdir()
    (parcial / "consolidado.csv").write_text("doi,titulo,ano,bases\n10.1/b,B,2021,arxiv\n", encoding="utf-8")
    (parcial / ".ranking-abc.csv").write_text(cabecalho + "10.1/b,B,2021,arxiv,0.5,Critério 3.\n", encoding="utf-8")
    sem_ranking = tmp_path / "2026-10-31_140000_sem-ranking"
    sem_ranking.mkdir()
    (sem_ranking / "consolidado.csv").write_text("doi,titulo,ano,bases\n10.1/c,C,2022,arxiv\n", encoding="utf-8")

    transport = httpx.ASGITransport(app=web.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        respostas = {p.name: (await client.get(f"/api/history/{p.name}")).json() for p in (completa, parcial, sem_ranking)}

    assert respostas[completa.name]["ranking"] == "completo"
    assert respostas[completa.name]["articles"][0]["llm_justification"] == "Critério 1."
    assert respostas[parcial.name]["ranking"] == "parcial"
    assert respostas[parcial.name]["articles"][0]["llm_justification"] == "Critério 3."
    assert ".ranking-abc.csv" not in respostas[parcial.name]["files"]
    assert respostas[sem_ranking.name]["ranking"] == "ausente"
    assert respostas[sem_ranking.name]["articles"][0]["llm_justification"] == ""


def test_job_repassa_temperatura_ao_ranking(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web, "SAIDA_PATH", tmp_path)
    monkeypatch.setattr(web, "_carregar_modelo", lambda model: None)
    monkeypatch.setattr(web, "Credenciais", SimpleNamespace(do_ambiente=lambda: object()))
    monkeypatch.setattr(web, "registrar", lambda credentials: None)
    recebido: dict = {}

    async def execute(config, credentials, *, dir_saida_override):
        (dir_saida_override / "consolidado.csv").write_text("doi\n", encoding="utf-8")
        return 0, dir_saida_override

    def generate(consolidado, criteria, **kwargs):
        recebido.update(kwargs)
        destino = consolidado.parent / "ranking.csv"
        destino.write_text("doi,llm_score\n", encoding="utf-8")
        return destino

    monkeypatch.setattr(web, "executar", execute)
    monkeypatch.setattr(web, "gerar_ranking", generate)
    config = config_mod.Config.model_validate({
        "query": "busca teste", "bases_ativas": ["arxiv"], "saida": {"diretorio": str(tmp_path)},
    })
    web._executar_job(config, "Critério", "modelo-teste", None, 0.4)
    assert recebido["temperatura"] == 0.4


def test_interface_rejeita_temperatura_fora_da_faixa() -> None:
    with pytest.raises(ValueError):
        web.InterfaceRequest(config={}, criteria="c", model="m", temperature=1.5)


def test_montar_grafo_liga_artigos_por_referencias_compartilhadas() -> None:
    linhas = [
        {"doi": "10.1/a", "titulo": "A", "ano": "2020", "llm_score": "0.9", "referencias": "10.9/x | 10.9/y | 10.1/b"},
        {"doi": "10.1/b", "titulo": "B", "ano": "2021", "llm_score": "0.5", "referencias": "10.9/x | 10.9/z"},
        {"doi": "10.1/c", "titulo": "C", "ano": "2022", "llm_score": "0.1", "referencias": "10.9/x | 10.9/y"},
        {"doi": "10.1/d", "titulo": "D", "ano": "2022", "llm_score": "", "referencias": ""},
    ]
    grafo = web._montar_grafo(linhas)
    ids = {n["id"]: n for n in grafo["nodes"]}

    # Referências citadas por 2+ artigos viram nós; citadas uma só vez (10.9/z) ficam de fora.
    assert {n["doi"] for n in grafo["nodes"] if n["type"] == "referencia"} == {"10.9/x", "10.9/y"}
    assert ids["r:10.9/x"]["citations"] == 3
    # Citação de um artigo da própria pesquisa vira aresta entre artigos; artigo sem referências não entra.
    arestas = {(a["source"], a["target"]) for a in grafo["edges"]}
    assert ("a0", "a1") in arestas
    assert all(n["label"] != "D" for n in grafo["nodes"])
    assert grafo["articles_with_references"] == 3


async def test_history_detail_traz_tempos_e_grafo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web, "SAIDA_PATH", tmp_path)
    nova = tmp_path / "2026-11-07_120000_nova"
    nova.mkdir()
    (nova / "consolidado.csv").write_text("doi,titulo,ano,bases,referencias\n", encoding="utf-8")
    (nova / "tempos.json").write_text('{"busca_s": 12.5, "processamento_s": 80}', encoding="utf-8")
    antiga = tmp_path / "2026-10-31_120000_antiga"
    antiga.mkdir()
    (antiga / "consolidado.csv").write_text("doi,titulo,ano,bases,referencias\n", encoding="utf-8")
    (antiga / "relatorio.json").write_text('{"duracao_s": 197.1, "bases": []}', encoding="utf-8")

    transport = httpx.ASGITransport(app=web.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        nova_det = (await client.get(f"/api/history/{nova.name}")).json()
        antiga_det = (await client.get(f"/api/history/{antiga.name}")).json()
        grafo = await client.get(f"/api/history/{nova.name}/graph")
        traversal = await client.get("/api/history/..%2F..%2Fetc/graph")

    assert nova_det["timing"] == {"busca_s": 12.5, "processamento_s": 80.0}
    assert antiga_det["timing"] == {"busca_s": 197.1, "processamento_s": None}
    assert grafo.status_code == 200 and grafo.json()["nodes"] == []
    assert traversal.status_code == 404


def test_job_grava_tempos_de_busca_e_processamento(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    monkeypatch.setattr(web, "SAIDA_PATH", tmp_path)
    monkeypatch.setattr(web, "_carregar_modelo", lambda model: None)
    monkeypatch.setattr(web, "Credenciais", SimpleNamespace(do_ambiente=lambda: object()))
    monkeypatch.setattr(web, "registrar", lambda credentials: None)

    async def execute(config, credentials, *, dir_saida_override):
        (dir_saida_override / "consolidado.csv").write_text("doi\n", encoding="utf-8")
        return 0, dir_saida_override

    def generate(consolidado, criteria, **kwargs):
        destino = consolidado.parent / "ranking.csv"
        destino.write_text("doi,llm_score\n", encoding="utf-8")
        return destino

    monkeypatch.setattr(web, "executar", execute)
    monkeypatch.setattr(web, "gerar_ranking", generate)
    config = config_mod.Config.model_validate({
        "query": "busca teste", "bases_ativas": ["arxiv"], "saida": {"diretorio": str(tmp_path)},
    })
    web._executar_job(config, "Critério", "modelo-teste")
    pesquisa = next(p for p in tmp_path.iterdir() if p.is_dir())
    tempos = json.loads((pesquisa / "tempos.json").read_text(encoding="utf-8"))
    assert tempos["busca_s"] >= 0 and tempos["processamento_s"] >= 0
    assert "inicio" in tempos and "fim" in tempos


async def test_logout_local_exige_token_ate_novo_login(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "y" * 40
    monkeypatch.setenv("COLETOR_WEB_TOKEN", token)
    origin = {"Origin": "http://127.0.0.1:8000"}
    transport = httpx.ASGITransport(app=web.app, client=("127.0.0.1", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        antes = await client.get("/api/status")
        logout = await client.post("/api/auth/logout", headers=origin)
        sessao = (await client.get("/api/auth/session")).json()
        depois = await client.get("/api/status")
        index = await client.get("/", follow_redirects=False)
        errado = await client.post("/api/auth/login", headers=origin, json={"token": "z" * 40})
        login = await client.post("/api/auth/login", headers=origin, json={"token": token})
        apos_login = await client.get("/api/status")
        client.cookies.delete(web.SESSION_COOKIE)
        sem_sessao = await client.get("/api/status")

    assert antes.status_code == 200
    assert logout.status_code == 200
    assert sessao["authenticated"] is False
    assert depois.status_code == 401
    assert index.status_code == 303 and index.headers["location"] == "/login"
    assert errado.status_code == 401
    assert login.status_code == 200
    assert apos_login.status_code == 200
    # O login remove a marca de logout: o acesso local volta a dispensar token.
    assert sem_sessao.status_code == 200


async def test_logout_remoto_revoga_a_sessao(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "w" * 40
    monkeypatch.setenv("COLETOR_WEB_TOKEN", token)
    origin = {"Origin": "http://192.168.0.5:8000"}
    transport = httpx.ASGITransport(app=web.app, client=("192.168.0.20", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://192.168.0.5:8000") as client:
        await client.post("/api/auth/login", headers=origin, json={"token": token})
        cookie_antigo = client.cookies.get(web.SESSION_COOKIE)
        assert (await client.get("/api/status")).status_code == 200
        logout = await client.post("/api/auth/logout", headers=origin)
    async with httpx.AsyncClient(transport=transport, base_url="http://192.168.0.5:8000") as outro:
        outro.cookies.set(web.SESSION_COOKIE, cookie_antigo)
        reuso = await outro.get("/api/status")
        relogin = await outro.post("/api/auth/login", headers=origin, json={"token": token})
        apos = await outro.get("/api/status")

    assert logout.status_code == 200
    assert reuso.status_code == 401  # cookie copiado antes do logout não vale mais
    assert relogin.status_code == 200 and apos.status_code == 200


def test_job_repassa_valores_por_tipo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web, "SAIDA_PATH", tmp_path)
    monkeypatch.setattr(web, "_carregar_modelo", lambda model: None)
    monkeypatch.setattr(web, "Credenciais", SimpleNamespace(do_ambiente=lambda: object()))
    monkeypatch.setattr(web, "registrar", lambda credentials: None)
    recebido: dict = {}

    async def execute(config, credentials, *, dir_saida_override):
        (dir_saida_override / "consolidado.csv").write_text("doi\n", encoding="utf-8")
        return 0, dir_saida_override

    def generate(consolidado, criteria, **kwargs):
        recebido.update(kwargs)
        destino = consolidado.parent / "ranking.csv"
        destino.write_text("doi,llm_score\n", encoding="utf-8")
        return destino

    monkeypatch.setattr(web, "executar", execute)
    monkeypatch.setattr(web, "gerar_ranking", generate)
    config = config_mod.Config.model_validate({
        "query": "busca teste", "bases_ativas": ["arxiv"], "saida": {"diretorio": str(tmp_path)},
    })
    pedido = web.InterfaceRequest(
        config={}, criteria="c", model="m",
        weights={"aderencia": 60, "ano": 10, "citacoes": 10, "tipo": 20},
        type_values={"artigo": 100, "revisao": 90, "conferencia": 70, "livro_capitulo": 50, "preprint": 30, "outros": 10},
    )
    web._executar_job(config, "Critério", "modelo-teste", pedido.weights, 0.0, pedido.type_values)
    assert recebido["pesos"]["tipo"] == 0.2
    assert recebido["valores_tipo"]["preprint"] == 0.3


def test_interface_rejeita_valor_de_tipo_fora_da_faixa() -> None:
    with pytest.raises(ValueError):
        web.InterfaceRequest(config={}, criteria="c", model="m", type_values={"artigo": 150})


def _preparar_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> config_mod.Config:
    monkeypatch.setattr(web, "SAIDA_PATH", tmp_path)
    monkeypatch.setattr(web, "_carregar_modelo", lambda model: None)
    monkeypatch.setattr(web, "Credenciais", SimpleNamespace(do_ambiente=lambda: object()))
    monkeypatch.setattr(web, "registrar", lambda credentials: None)
    return config_mod.Config.model_validate({
        "query": "busca teste", "bases_ativas": ["arxiv"], "saida": {"diretorio": str(tmp_path)},
    })


def test_cancelar_durante_a_busca_interrompe_a_execucao(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    config = _preparar_job(tmp_path, monkeypatch)
    chamou_ranking = []

    async def execute(config, credentials, *, dir_saida_override):
        web._cancelamento.set()  # o usuário cancela enquanto a coleta está em andamento
        await asyncio.sleep(5)
        return 0, dir_saida_override

    monkeypatch.setattr(web, "executar", execute)
    monkeypatch.setattr(web, "gerar_ranking", lambda *a, **k: chamou_ranking.append(1))
    web._cancelamento.clear()
    web._executar_job(config, "Critério", "modelo-teste")

    assert web._job_state["stage"] == "cancelado"
    assert web._job_state["running"] is False
    assert web._job_state["research_id"]
    assert not chamou_ranking
    web._cancelamento.clear()


def test_cancelar_durante_o_ranking_mantem_checkpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from coletor import ranking

    config = _preparar_job(tmp_path, monkeypatch)

    async def execute(config, credentials, *, dir_saida_override):
        (dir_saida_override / "consolidado.csv").write_text(
            'doi,titulo,ano,resumo,n_citacoes\n10.1/a,A,2020,"Resumo A.",1\n10.1/b,B,2021,"Resumo B.",2\n',
            encoding="utf-8",
        )
        return 0, dir_saida_override

    def avaliar(*args, **kwargs):
        web._cancelamento.set()  # cancela depois do primeiro artigo
        return ranking.Screening(justification="Critério 1.", quote=args[1], match=1)

    monkeypatch.setattr(web, "executar", execute)
    monkeypatch.setattr(ranking, "screen", avaliar)
    web._cancelamento.clear()
    web._executar_job(config, "Critério", "modelo-teste")

    pesquisa = tmp_path / web._job_state["research_id"]
    assert web._job_state["stage"] == "cancelado"
    assert not (pesquisa / "ranking.csv").exists()
    assert list(pesquisa.glob(".ranking-*.csv"))  # o histórico mostra o resultado parcial
    assert "processamento_s" in (pesquisa / "tempos.json").read_text(encoding="utf-8")
    web._cancelamento.clear()


async def test_cancel_sem_execucao_retorna_409() -> None:
    transport = httpx.ASGITransport(app=web.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resposta = await client.post("/api/cancel")
    assert resposta.status_code == 409
