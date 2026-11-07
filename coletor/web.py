"""HTTP interface for collection and LLM ranking; remote clients require a token."""

from __future__ import annotations

import asyncio
import contextlib
import csv
import json
import math
import hmac
import ipaddress
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import ollama
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
import yaml

from . import config as config_mod
from .orquestrador import diretorio_execucao, executar
from .ranking import (
    DEFAULT_MODEL,
    PESOS_SCORE,
    TEMPERATURA_MAXIMA,
    TEMPERATURA_PADRAO,
    VALORES_TIPO_PADRAO,
    PesosRanking,
    ValoresTipo,
    RankingCancelado,
    gerar_ranking,
    normalizar_pesos,
    normalizar_valores_tipo,
)
from .segredos import Credenciais, registrar

ROOT = Path(__file__).resolve().parents[1]
SAIDA_PATH = ROOT / "saida"
WEB_PATH = ROOT / "web"
if not WEB_PATH.is_dir():
    WEB_PATH = Path(sys.prefix) / "share" / "coletor-artigos" / "web"
UI_PATH = WEB_PATH / "index.html"
_ollama_process: subprocess.Popen | None = None
_ollama_lock = threading.Lock()
SESSION_COOKIE = "coletor_session"
SESSION_MAX_AGE_S = 12 * 60 * 60
# Marca o navegador que saiu da sessão: a partir daí, até um novo login, nem o acesso local (loopback)
# entra sem token.
LOGOUT_COOKIE = "coletor_logout"
# Sessões encerradas por logout (nonce -> emitida_em), recusadas até expirarem.
_sessoes_revogadas: dict[str, int] = {}
_sessoes_revogadas_lock = threading.Lock()
_login_attempts: dict[str, list[float]] = {}
_login_attempts_lock = threading.Lock()

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
    "ollama_accelerator": "não informado",
    "research_id": "",
}
# Pedido de cancelamento da execução em andamento (verificado entre etapas, durante a busca e a cada artigo).
_cancelamento = threading.Event()


class ExecucaoCancelada(Exception):
    """A execução foi interrompida a pedido do usuário."""


def _verificar_cancelamento() -> None:
    if _cancelamento.is_set():
        raise ExecucaoCancelada()


async def _executar_cancelavel(*args: Any, **kwargs: Any) -> Any:
    """Roda a coleta e a interrompe se o usuário pedir o cancelamento."""
    tarefa = asyncio.ensure_future(executar(*args, **kwargs))
    while not tarefa.done():
        if _cancelamento.is_set():
            tarefa.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await tarefa
            raise ExecucaoCancelada()
        await asyncio.wait({tarefa}, timeout=0.3)
    return tarefa.result()


class InterfaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: dict[str, Any]
    criteria: str = Field(min_length=1)
    model: str = Field(min_length=1, max_length=200)
    weights: PesosRanking = Field(default_factory=PesosRanking)
    temperature: float = Field(TEMPERATURA_PADRAO, ge=0.0, le=TEMPERATURA_MAXIMA)
    type_values: ValoresTipo = Field(default_factory=ValoresTipo)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=512)


QUERY_PADRAO = "SAR AND Agricultura"
# Tempo máximo da coleta pela interface; ao estourar, segue para a classificação com o que já chegou.
TIMEOUT_PESQUISA_PADRAO_S = 300

# Mude a versão sempre que a consulta ou os critérios padrão mudarem: a interface substitui uma vez os
# valores salvos no navegador pelos novos padrões.
VERSAO_PADROES = "2026-11-07"

