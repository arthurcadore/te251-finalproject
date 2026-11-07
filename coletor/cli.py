"""Linha de comando (seção 5.3). Argumentos sobrescrevem o config.yaml.

Códigos de saída: 0 se ao menos uma base gerou resultados (ok/parcial); 1 se todas falharam
ou foram puladas; 2 erro de configuração.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import os
import sys
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from . import config as cfg
from .bases import BASES, CREDENCIAIS
from .orquestrador import executar
from .segredos import Credenciais, registrar

CONFIG_PADRAO = "config.yaml"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m coletor",
                                description="Coletor multibase de artigos científicos.")
    p.add_argument("--config", help=f"arquivo YAML de configuração (padrão: {CONFIG_PADRAO}, se existir)")
    p.add_argument("--query", help="consulta (sobrescreve `query`)")
    p.add_argument("--max", type=int, help="máximo de artigos por base (sobrescreve `max_artigos_por_base`)")
    p.add_argument("--bases", help="bases separadas por vírgula (sobrescreve `bases_ativas`)")
    p.add_argument("--sem-raw-json", action="store_true", help="omite a coluna raw_json")
    p.add_argument("--web", "--gui", dest="web", action="store_true",
                   help="abre a interface HTTP (padrão: todas as interfaces; exige token)")
    p.add_argument("--host", default="0.0.0.0", help="endereço de bind web (padrão: 0.0.0.0)")
    p.add_argument("--port", type=int, default=8000, help="porta da interface HTTP (padrão: 8000)")
    p.add_argument("--graph", action="store_true",
                   help="com --web: mostra no histórico o grafo de artigos e referências compartilhadas")
    p.add_argument("--listar-bases", action="store_true",
                   help="mostra bases, status (ativa/inativa) e credenciais detectadas")
    return p


def _arquivo_config(arg: str | None) -> str | None:
    if arg:
        return arg
    return CONFIG_PADRAO if Path(CONFIG_PADRAO).exists() else None


def listar_bases(ativas: list[str] | None, cred: Credenciais) -> str:
    linhas = [f"{'base':<17} {'status':<34} credenciais"]
    for chave in cfg.CHAVES_BASES:
        cls = BASES.get(chave)
        if cls is None:
            status = "não implementada"
        elif cls.desabilitado:
            status = "desabilitada"
        elif ativas is None:
            status = "—"
        else:
            status = "ativa" if chave in ativas else "inativa"
        obrig, opcionais = CREDENCIAIS[chave]
        partes = []
        if obrig:
            partes.append(f"{obrig} (obrigatória): {'definida' if getattr(cred, obrig) else 'AUSENTE'}")
        for o in opcionais:
            partes.append(f"{o}: {'definida' if getattr(cred, o) else 'vazia'}")
        if obrig and not getattr(cred, obrig) and status == "ativa":
            status = "ativa (será pulada: sem credencial)"
        linhas.append(f"{chave:<17} {status:<34} {'; '.join(partes) or 'nenhuma'}")
        if cls is not None and cls.desabilitado:
            linhas.append(f"{'':<17} motivo: {cls.desabilitado}")
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.graph and not args.web:
        print("aviso: --graph só tem efeito com --web; ignorado.", file=sys.stderr)
    if args.web:
        if not 1 <= args.port <= 65535:
            print("erro: --port deve estar entre 1 e 65535", file=sys.stderr)
            return 2
        load_dotenv(find_dotenv(usecwd=True))
        try:
            host_local = args.host.casefold() == "localhost" or ipaddress.ip_address(args.host).is_loopback
        except ValueError:
            host_local = False
        if not host_local and len(os.getenv("COLETOR_WEB_TOKEN", "")) < 32:
            print(
                "erro: para expor a interface na rede, defina COLETOR_WEB_TOKEN no .env "
                "com pelo menos 32 caracteres aleatórios.",
                file=sys.stderr,
            )
            return 2
        import uvicorn

        # Lido pelo servidor (mesmo processo): liga ou desliga o grafo no histórico.
        os.environ["COLETOR_WEB_GRAFO"] = "1" if args.graph else "0"
        print(f"Interface web em http://{args.host}:{args.port} (Ctrl+C para encerrar)")
        if args.graph:
            print("Grafo de artigos e referências habilitado no histórico.")
        if not host_local:
            print("Acesso remoto protegido por página de login e sessão; use HTTPS via proxy reverso.")
        uvicorn.run("coletor.web:app", host=args.host, port=args.port, reload=False)
        return 0

    load_dotenv(find_dotenv(usecwd=True))
    cred = Credenciais.do_ambiente()
    registrar(cred)
    arquivo = _arquivo_config(args.config)

    if args.listar_bases:
        ativas = None
        if arquivo:
            try:
                ativas = cfg.carregar(arquivo).bases_ativas
            except cfg.ErroConfig as e:
                print(f"aviso: {e}", file=sys.stderr)
        print(listar_bases(ativas, cred))
        return 0

    sob: dict = {}
    if args.query is not None:
        sob["query"] = args.query
    if args.max is not None:
        sob["max_artigos_por_base"] = args.max
    if args.bases is not None:
        sob["bases_ativas"] = [b.strip() for b in args.bases.split(",") if b.strip()]
    if args.sem_raw_json:
        sob["saida.raw_json"] = False
    if arquivo is None and "query" not in sob:
        print("erro: informe --config (ou crie config.yaml) ou --query", file=sys.stderr)
        return 2
    try:
        config = cfg.carregar(arquivo, sob)
    except cfg.ErroConfig as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    codigo, diretorio = asyncio.run(executar(config, cred))
    print(f"saída em {diretorio}")
    return codigo
