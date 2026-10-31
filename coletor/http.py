"""Cliente HTTP por base: limitador + cache em disco (TTL 24 h) + User-Agent + URLs sem segredos."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx

from .limitador import Limitador
from .segredos import higienizar_texto, higienizar_url

TTL_CACHE_S = 24 * 3600


def user_agent(email: str) -> str:
    return f"coletor-artigos/1.0 (mailto:{email})" if email else "coletor-artigos/1.0"


class ErroHTTP(Exception):
    """Resposta 4xx/5xx definitiva (sem nova tentativa)."""

    def __init__(self, status: int, url: str, trecho: str, headers: dict | None = None):
        super().__init__(f"HTTP {status} em {url}: {trecho}")
        self.status = status
        self.url = url
        self.trecho = trecho
        self.headers = headers or {}


@dataclass
class Resposta:
    status: int
    texto: str
    url: str  # já sem segredos
    headers: dict[str, str] = field(default_factory=dict)
    do_cache: bool = False

    def json(self) -> Any:
        return json.loads(self.texto)


class CacheDisco:
    def __init__(self, diretorio: Path, ttl_s: float = TTL_CACHE_S):
        self.dir = Path(diretorio)
        self.ttl_s = ttl_s

    @staticmethod
    def chave(metodo: str, url: str, corpo: bytes) -> str:
        h = hashlib.sha256()
        h.update(metodo.encode())
        h.update(b"\0")
        h.update(url.encode())
        h.update(b"\0")
        h.update(corpo)
        return h.hexdigest()

    def _arq(self, chave: str) -> Path:
        return self.dir / chave[:2] / f"{chave}.json"

    def ler(self, chave: str) -> Resposta | None:
        p = self._arq(chave)
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if time.time() - d.get("criado_em", 0) > self.ttl_s:
            return None
        return Resposta(d["status"], d["texto"], d["url"], d.get("headers", {}), do_cache=True)

    def gravar(self, chave: str, r: Resposta) -> None:
        p = self._arq(chave)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"criado_em": time.time(), "status": r.status, "url": r.url,
                                   "headers": r.headers, "texto": r.texto}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)


class ClienteHTTP:
    def __init__(
        self,
        base: str,
        limitador: Limitador,
        *,
        email: str = "",
        timeout_s: float = 30,
        cache: CacheDisco | None = None,
        headers: dict[str, str] | None = None,
        logger: logging.Logger | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base = base
        self.limitador = limitador
        self.cache = cache
        self.log = logger or logging.getLogger(f"coletor.{base}")
        self.n_do_cache = 0
        self._cliente = httpx.AsyncClient(
            headers={"User-Agent": user_agent(email), **(headers or {})},
            timeout=httpx.Timeout(timeout_s),
            follow_redirects=True,
            transport=transport,
        )

    async def get(self, url: str, **kw) -> Resposta:
        return await self.requisitar("GET", url, **kw)

    async def post(self, url: str, **kw) -> Resposta:
        return await self.requisitar("POST", url, **kw)

    async def requisitar(
        self,
        metodo: str,
        url: str,
        *,
        params: dict | None = None,
        json: Any = None,
        headers: dict | None = None,
        parar: Callable[[httpx.Response], bool] | None = None,
    ) -> Resposta:
        req = self._cliente.build_request(metodo, url, params=params, json=json, headers=headers)
        url_limpa = higienizar_url(str(req.url))
        chave = CacheDisco.chave(metodo, url_limpa, req.content) if self.cache else None
        if chave:
            r = self.cache.ler(chave)
            if r is not None:
                self.n_do_cache += 1
                self.log.debug("%s %s → %d (cache)", metodo, url_limpa, r.status)
                return r
        t0 = time.monotonic()
        descricao = url_limpa if len(url_limpa) <= 160 else url_limpa[:157] + "..."
        resp = await self.limitador.executar(lambda: self._cliente.send(req), descricao=descricao, parar=parar)
        r = Resposta(resp.status_code, resp.text, url_limpa, dict(resp.headers))
        self.log.debug("%s %s → %d (%.2f s)", metodo, url_limpa, r.status, time.monotonic() - t0)
        if r.status >= 400:
            raise ErroHTTP(r.status, url_limpa, higienizar_texto(" ".join(r.texto.split()))[:300], r.headers)
        if chave and r.status == 200:
            self.cache.gravar(chave, r)
        return r

    async def fechar(self) -> None:
        await self._cliente.aclose()
