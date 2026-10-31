"""Limitador por base (seção 7): token bucket + semáforo, taxa adaptativa e retentativa.

- 429: taxa ÷ 2 (piso 0,1 req/s), espera `Retry-After` ou backoff exponencial com jitter.
- 5xx, timeout, erro de conexão: mesmo backoff, sem reduzir a taxa.
- 20 sucessos seguidos: taxa × 1,25, sem passar da inicial.
- Outros 4xx: devolvidos sem repetir (quem chama decide o erro).
- Até `max_tentativas`; depois, `TentativasEsgotadas`.
"""

from __future__ import annotations

import asyncio
import email.utils
import logging
import random
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable

import httpx

BACKOFF_PADRAO = (2, 4, 8, 16, 32)
RETRY_AFTER_MAX = 300.0


class TentativasEsgotadas(Exception):
    def __init__(self, ultimo: str):
        super().__init__(f"tentativas esgotadas (último resultado: {ultimo})")
        self.ultimo = ultimo


class Limitador:
    def __init__(
        self,
        nome: str,
        taxa: float,
        concorrencia: int,
        *,
        logger: logging.Logger | None = None,
        max_tentativas: int = 6,
        piso: float = 0.1,
        backoff: tuple[float, ...] = BACKOFF_PADRAO,
        sucessos_para_subir: int = 20,
        dormir: Callable[[float], Awaitable[None]] = asyncio.sleep,
        relogio: Callable[[], float] = time.monotonic,
        aleatorio: Callable[[], float] = random.random,
    ):
        self.nome = nome
        self.taxa_inicial = float(taxa)
        self.taxa = float(taxa)
        self.concorrencia = concorrencia
        self.log = logger or logging.getLogger(f"coletor.{nome}")
        self.max_tentativas = max_tentativas
        self.piso = piso
        self.backoff = backoff
        self.sucessos_para_subir = sucessos_para_subir
        self._dormir = dormir
        self._relogio = relogio
        self._aleatorio = aleatorio
        self._sem = asyncio.Semaphore(concorrencia)
        self._lock = asyncio.Lock()
        self._proximo = 0.0
        self._ok_seguidos = 0
        self.n_chamadas = 0
        self.n_429 = 0
        self.n_retentativas = 0

    # ------------------------------------------------------------ token bucket (capacidade 1)

    async def _vez(self) -> None:
        async with self._lock:
            agora = self._relogio()
            espera = max(0.0, self._proximo - agora)
            self._proximo = max(agora, self._proximo) + 1.0 / self.taxa
        if espera > 0:
            await self._dormir(espera)

    def _espera_backoff(self, tentativa: int) -> float:
        base = self.backoff[min(tentativa, len(self.backoff) - 1)]
        return base + self._aleatorio() * base / 2

    def _reduzir(self) -> None:
        anterior = self.taxa
        self.taxa = max(self.piso, self.taxa / 2)
        self._ok_seguidos = 0
        if self.taxa != anterior:
            self.log.warning("429 recebido: taxa reduzida de %.3g para %.3g req/s", anterior, self.taxa)

    def _sucesso(self) -> None:
        self._ok_seguidos += 1
        if self._ok_seguidos >= self.sucessos_para_subir and self.taxa < self.taxa_inicial:
            anterior = self.taxa
            self.taxa = min(self.taxa_inicial, self.taxa * 1.25)
            self.log.info("%d sucessos seguidos: taxa aumentada de %.3g para %.3g req/s",
                          self._ok_seguidos, anterior, self.taxa)
            self._ok_seguidos = 0
        elif self._ok_seguidos >= self.sucessos_para_subir:
            self._ok_seguidos = 0

    # ------------------------------------------------------------ execução

    async def executar(
        self,
        requisicao: Callable[[], Awaitable[httpx.Response]],
        descricao: str = "",
        parar: Callable[[httpx.Response], bool] | None = None,
    ) -> httpx.Response:
        """Executa `requisicao` respeitando taxa e concorrência, com retentativas.

        `parar(resp)` → True interrompe as retentativas de um 429 e devolve a resposta
        (ex.: orçamento diário do OpenAlex esgotado, que não volta com espera).
        """
        ultimo = "?"
        for tentativa in range(self.max_tentativas):
            async with self._sem:
                await self._vez()
                self.n_chamadas += 1
                try:
                    resp = await requisicao()
                except (httpx.TimeoutException, httpx.TransportError) as e:
                    ultimo = type(e).__name__
                    espera = self._espera_backoff(tentativa)
                else:
                    ultimo = f"HTTP {resp.status_code}"
                    if resp.status_code == 429:
                        if parar and parar(resp):
                            return resp
                        self.n_429 += 1
                        self._reduzir()
                        espera = retry_after(resp) or self._espera_backoff(tentativa)
                    elif resp.status_code >= 500:
                        espera = self._espera_backoff(tentativa)
                    else:
                        if resp.status_code < 400:
                            self._sucesso()
                        return resp
            if tentativa == self.max_tentativas - 1:
                break
            self.n_retentativas += 1
            self.log.warning("%s em %s; tentativa %d/%d em %.1f s",
                             ultimo, descricao or "requisição", tentativa + 2, self.max_tentativas, espera)
            await self._dormir(espera)
        raise TentativasEsgotadas(ultimo)


def retry_after(resp: httpx.Response) -> float | None:
    """`Retry-After` (segundos ou data HTTP) ou `X-RateLimit-Retry-After` (data ISO, usado pelo CORE)."""
    v = (resp.headers.get("retry-after") or "").strip()
    if not v:
        iso = (resp.headers.get("x-ratelimit-retry-after") or "").strip()
        if not iso:
            return None
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        s = (dt - datetime.now(timezone.utc)).total_seconds()
        return min(max(s, 0.0), RETRY_AFTER_MAX) or None
    try:
        s = float(v)
    except ValueError:
        try:
            dt = email.utils.parsedate_to_datetime(v)
        except (TypeError, ValueError):
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        s = (dt - datetime.now(timezone.utc)).total_seconds()
    return min(max(s, 0.0), RETRY_AFTER_MAX) or None
