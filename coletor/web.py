"""Local-only HTTP interface for collection and LLM ranking."""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from contextlib import asynccontextmanager

import ollama
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
import yaml

from . import config as config_mod
from .orquestrador import diretorio_execucao, executar
from .ranking import DEFAULT_MODEL, gerar_ranking
from .segredos import Credenciais, registrar

ROOT = Path(__file__).resolve().parents[1]
SAIDA_PATH = ROOT / "saida"
WEB_PATH = ROOT / "web"
if not WEB_PATH.is_dir():
    WEB_PATH = Path(sys.prefix) / "share" / "coletor-artigos" / "web"
UI_PATH = WEB_PATH / "index.html"
_ollama_process: subprocess.Popen | None = None
_ollama_lock = threading.Lock()

_state_lock = threading.Lock()
_job_state: dict[str, Any] = {
    "running": False,
    "stage": "ocioso",
    "processed": 0,
    "total": 0,
    "current": "",
    "output": "",
    "error": "",
    "ollama_status": "iniciando",
    "ollama_model": DEFAULT_MODEL,
    "ollama_error": "",
}


class InterfaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: dict[str, Any]
    criteria: str = Field(min_length=1)
    model: str = Field(min_length=1, max_length=200)


def _config_padrao() -> dict[str, Any]:
    return {
        "query": "",
        "bases_ativas": ["openalex", "crossref", "pubmed", "europepmc", "core", "doaj", "arxiv", "semantic_scholar"],
        "max_artigos_por_base": 100,
        "filtros": {"ano_de": None, "ano_ate": None, "tipos": [], "idiomas": [], "somente_oa": False, "campo_busca": "tudo"},
        "enriquecimento": {"referencias": True, "resolver_ids_para_doi": True, "texto_completo": True},
        "saida": {"diretorio": "saida", "raw_json": True, "separador_lista": " | "},
        "execucao": {"max_paginas_extras_filtro_local": 10, "cache_http": True, "timeout_s": 30, "log_nivel": "INFO"},
        "limites": {},
    }