CRITERIOS_PADRAO = """SCREENING CRITERIA
Search query: SAR AND Agricultura
Topic: Synthetic Aperture Radar (SAR) remote sensing applied to agriculture (agricultura).

Review question:
How are Synthetic Aperture Radar (SAR) data used to map, monitor, or estimate agricultural variables, such as crop type, crop condition and growth, phenology, biomass, yield, soil moisture, irrigation, tillage, or crop damage?

Definitions:
- SAR = Synthetic Aperture Radar (radar de abertura sintética), from satellite, airborne, or UAV platforms, e.g. Sentinel-1, RADARSAT-2, RCM, ALOS-2 PALSAR-2, TerraSAR-X, TanDEM-X, COSMO-SkyMed, SAOCOM, ICEYE, Capella, NISAR, UAVSAR. Related terms: backscatter, polarimetry (PolSAR), interferometry (InSAR), coherence, C-band, L-band, X-band.
- Agriculture = croplands, pastures, and crops (e.g. soybean/soja, maize/milho, rice/arroz, wheat/trigo, sugarcane/cana-de-açúcar, coffee/café, cotton/algodão), agricultural soils, irrigation, and farm management.

Decision procedure (apply in order and stop at the first rule that applies):
Step 1. If "SAR" in the paper means something other than radar, apply 2.1.
Step 2. If the paper is not a research article or review on the topic, apply 2.5.
Step 3. If SAR imagery is not used or analyzed, apply 2.2 or 3.1.
Step 4. If the application is not agricultural, apply 2.3 or 2.4.
Step 5. Otherwise, check the INCLUDE and DOUBTFUL rules.

1. INCLUDE (match = 1) if the paper meets 1.1 AND at least one of 1.2 to 1.4:
1.1. SAR data are a main input of the study (alone or combined with optical, field, or weather data).
1.2. The goal is crop type classification or cropland mapping.
1.3. The goal is monitoring crop growth, condition, phenology, biomass, yield, or crop damage (flood, drought, lodging, hail).
1.4. The goal is estimating agricultural soil moisture, irrigation, tillage, or residue cover, or developing SAR methods tested on agricultural areas.

2. EXCLUDE (match = 0) if the paper:
2.1. uses "SAR" with another meaning: systemic acquired resistance (plant immunity), sodium adsorption ratio (soil/irrigation water), structure-activity relationship, specific absorption rate, search and rescue, or similar;
2.2. uses no radar imagery (only optical, multispectral, hyperspectral, thermal, LiDAR, or field data);
2.3. uses SAR only for non-agricultural targets (forests, urban areas, oceans, ice, geology, infrastructure, or disasters without crops);
2.4. is about SAR hardware, antennas, or signal processing without an agricultural application;
2.5. is not a study: journal index, table of contents, editorial, erratum, or conference announcement.

3. DOUBTFUL (match = 0.5) if:
3.1. the abstract mentions SAR and agriculture but does not make clear whether SAR data are actually analyzed;
3.2. it is a land use/land cover study where agriculture is only one class among many;
3.3. it is a review or survey of remote sensing in agriculture that covers SAR among other sensors;
3.4. the abstract is too short or vague to decide.

Answer rules:
- In the justification, name the step and criterion numbers used (e.g. "Step 5; 1.1 and 1.2").
- The quote must be one sentence or phrase copied exactly from the ABSTRACT of the paper, never from these criteria.
"""


def _config_padrao() -> dict[str, Any]:
    return {
        "query": QUERY_PADRAO,
        "bases_ativas": ["openalex", "crossref", "pubmed", "europepmc", "core", "doaj", "arxiv", "semantic_scholar"],
        "max_artigos_por_base": 100,
        "filtros": {"ano_de": None, "ano_ate": None, "tipos": [], "idiomas": [], "somente_oa": False, "campo_busca": "tudo"},
        "enriquecimento": {"referencias": True, "resolver_ids_para_doi": True, "texto_completo": True},
        "saida": {"diretorio": "saida", "raw_json": True, "separador_lista": " | "},
        "execucao": {
            "max_paginas_extras_filtro_local": 10,
            "cache_http": True,
            "timeout_s": 30,
            "timeout_pesquisa_s": TIMEOUT_PESQUISA_PADRAO_S,
            "log_nivel": "INFO",
        },
        "limites": {},
    }


_PROXY_HEADERS = ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-real-ip")


def _cliente_remoto(request: Request) -> bool:
    # A same-host reverse proxy shows up as loopback; forwarded requests are never treated as local.
    if any(h in request.headers for h in _PROXY_HEADERS):
        return True
    host = request.client.host if request.client else ""
    try:
        return not ipaddress.ip_address(host).is_loopback
    except ValueError:
        return True


def _assinar_sessao(token: str, emitida_em: int, nonce: str) -> str:
    payload = f"{emitida_em}.{nonce}"
    return hmac.new(token.encode(), f"coletor-session:{payload}".encode(), "sha256").hexdigest()


