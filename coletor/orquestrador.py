"""Orquestrador: uma tarefa assíncrona por base, CSVs em fluxo, relatório no fim (seções 7–9)."""

from __future__ import annotations

import asyncio
import logging
import re
import sys
import time
import unicodedata
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .bases import BASES, CREDENCIAIS
from .bases.base import Contexto, EncerrarBase
from .config import Config
from .consulta import analisar
from .enriquecimento.opencitations import OpenCitations
from .http import CacheDisco, ClienteHTTP, ErroHTTP
from .limitador import Limitador, TentativasEsgotadas
from .modelo import EstatisticasBase, Registro
from .saida import consolidado, relatorio
from .saida.csv_writer import EscritorCSV
from .segredos import Credenciais, FiltroSegredos, higienizar_texto

DIR_CACHE = Path(".cache") / "http"
FORMATO_LOG = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

log = logging.getLogger("coletor")


def slug(texto: str, tamanho: int = 50) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:tamanho].rstrip("-") or "consulta"


def diretorio_execucao(config: Config, agora: datetime) -> Path:
    raiz = Path(config.saida.diretorio)
    nome = f"{agora.strftime('%Y-%m-%d_%H%M%S')}_{slug(config.query)}"
    d, i = raiz / nome, 2
    while d.exists():
        d, i = raiz / f"{nome}-{i}", i + 1
    d.mkdir(parents=True)
    return d


def configurar_log(nivel: str, arquivo: Path) -> list[logging.Handler]:
    logging.getLogger("httpx").setLevel(logging.WARNING)  # o httpx registra URLs completas em INFO
    log.setLevel(logging.DEBUG)
    log.propagate = False
    fmt = logging.Formatter(FORMATO_LOG)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr),
                                       logging.FileHandler(arquivo, encoding="utf-8")]
    for h in handlers:
        h.setLevel(nivel)
        h.setFormatter(fmt)
        h.addFilter(FiltroSegredos())
        log.addHandler(h)
    return handlers


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def executar(
    config: Config,
    cred: Credenciais,
    *,
    dir_cache: Path = DIR_CACHE,
    dir_saida_override: Path | None = None,
    opcoes_limitador: dict | None = None,
) -> tuple[int, Path]:
    """Roda todas as bases ativas em paralelo. Devolve (código de saída, diretório da execução)."""
    inicio, inicio_iso = time.monotonic(), _agora_iso()
    dir_saida = dir_saida_override or diretorio_execucao(config, datetime.now())
    dir_saida.mkdir(parents=True, exist_ok=True)
    handlers = configurar_log(config.execucao.log_nivel, dir_saida / "execucao.log")
    try:
        (dir_saida / "config_usada.yaml").write_text(
            yaml.safe_dump(config.model_dump(mode="json"), allow_unicode=True, sort_keys=False), encoding="utf-8")
        log.info("consulta: %s | bases: %s | máximo por base: %d",
                 config.query, ", ".join(config.bases_ativas), config.max_artigos_por_base)
        cache = CacheDisco(dir_cache) if config.execucao.cache_http else None
        oc = _opencitations(config, cred, cache, opcoes_limitador or {}) if config.enriquecimento.referencias else None
        ests = [EstatisticasBase(base=b, pedidos=config.max_artigos_por_base) for b in config.bases_ativas]
        gravados: dict[str, list[Registro]] = {e.base: [] for e in ests}  # para o consolidado
        limite = config.execucao.timeout_pesquisa_s
        prazo = asyncio.get_running_loop().time() + limite if limite else None
        if limite:
            log.info("tempo limite da pesquisa: %.0f s", limite)
        try:
            resultados = await asyncio.gather(
                *(_executar_base(e, config, cred, dir_saida, cache, opcoes_limitador or {}, oc, gravados[e.base],
                                 prazo=prazo)
                  for e in ests),
                return_exceptions=True,
            )
        finally:
            if oc is not None:
                await oc.cliente.fechar()
        for e, r in zip(ests, resultados):
            if isinstance(r, BaseException):  # não deveria ocorrer: _executar_base captura tudo
                e.status, e.motivo = "falhou", higienizar_texto(f"{type(r).__name__}: {r}")
        resumo_cons = _gerar_consolidado(dir_saida, gravados, config)
        dados = relatorio.montar({
            "query": config.query,
            "filtros": config.filtros.model_dump(mode="json"),
            "enriquecimento": config.enriquecimento.model_dump(mode="json"),
            "max_artigos_por_base": config.max_artigos_por_base,
            "inicio": inicio_iso,
            "fim": _agora_iso(),
            "duracao_s": round(time.monotonic() - inicio, 2),
            "diretorio": str(dir_saida),
            "opencitations": _estat_opencitations(oc),
            "consolidado": asdict(resumo_cons),
        }, ests)
        relatorio.escrever(dir_saida, dados)
        for e in ests:
            log.info("%s: %s, %d registros%s", e.base, e.status, e.gravados, f" — {e.motivo}" if e.motivo else "")
        codigo = 0 if any(e.status in ("ok", "parcial") for e in ests) else 1
        log.info("concluído em %.1f s; saída em %s", time.monotonic() - inicio, dir_saida)
        return codigo, dir_saida
    finally:
        for h in handlers:
            log.removeHandler(h)
            h.close()


