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

    assert pagina.status_code == 200 and "Histórico de pesquisas" in pagina.text
    assert login_page.status_code == 200 and "Token de acesso" in login_page.text
    assert login_css.status_code == 200 and ".login-card" in login_css.text
    assert login_js.status_code == 200 and "/api/auth/login" in login_js.text
    assert 'id="model"' in pagina.text and "<select id=\"model\"" in pagina.text
    assert css.status_code == 200 and ".sidebar" in css.text
    assert session_css.status_code == 200 and ".logout-button" in session_css.text
    assert model_css.status_code == 200 and ".model-panel" in model_css.text
    assert js.status_code == 200 and "refreshHistory" in js.text
    assert configuracao.status_code == 200
    assert configuracao.json()["config"]["query"] == ""
    assert configuracao.json()["criteria"] == ""
    assert configuracao.json()["model"] == "qwen3.5:0.8b"
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

    def generate(consolidado, criteria, *, modelo, progresso):
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
    public = {"/login", "/api/auth/login", "/api/auth/session"}
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