def _sessao_valida(cookie: str | None, token: str, agora: int | None = None) -> bool:
    if not cookie or len(token) < 32:
        return False
    try:
        emitida_str, nonce, assinatura = cookie.split(".", 2)
        emitida_em = int(emitida_str)
    except ValueError:
        return False
    agora = int(time.time()) if agora is None else agora
    if emitida_em > agora + 60 or agora - emitida_em > SESSION_MAX_AGE_S:
        return False
    esperado = _assinar_sessao(token, emitida_em, nonce)
    return hmac.compare_digest(assinatura, esperado)


def _nonce_sessao(cookie: str | None) -> tuple[str, int] | None:
    try:
        emitida_str, nonce, _ = str(cookie or "").split(".", 2)
        return nonce, int(emitida_str)
    except ValueError:
        return None


def _revogar_sessao(cookie: str | None) -> None:
    dados = _nonce_sessao(cookie)
    agora = int(time.time())
    with _sessoes_revogadas_lock:
        for nonce, emitida in list(_sessoes_revogadas.items()):
            if agora - emitida > SESSION_MAX_AGE_S:
                del _sessoes_revogadas[nonce]
        if dados:
            _sessoes_revogadas[dados[0]] = dados[1]


def _sessao_ativa(cookie: str | None, token: str) -> bool:
    """Sessão com assinatura válida, dentro do prazo e não encerrada por logout."""
    if not _sessao_valida(cookie, token):
        return False
    dados = _nonce_sessao(cookie)
    with _sessoes_revogadas_lock:
        return dados is not None and dados[0] not in _sessoes_revogadas


def _exige_login(request: Request) -> bool:
    """Clientes remotos sempre; clientes locais só depois de saírem da sessão (se houver token configurado)."""
    if _cliente_remoto(request):
        return True
    return bool(request.cookies.get(LOGOUT_COOKIE)) and len(os.getenv("COLETOR_WEB_TOKEN", "")) >= 32


def _origem_permitida(request: Request) -> bool:
    origin = request.headers.get("origin", "")
    host = request.headers.get("host", "")
    if not origin or not host:
        return False
    parsed = urlsplit(origin)
    # Proxies may rewrite Host; browsers cannot forge X-Forwarded-Host on cross-site requests.
    hosts = {host.casefold(), request.headers.get("x-forwarded-host", "").split(",")[0].strip().casefold()}
    return parsed.netloc.casefold() in hosts and parsed.scheme.casefold() == request.url.scheme.casefold()


def _conexao_https(request: Request) -> bool:
    return request.url.scheme.casefold() == "https"


def _permitir_tentativa_login(client_ip: str) -> bool:
    agora = time.monotonic()
    with _login_attempts_lock:
        tentativas = [t for t in _login_attempts.get(client_ip, []) if agora - t < 900]
        if len(tentativas) >= 10:
            _login_attempts[client_ip] = tentativas
            return False
        tentativas.append(agora)
        _login_attempts[client_ip] = tentativas
        return True


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
        try:
            acelerador = _resumo_acelerador(ollama.ps().models, modelo)
        except Exception:  # noqa: BLE001 — telemetry must not fail the actual model load
            acelerador = "Ollama não informou alocação"
        _atualizar_estado(ollama_accelerator=acelerador)


def _resumo_acelerador(processos: Any, modelo: str) -> str:
    """Infer CPU/GPU split from Ollama's reported VRAM and total model memory."""
    processo = next(
        (p for p in processos if getattr(p, "model", None) in {modelo, f"{modelo}:latest"}),
        None,
    )
    if processo is None:
        return "nenhum modelo ativo"
    total = int(getattr(processo, "size", 0) or 0)
    vram = int(getattr(processo, "size_vram", 0) or 0)
    if total <= 0:
        return "acelerador não informado pelo Ollama"
    gpu_percent = min(100, max(0, round(vram * 100 / total)))
    cpu_percent = 100 - gpu_percent
    return f"{gpu_percent}% GPU · {cpu_percent}% CPU"


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


TEMPOS_ARQUIVO = "tempos.json"