def _gerar_consolidado(dir_saida: Path, gravados: dict[str, list[Registro]], config: Config):
    """consolidado.csv (ESCOPO 9.5): funde as bases e remove duplicatas. Falha aqui não afeta os CSVs por base."""
    caminho = dir_saida / "consolidado.csv"
    regs = [r for b in config.bases_ativas for r in gravados.get(b, [])]
    try:
        linhas, resumo = consolidado.consolidar(regs, config.bases_ativas)
        consolidado.escrever(caminho, linhas, config.saida.separador_lista)
        log.info("consolidado: %d registros; %d duplicatas removidas; %d sem DOI ou resumo descartados; "
                 "%d artigos gravados (%d em 2+ bases)", resumo.registros_entrada, resumo.duplicatas_removidas,
                 resumo.sem_doi_ou_resumo, resumo.linhas, resumo.em_varias_bases)
    except Exception as e:  # noqa: BLE001
        log.exception("falha ao gerar o consolidado")
        consolidado.escrever(caminho, [], config.saida.separador_lista)
        resumo = consolidado.ResumoConsolidado(registros_entrada=len(regs),
                                               erro=higienizar_texto(f"{type(e).__name__}: {e}"))
    return resumo


def _opencitations(config: Config, cred: Credenciais, cache: CacheDisco | None, opcoes: dict) -> OpenCitations:
    """Cliente único do OpenCitations, com limitador próprio compartilhado entre as bases (seção 7)."""
    taxa, conc = 3.0, 3
    sob = config.limites.get("opencitations")
    if sob:
        taxa, conc = sob.taxa_rps or taxa, sob.concorrencia or conc
    olog = logging.getLogger("coletor.opencitations")
    lim = Limitador("opencitations", taxa, conc, logger=olog, **opcoes)
    cliente = ClienteHTTP("opencitations", lim, email=cred.CONTACT_EMAIL, timeout_s=config.execucao.timeout_s,
                          cache=cache, logger=olog)
    return OpenCitations(cliente, cred.OPENCITATIONS_TOKEN)


def _estat_opencitations(oc: OpenCitations | None) -> dict | None:
    if oc is None:
        return None
    lim = oc.cliente.limitador
    return {"chamadas_http": lim.n_chamadas, "chamadas_cache": oc.cliente.n_do_cache, "n_429": lim.n_429,
            "taxa_inicial": lim.taxa_inicial, "taxa_final": lim.taxa, "indisponivel": oc.indisponivel}


