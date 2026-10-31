from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from coletor import config as config_mod
from coletor import web


async def test_interface_assets_endpoints_and_initial_state() -> None:
    transport = httpx.ASGITransport(app=web.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        pagina = await client.get("/")
        css = await client.get("/assets/styles.css")
        js = await client.get("/assets/app.js")
        configuracao = await client.get("/api/config")
        status = await client.get("/api/status")

    assert pagina.status_code == 200 and "Histórico de pesquisas" in pagina.text
    assert css.status_code == 200 and ".sidebar" in css.text
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

    assert historico.json() == [{"id": pesquisa.name, "files": ["ranking.csv"]}]
    assert arquivo.status_code == 200 and "llm_score" in arquivo.text
    assert traversal.status_code in {404, 422}


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