def _gravar_tempos(pasta: Path, tempos: dict[str, Any]) -> None:
    """Registra a duração da busca e do processamento (triagem LLM) na pasta da pesquisa."""
    with contextlib.suppress(OSError):
        (pasta / TEMPOS_ARQUIVO).write_text(json.dumps(tempos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _ler_tempos(pasta: Path) -> dict[str, float | None]:
    tempos: dict[str, Any] = {}
    arq = pasta / TEMPOS_ARQUIVO
    if arq.is_file() and not arq.is_symlink():
        with contextlib.suppress(Exception):
            dados = json.loads(arq.read_text(encoding="utf-8"))
            if isinstance(dados, dict):
                tempos = dados
    busca = tempos.get("busca_s")
    if busca is None:
        # Pesquisas anteriores ao registro de tempos: a duração da coleta está no relatorio.json.
        relatorio = pasta / "relatorio.json"
        if relatorio.is_file() and not relatorio.is_symlink():
            with contextlib.suppress(Exception):
                busca = json.loads(relatorio.read_text(encoding="utf-8")).get("duracao_s")
    def _num(valor: Any) -> float | None:
        try:
            numero = float(valor)
        except (TypeError, ValueError):
            return None
        return numero if math.isfinite(numero) and numero >= 0 else None
    return {"busca_s": _num(busca), "processamento_s": _num(tempos.get("processamento_s"))}


def _executar_job(
    configuracao: config_mod.Config,
    criteria: str,
    model: str,
    weights: PesosRanking | dict[str, float] | None = None,
    temperature: float = TEMPERATURA_PADRAO,
    type_values: ValoresTipo | dict[str, float] | None = None,
) -> None:
    _atualizar_estado(stage="carregando modelo", processed=0, total=0, current="", output="", error="")
    try:
        load_dotenv(ROOT / ".env")
        pasta_saida = diretorio_execucao(configuracao, datetime.now())
        _atualizar_estado(research_id=pasta_saida.name)
        (pasta_saida / "config.yaml").write_text(
            yaml.safe_dump(configuracao.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        (pasta_saida / "criterios.txt").write_text(criteria.rstrip() + "\n", encoding="utf-8")
        tempos: dict[str, Any] = {"inicio": datetime.now().astimezone().isoformat(timespec="seconds")}
        # O status passa a refletir o modelo escolhido já durante o carregamento (não o anterior).
        _atualizar_estado(ollama_status="carregando", ollama_model=model, ollama_error="", ollama_accelerator="não informado")
        _carregar_modelo(model)
        _atualizar_estado(ollama_status="pronto", ollama_model=model, ollama_error="")
        _verificar_cancelamento()
        _atualizar_estado(stage="Buscando Artigos")
        credenciais = Credenciais.do_ambiente()
        registrar(credenciais)
        t_busca = time.monotonic()
        try:
            codigo, pasta_saida = asyncio.run(
                _executar_cancelavel(configuracao, credenciais, dir_saida_override=pasta_saida)
            )
        finally:
            tempos["busca_s"] = round(time.monotonic() - t_busca, 1)
            _gravar_tempos(pasta_saida, tempos)
        if codigo != 0:
            raise RuntimeError("A busca terminou sem sucesso em nenhuma base; consulte o relatório da execução.")

        consolidado = pasta_saida / "consolidado.csv"
        if not consolidado.exists():
            raise FileNotFoundError("A busca não produziu consolidado.csv.")

        _verificar_cancelamento()
        _atualizar_estado(stage="Validando e Ranqueando", processed=0, total=0)

        def progresso(processado: int, total: int, titulo: str) -> None:
            _atualizar_estado(processed=processado, total=total, current=titulo)

        pesos = normalizar_pesos(weights)
        kwargs_ranking: dict[str, Any] = {"modelo": model, "progresso": progresso, "cancelar": _cancelamento.is_set}
        if temperature != TEMPERATURA_PADRAO:
            kwargs_ranking["temperatura"] = temperature
        if pesos != PESOS_SCORE:
            kwargs_ranking["pesos"] = pesos
        valores_tipo = normalizar_valores_tipo(type_values)
        if valores_tipo != VALORES_TIPO_PADRAO:
            kwargs_ranking["valores_tipo"] = valores_tipo
        t_ranking = time.monotonic()
        try:
            ranking = gerar_ranking(consolidado, criteria, **kwargs_ranking)
        finally:
            tempos["processamento_s"] = round(time.monotonic() - t_ranking, 1)
            tempos["fim"] = datetime.now().astimezone().isoformat(timespec="seconds")
            _gravar_tempos(pasta_saida, tempos)
        _atualizar_estado(
            running=False,
            stage="concluído",
            processed=_job_state.get("total", 0),
            output=str(ranking),
            error="",
        )
    except RuntimeError as erro:
        if _job_state.get("ollama_status") == "carregando":
            _atualizar_estado(ollama_status="erro", ollama_error=str(erro))
        _atualizar_estado(running=False, stage="falhou", error=f"{type(erro).__name__}: {erro}")
    except (ExecucaoCancelada, RankingCancelado):
        _atualizar_estado(running=False, stage="cancelado", error="")
    except Exception as erro:  # noqa: BLE001 — erros são reportados na interface, não encerram o servidor
        _atualizar_estado(running=False, stage="falhou", error=f"{type(erro).__name__}: {erro}")


@app.get("/", response_class=FileResponse)
def index() -> FileResponse:
    return FileResponse(UI_PATH, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})


@app.get("/login", response_class=FileResponse)
def login_page() -> FileResponse:
    return FileResponse(WEB_PATH / "login.html", media_type="text/html; charset=utf-8")


@app.get("/api/auth/session")
def auth_session(request: Request) -> dict[str, bool]:
    if not _exige_login(request):
        return {"authenticated": True, "configured": True}
    token = os.getenv("COLETOR_WEB_TOKEN", "")
    valid = _sessao_ativa(request.cookies.get(SESSION_COOKIE), token)
    return {"authenticated": valid, "configured": len(token) >= 32}


@app.post("/api/auth/login")
def auth_login(payload: LoginRequest, request: Request, response: Response) -> dict[str, str]:
    token = os.getenv("COLETOR_WEB_TOKEN", "")
    if len(token) < 32:
        raise HTTPException(status_code=503, detail="Login remoto não configurado no servidor.")
    client_ip = request.client.host if request.client else "desconhecido"
    if not _permitir_tentativa_login(client_ip):
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde 15 minutos e tente novamente.")
    if not hmac.compare_digest(payload.token, token):
        raise HTTPException(status_code=401, detail="Token inválido.")

    with _login_attempts_lock:
        _login_attempts.pop(client_ip, None)
    issued = int(time.time())
    nonce = secrets.token_urlsafe(18)
    session = f"{issued}.{nonce}.{_assinar_sessao(token, issued, nonce)}"
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session,
        max_age=SESSION_MAX_AGE_S,
        httponly=True,
        secure=_conexao_https(request),
        samesite="strict",
        path="/",
    )
    response.delete_cookie(
        key=LOGOUT_COOKIE, path="/", httponly=True, secure=_conexao_https(request), samesite="strict"
    )
    return {"message": "Login efetuado."}


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response) -> dict[str, str]:
    _revogar_sessao(request.cookies.get(SESSION_COOKIE))
    seguro = _conexao_https(request)
    response.delete_cookie(key=SESSION_COOKIE, path="/", httponly=True, secure=seguro, samesite="strict")
    response.set_cookie(
        key=LOGOUT_COOKIE,
        value="1",
        max_age=365 * 24 * 60 * 60,
        httponly=True,
        secure=seguro,
        samesite="strict",
        path="/",
    )
    return {"message": "Sessão encerrada."}


def _arquivos_visiveis(pasta: Path) -> list[str]:
    return sorted(p.name for p in pasta.iterdir() if p.is_file() and not p.is_symlink() and not p.name.startswith("."))


def _pasta_pesquisa(research_id: str) -> Path:
    if Path(research_id).name != research_id:
        raise HTTPException(status_code=404, detail="Pesquisa não encontrada.")
    pasta = SAIDA_PATH / research_id
    raiz = SAIDA_PATH.resolve()
    if not pasta.is_dir() or pasta.is_symlink() or not pasta.resolve().is_relative_to(raiz):
        raise HTTPException(status_code=404, detail="Pesquisa não encontrada.")
    return pasta


def _desempacotar_aspas_simples(texto: str) -> str:
    s = texto.strip()
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1].strip()
    return s


