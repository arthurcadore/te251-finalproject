from __future__ import annotations

import logging
import socket
from pathlib import Path

import pytest

from coletor.bases.base import Contexto
from coletor.config import Config
from coletor.http import ClienteHTTP
from coletor.limitador import Limitador
from coletor.modelo import EstatisticasBase
from coletor.segredos import Credenciais, registrar

FIXTURES = Path(__file__).parent / "fixtures"

CHAVE_FALSA = "CHAVE-SECRETA-TESTE-9f3a"
EMAIL_FALSO = "pesquisador.teste@example.org"
CRED = Credenciais(OPENALEX_API_KEY=CHAVE_FALSA, CONTACT_EMAIL=EMAIL_FALSO)
registrar(CRED)


def fixture(base: str, nome: str) -> str:
    return (FIXTURES / base / nome).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def sem_rede(request, monkeypatch):
    """Testes padrão são offline: qualquer conexão TCP real falha (respx não abre sockets)."""
    if request.node.get_closest_marker("online"):
        return
    original = socket.socket.connect

    def bloquear(self, endereco):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            raise RuntimeError(f"acesso à rede em teste offline: {endereco}")
        return original(self, endereco)

    monkeypatch.setattr(socket.socket, "connect", bloquear)


class RelogioFalso:
    """Relógio + sleep simulados: o limitador "espera" sem gastar tempo real."""

    def __init__(self):
        self.t = 0.0
        self.esperas: list[float] = []

    def __call__(self) -> float:
        return self.t

    async def dormir(self, s: float) -> None:
        self.esperas.append(s)
        self.t += s


@pytest.fixture
def relogio() -> RelogioFalso:
    return RelogioFalso()


def opcoes_rapidas(relogio: RelogioFalso) -> dict:
    return {"dormir": relogio.dormir, "relogio": relogio, "aleatorio": lambda: 0.0}


def config(**kw) -> Config:
    dados = {"query": "machine learning", "execucao": {"cache_http": False}}
    dados.update(kw)
    return Config.model_validate(dados)


def contexto(cfg: Config, base: str, relogio: RelogioFalso, cred: Credenciais = CRED) -> Contexto:
    log = logging.getLogger(f"coletor.{base}")
    lim = Limitador(base, 100, 5, logger=log, **opcoes_rapidas(relogio))
    cliente = ClienteHTTP(base, lim, email=cred.CONTACT_EMAIL, logger=log)
    return Contexto(cfg, cred, cliente, EstatisticasBase(base=base, pedidos=cfg.max_artigos_por_base), log)


async def coletar(adaptador, arvore, plano, limite) -> list:
    regs = []
    async for lote in adaptador.buscar(arvore, plano, limite):
        regs += lote
    return regs