async def _executar_base(
    est: EstatisticasBase,
    config: Config,
    cred: Credenciais,
    dir_saida: Path,
    cache: CacheDisco | None,
    opcoes_limitador: dict,
    oc: OpenCitations | None = None,
    acumulado: list[Registro] | None = None,
    *,
    prazo: float | None = None,
) -> None:
    blog = logging.getLogger(f"coletor.{est.base}")
    t0 = time.monotonic()
    cls = BASES.get(est.base)
    arquivo = dir_saida / f"{est.base}.csv"
    est.arquivo_csv = arquivo.name
    escritor = EscritorCSV(arquivo, cls.colunas_extras if cls else [], config.saida.raw_json,
                           config.saida.separador_lista)
    cliente = limitador = None
    try:
        obrigatoria = CREDENCIAIS.get(est.base, (None, ()))[0]
        if cls is None:
            est.status, est.motivo = "pulada", "adaptador ainda não implementado"
            return
        if cls.desabilitado:
            est.status, est.motivo = "pulada", f"base desabilitada: {cls.desabilitado}"
            return
        if obrigatoria and not getattr(cred, obrigatoria):
            est.status, est.motivo = "pulada", f"credencial obrigatória {obrigatoria} ausente no .env"
            return

        taxa, conc = cls.limites_padrao(cred)
        sob = config.limites.get(est.base)
        if sob:
            taxa = sob.taxa_rps or taxa
            conc = sob.concorrencia or conc
        limitador = Limitador(est.base, taxa, conc, logger=blog, backoff=cls.backoff, **opcoes_limitador)
        est.taxa_inicial = taxa
        cliente = ClienteHTTP(est.base, limitador, email=cred.CONTACT_EMAIL, timeout_s=config.execucao.timeout_s,
                              cache=cache, logger=blog)
        adaptador = cls(Contexto(config, cred, cliente, est, blog, opencitations=oc))

        arvore = analisar(config.query)
        plano = adaptador.suporta(config.filtros)
        est.filtros_nativos = plano.nativos
        est.filtros_locais = plano.locais
        est.filtros_ignorados = plano.ignorados
        est.filtros_atendidos = plano.atendidos
        for msg in plano.ignorados:
            blog.warning("filtro ignorado — %s", msg)
        if plano.incompativel:
            est.status, est.motivo = "pulada", plano.incompativel
            blog.warning("base pulada: %s", plano.incompativel)
            return
        est.consulta_traduzida = higienizar_texto(adaptador.traduzir(arvore, plano))
        blog.info("início: consulta %r; filtros nativos %s; locais %s",
                  est.consulta_traduzida, plano.nativos or "—", plano.locais or "—")

        try:
            async with asyncio.timeout_at(prazo):
                async for lote in adaptador.buscar(arvore, plano, config.max_artigos_por_base):
                    lote = await adaptador.aplicar_enriquecimento(lote, config.enriquecimento)
                    est.gravados += escritor.escrever(lote)
                    if acumulado is not None:
                        for r in lote:  # o consolidado não usa estes campos grandes
                            r.raw = None
                            r.texto_completo = None
                        acumulado.extend(lote)
        except TimeoutError:
            # Só o prazo da pesquisa gera TimeoutError aqui (timeouts HTTP são exceções do httpx).
            est.status = "parcial" if est.gravados else "falhou"
            est.motivo = (f"tempo limite da pesquisa ({config.execucao.timeout_pesquisa_s:.0f} s) atingido "
                          f"com {est.gravados} de {config.max_artigos_por_base} artigos")
            blog.warning("base encerrada: %s", est.motivo)
    except EncerrarBase as e:
        est.status = e.status or ("parcial" if est.gravados else "falhou")
        est.motivo = higienizar_texto(e.motivo)
        blog.warning("base encerrada: %s", est.motivo)
    except TentativasEsgotadas as e:
        est.status = "parcial" if est.gravados else "falhou"
        est.motivo = f"tentativas esgotadas numa página ({e.ultimo})"
        blog.error(est.motivo)
    except ErroHTTP as e:
        est.status = "parcial" if est.gravados else "falhou"
        est.motivo = higienizar_texto(f"HTTP {e.status} (sem nova tentativa): {e.trecho}")
        blog.error("%s — %s", est.motivo, e.url)
    except Exception as e:  # uma base nunca derruba o processo
        est.status = "parcial" if est.gravados else "falhou"
        est.motivo = higienizar_texto(f"{type(e).__name__}: {e}")
        blog.exception("erro inesperado")
    finally:
        escritor.fechar()
        if cliente is not None:
            est.chamadas_cache = cliente.n_do_cache
            await cliente.fechar()
        if limitador is not None:
            est.chamadas_http = limitador.n_chamadas
            est.n_429 = limitador.n_429
            est.taxa_final = limitador.taxa
        est.duracao_s = round(time.monotonic() - t0, 2)