def _ler_query(pasta: Path) -> str:
    relatorio = pasta / "relatorio.json"
    if relatorio.is_file() and not relatorio.is_symlink():
        try:
            dados = json.loads(relatorio.read_text(encoding="utf-8"))
            if isinstance(dados, dict) and str(dados.get("query") or "").strip():
                return _desempacotar_aspas_simples(str(dados["query"]))
        except Exception:  # noqa: BLE001
            pass
    for nome_yaml in ("config.yaml", "config_usada.yaml"):
        arq = pasta / nome_yaml
        if arq.is_file() and not arq.is_symlink():
            try:
                dados = yaml.safe_load(arq.read_text(encoding="utf-8"))
                if isinstance(dados, dict) and str(dados.get("query") or "").strip():
                    return _desempacotar_aspas_simples(str(dados["query"]))
            except Exception:  # noqa: BLE001
                pass
    partes = pasta.name.split("_", 2)
    return partes[2].replace("-", " ") if len(partes) == 3 else pasta.name


def _fontes_artigos(pasta: Path) -> list[tuple[Path, str]]:
    """Ranking final; senão o checkpoint de um ranking interrompido; senão o consolidado sem triagem."""
    fontes = [(pasta / "ranking.csv", "completo")]
    checkpoints = sorted(
        (p for p in pasta.glob(".ranking-*.csv") if p.is_file() and not p.is_symlink() and p.stat().st_size > 0),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    fontes += [(p, "parcial") for p in checkpoints]
    fontes.append((pasta / "consolidado.csv", "ausente"))
    return fontes


def _ler_linhas_fonte(pasta: Path) -> tuple[list[dict[str, str]], str]:
    for arq, situacao in _fontes_artigos(pasta):
        if not arq.is_file() or arq.is_symlink():
            continue
        try:
            with arq.open("r", encoding="utf-8-sig", newline="") as f:
                return list(csv.DictReader(f)), situacao
        except Exception:  # noqa: BLE001
            continue
    return [], "ausente"


def _score(linha: dict[str, str]) -> float | None:
    bruto = str(linha.get("llm_score") or "").strip().replace(",", ".")
    try:
        score = float(bruto)
    except ValueError:
        return None
    return score if math.isfinite(score) else None


def _ler_artigos_ordenados(pasta: Path) -> tuple[list[dict[str, Any]], str]:
    linhas, situacao = _ler_linhas_fonte(pasta)
    artigos: list[dict[str, Any]] = []
    for linha in linhas:
        score = _score(linha)
        artigos.append({
            "llm_score": score,
            "ano": str(linha.get("ano") or "").strip(),
            "bases": str(linha.get("bases") or "").strip(),
            "titulo": str(linha.get("titulo") or "").strip(),
            "autores": str(linha.get("autores") or "").strip(),
            "resumo": str(linha.get("resumo") or "").strip(),
            "doi": str(linha.get("doi") or "").strip(),
            "llm_label": str(linha.get("llm_label") or "").strip(),
            "llm_justification": str(linha.get("llm_justification") or "").strip(),
        })
    artigos.sort(key=lambda item: (item["llm_score"] is None, -(item["llm_score"] or 0.0)))
    return artigos, situacao


@app.get("/api/history")
def history() -> list[dict[str, Any]]:
    SAIDA_PATH.mkdir(parents=True, exist_ok=True)
    pesquisas = []
    for pasta in sorted((p for p in SAIDA_PATH.iterdir() if p.is_dir() and not p.is_symlink()), reverse=True):
        arquivos = _arquivos_visiveis(pasta)
        pesquisas.append({"id": pasta.name, "query": _ler_query(pasta), "files": arquivos})
    return pesquisas


@app.get("/api/history/{research_id}")
def history_detail(research_id: str) -> dict[str, Any]:
    pasta = _pasta_pesquisa(research_id)
    arquivos = _arquivos_visiveis(pasta)
    query = _ler_query(pasta)
    por_base: list[dict[str, Any]] = []
    consolidado_info: dict[str, Any] = {}
    relatorio = pasta / "relatorio.json"
    if relatorio.is_file() and not relatorio.is_symlink():
        try:
            dados = json.loads(relatorio.read_text(encoding="utf-8"))
            if isinstance(dados, dict):
                consolidado_info = dados.get("consolidado") or {}
                for b in dados.get("bases") or []:
                    if isinstance(b, dict) and b.get("base"):
                        por_base.append({
                            "base": str(b["base"]),
                            "count": int(b.get("gravados") or 0),
                            "status": str(b.get("status") or ""),
                        })
        except Exception:  # noqa: BLE001
            pass
    artigos, situacao_ranking = _ler_artigos_ordenados(pasta)
    if not por_base and artigos:
        contagem: dict[str, int] = {}
        for art in artigos:
            for b in (x.strip() for x in art["bases"].split("|") if x.strip()):
                contagem[b] = contagem.get(b, 0) + 1
        por_base = [{"base": k, "count": v, "status": "ok"} for k, v in contagem.items()]
    total_por_base = sum(item["count"] for item in por_base)
    return {
        "id": pasta.name,
        "query": query,
        "files": arquivos,
        "total_articles": total_por_base,
        "consolidated_articles": int(consolidado_info.get("linhas") or len(artigos)),
        "by_base": por_base,
        "ranking": situacao_ranking,
        "timing": _ler_tempos(pasta),
        "articles": artigos,
    }


GRAFO_MAX_ARTIGOS = 60
GRAFO_MAX_REFERENCIAS = 60


def _dois(texto: str) -> list[str]:
    return [t.strip().lower() for t in str(texto or "").split("|") if t.strip()]


def _montar_grafo(linhas: list[dict[str, str]]) -> dict[str, Any]:
    """Artigos ligados às referências que compartilham (acoplamento bibliográfico) e a artigos da própria pesquisa.

    Para manter o grafo legível: os artigos com referências mais bem ranqueados e as referências citadas por pelo
    menos dois desses artigos.
    """
    ordenadas = sorted(
        (linha for linha in linhas if _dois(linha.get("referencias", ""))),
        key=lambda linha: (_score(linha) is None, -(_score(linha) or 0.0)),
    )[:GRAFO_MAX_ARTIGOS]
    por_doi = {str(l.get("doi") or "").strip().lower(): l for l in ordenadas if str(l.get("doi") or "").strip()}
    contagem: dict[str, int] = {}
    for linha in ordenadas:
        for ref in set(_dois(linha.get("referencias", ""))):
            if ref not in por_doi:
                contagem[ref] = contagem.get(ref, 0) + 1
    compartilhadas = sorted((r for r, n in contagem.items() if n >= 2), key=lambda r: (-contagem[r], r))
    referencias = set(compartilhadas[:GRAFO_MAX_REFERENCIAS])

    nos: list[dict[str, Any]] = []
    arestas: list[dict[str, str]] = []
    ids: dict[str, str] = {}
    for indice, linha in enumerate(ordenadas):
        no_id = f"a{indice}"
        doi = str(linha.get("doi") or "").strip()
        if doi:
            ids[doi.lower()] = no_id
        nos.append({
            "id": no_id,
            "type": "artigo",
            "label": str(linha.get("titulo") or doi or "Sem título").strip(),
            "doi": doi,
            "ano": str(linha.get("ano") or "").strip(),
            "score": _score(linha),
        })
    for ref in sorted(referencias):
        ids[ref] = f"r:{ref}"
        nos.append({"id": f"r:{ref}", "type": "referencia", "label": ref, "doi": ref, "citations": contagem[ref]})
    for indice, linha in enumerate(ordenadas):
        for ref in set(_dois(linha.get("referencias", ""))):
            if ref in ids and ids[ref] != f"a{indice}":
                arestas.append({"source": f"a{indice}", "target": ids[ref]})
    usados = {a["source"] for a in arestas} | {a["target"] for a in arestas}
    nos = [n for n in nos if n["id"] in usados]
    return {
        "nodes": nos,
        "edges": arestas,
        "articles_with_references": sum(1 for l in linhas if _dois(l.get("referencias", ""))),
    }


def _grafo_habilitado() -> bool:
    """O grafo do histórico só aparece quando o servidor é iniciado com --graph."""
    return os.getenv("COLETOR_WEB_GRAFO", "0") == "1"


@app.get("/api/history/{research_id}/graph")
def history_graph(research_id: str) -> dict[str, Any]:
    if not _grafo_habilitado():
        raise HTTPException(status_code=404, detail="Grafo desabilitado: inicie o servidor com --graph.")
    pasta = _pasta_pesquisa(research_id)
    linhas, _ = _ler_linhas_fonte(pasta)
    return _montar_grafo(linhas)


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
    return {
        "config": _config_padrao(),
        "criteria": CRITERIOS_PADRAO,
        "defaults_version": VERSAO_PADROES,
        "model": DEFAULT_MODEL,
        "weights": {k: round(v * 100) for k, v in PESOS_SCORE.items()},
        "type_values": {k: round(v * 100) for k, v in VALORES_TIPO_PADRAO.items()},
        "temperature": TEMPERATURA_PADRAO,
        "graph": _grafo_habilitado(),
    }


@app.get("/api/models")
def get_models() -> dict[str, Any]:
    try:
        models = []
        for item in ollama.list().models:
            nome = getattr(item, "model", None) or getattr(item, "name", None)
            if not nome:
                continue
            details = getattr(item, "details", None)
            models.append({
                "name": nome,
                "size": int(getattr(item, "size", 0) or 0),
                "family": getattr(details, "family", None),
                "parameter_size": getattr(details, "parameter_size", None),
            })
        return {"models": models, "error": ""}
    except Exception as erro:  # noqa: BLE001 — expose a recoverable status for the UI
        return {"models": [], "error": f"{type(erro).__name__}: Ollama indisponível"}


@app.post("/api/run")
def start_run(payload: InterfaceRequest) -> dict[str, str]:
    with _state_lock:
        if _job_state["running"]:
            raise HTTPException(status_code=409, detail="Já existe uma execução em andamento.")
        _cancelamento.clear()
        _job_state.update({
            "running": True,
            "research_id": "",
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
        args=(configuracao, payload.criteria.strip(), payload.model.strip(), payload.weights, payload.temperature, payload.type_values),
        daemon=True,
    )
    worker.start()
    return {"message": "Busca iniciada."}


@app.post("/api/cancel")
def cancel_run() -> dict[str, str]:
    with _state_lock:
        if not _job_state["running"]:
            raise HTTPException(status_code=409, detail="Não há execução em andamento.")
        _cancelamento.set()
        _job_state["stage"] = "cancelando"
    return {"message": "Cancelamento solicitado."}


@app.get("/api/status")
def get_status() -> dict[str, Any]:
    with _state_lock:
        return dict(_job_state)


@app.middleware("http")
async def protect_remote_access(request, call_next):
    """Require signed cookie sessions for remote clients, without browser Basic Auth prompts."""
    if not _exige_login(request):
        return await call_next(request)

    if request.url.path == "/api/auth/logout":
        # Sair é sempre permitido (mesmo com sessão já expirada), desde que a origem seja a própria interface.
        if not _origem_permitida(request):
            return JSONResponse({"detail": "Origem da requisição não autorizada."}, status_code=403)
        return await call_next(request)
    public_paths = {"/login", "/api/auth/login", "/api/auth/session"}
    if request.url.path.startswith("/assets/") or request.url.path in public_paths:
        if request.method == "POST" and not _origem_permitida(request):
            return JSONResponse({"detail": "Origem da requisição não autorizada."}, status_code=403)
        return await call_next(request)

    token = os.getenv("COLETOR_WEB_TOKEN", "")
    if len(token) < 32:
        if request.url.path == "/":
            return RedirectResponse("/login?error=not-configured", status_code=303)
        return JSONResponse(
            {"detail": "Acesso remoto desabilitado: configure COLETOR_WEB_TOKEN com 32+ caracteres."},
            status_code=503,
        )

    if request.method == "POST" and not _origem_permitida(request):
        return JSONResponse({"detail": "Origem da requisição não autorizada."}, status_code=403)

    if not _sessao_ativa(request.cookies.get(SESSION_COOKIE), token):
        if request.url.path == "/":
            return RedirectResponse("/login", status_code=303)
        return JSONResponse({"detail": "Sessão expirada ou ausente.", "login": "/login"}, status_code=401)
    return await call_next(request)