def _carregar_modelo(modelo: str) -> None:
    """Start the local Ollama daemon if needed and load a preinstalled model."""
    global _ollama_process
    with _ollama_lock:
        try:
            ollama.list()
        except Exception as erro:  # noqa: BLE001 — launch the local daemon if installed
            executavel = shutil.which("ollama")
            if not executavel:
                raise RuntimeError(
                    "Ollama não está acessível e o executável 'ollama' não foi encontrado no PATH. "
                    "Instale o Ollama e reinicie a interface."
                ) from erro
            _ollama_process = subprocess.Popen(
                [executavel, "serve"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if _ollama_process.poll() is not None:
                    raise RuntimeError("O processo 'ollama serve' encerrou durante a inicialização.")
                try:
                    ollama.list()
                    break
                except Exception:  # noqa: BLE001 — daemon still starting
                    time.sleep(0.25)
            else:
                raise RuntimeError("O Ollama não respondeu em até 30 segundos após iniciar.")

        disponiveis = ollama.list().models
        nomes = {nome for item in disponiveis if (nome := getattr(item, "model", None))}
        if modelo not in nomes and f"{modelo}:latest" not in nomes:
            raise RuntimeError(
                f"O modelo {modelo!r} não está instalado no Ollama. Instale-o com 'ollama pull {modelo}'."
            )
        ollama.generate(
            model=modelo,
            prompt="Responda apenas: pronto",
            options={"num_predict": 1},
            keep_alive=-1,
        )


def _iniciar_ollama() -> None:
    _atualizar_estado(ollama_status="iniciando", ollama_model=DEFAULT_MODEL, ollama_error="")
    try:
        _carregar_modelo(DEFAULT_MODEL)
        _atualizar_estado(ollama_status="pronto")
    except Exception as erro:  # noqa: BLE001 — keep web server alive to display setup error
        _atualizar_estado(ollama_status="erro", ollama_error=f"{type(erro).__name__}: {erro}")


@asynccontextmanager
async def lifespan(_: FastAPI):
    load_dotenv(ROOT / ".env")
    threading.Thread(target=_iniciar_ollama, daemon=True).start()
    yield
    global _ollama_process
    if _ollama_process is not None and _ollama_process.poll() is None:
        with contextlib.suppress(ProcessLookupError):
            _ollama_process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            _ollama_process.wait(timeout=5)
        _ollama_process = None


app = FastAPI(title="Coletor de artigos — interface local", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=WEB_PATH), name="assets")


def _validar_configuracao(payload: InterfaceRequest) -> config_mod.Config:
    try:
        configuracao = config_mod.Config.model_validate(payload.config)
    except Exception as erro:
        raise HTTPException(status_code=422, detail=f"Configuração inválida: {erro}") from erro
    if not configuracao.query:
        raise HTTPException(status_code=422, detail="Informe uma consulta de busca.")
    if not configuracao.bases_ativas:
        raise HTTPException(status_code=422, detail="Selecione ao menos uma base de busca.")
    criteria = payload.criteria.strip()
    model = payload.model.strip()
    if not criteria:
        raise HTTPException(status_code=422, detail="Informe os critérios de triagem.")
    if not model:
        raise HTTPException(status_code=422, detail="Informe o nome do modelo Ollama.")
    configuracao.saida.diretorio = str(SAIDA_PATH)
    return configuracao


def _atualizar_estado(**valores: Any) -> None:
    with _state_lock:
        _job_state.update(valores)


def _executar_job(configuracao: config_mod.Config, criteria: str, model: str) -> None:
    _atualizar_estado(stage="carregando modelo", processed=0, total=0, current="", output="", error="")
    try:
        load_dotenv(ROOT / ".env")
        pasta_saida = diretorio_execucao(configuracao, datetime.now())
        (pasta_saida / "config.yaml").write_text(
            yaml.safe_dump(configuracao.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        (pasta_saida / "criterios.txt").write_text(criteria.rstrip() + "\n", encoding="utf-8")
        _carregar_modelo(model)
        _atualizar_estado(ollama_status="pronto", ollama_model=model, ollama_error="")
        _atualizar_estado(stage="buscando artigos")
        credenciais = Credenciais.do_ambiente()
        registrar(credenciais)
        codigo, pasta_saida = asyncio.run(executar(configuracao, credenciais, dir_saida_override=pasta_saida))
        if codigo != 0:
            raise RuntimeError("A busca terminou sem sucesso em nenhuma base; consulte o relatório da execução.")

        consolidado = pasta_saida / "consolidado.csv"
        if not consolidado.exists():
            raise FileNotFoundError("A busca não produziu consolidado.csv.")

        _atualizar_estado(stage="validando e ranqueando", processed=0, total=0)

        def progresso(processado: int, total: int, titulo: str) -> None:
            _atualizar_estado(processed=processado, total=total, current=titulo)

        ranking = gerar_ranking(consolidado, criteria, modelo=model, progresso=progresso)
        _atualizar_estado(
            running=False,
            stage="concluído",
            processed=_job_state.get("total", 0),
            output=str(ranking),
            error="",
        )
    except Exception as erro:  # noqa: BLE001 — erros são reportados na interface, não encerram o servidor
        _atualizar_estado(running=False, stage="falhou", error=f"{type(erro).__name__}: {erro}")


@app.get("/", response_class=FileResponse)
def index() -> FileResponse:
    return FileResponse(UI_PATH, media_type="text/html; charset=utf-8")


@app.get("/api/history")
def history() -> list[dict[str, Any]]:
    SAIDA_PATH.mkdir(parents=True, exist_ok=True)
    pesquisas = []
    for pasta in sorted((p for p in SAIDA_PATH.iterdir() if p.is_dir() and not p.is_symlink()), reverse=True):
        arquivos = sorted(p.name for p in pasta.iterdir() if p.is_file() and not p.is_symlink())
        pesquisas.append({"id": pasta.name, "files": arquivos})
    return pesquisas


@app.get("/api/history/{research_id}/{filename}")
def history_file(research_id: str, filename: str) -> FileResponse:
    if Path(research_id).name != research_id or Path(filename).name != filename:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    caminho = SAIDA_PATH / research_id / filename
    raiz = SAIDA_PATH.resolve()
    if not caminho.is_file() or caminho.is_symlink() or not caminho.resolve().is_relative_to(raiz):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    return FileResponse(caminho, filename=filename)


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return {"config": _config_padrao(), "criteria": "", "model": DEFAULT_MODEL}


@app.post("/api/run")
def start_run(payload: InterfaceRequest) -> dict[str, str]:
    with _state_lock:
        if _job_state["running"]:
            raise HTTPException(status_code=409, detail="Já existe uma execução em andamento.")
        _job_state.update({
            "running": True,
            "stage": "validando configuração",
            "processed": 0,
            "total": 0,
            "current": "",
            "output": "",
            "error": "",
        })
    try:
        configuracao = _validar_configuracao(payload)
    except Exception:
        _atualizar_estado(running=False, stage="falhou")
        raise
    _atualizar_estado(stage="na fila")
    worker = threading.Thread(
        target=_executar_job,
        args=(configuracao, payload.criteria.strip(), payload.model.strip()),
        daemon=True,
    )
    worker.start()
    return {"message": "Busca iniciada."}


@app.get("/api/status")
def get_status() -> dict[str, Any]:
    with _state_lock:
        return dict(_job_state)
