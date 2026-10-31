import json

from coletor.bases import BASES
from coletor.bases.scielo import SciELO
from coletor.cli import listar_bases
from coletor.config import Filtros, carregar
from conftest import CRED, config, opcoes_rapidas
from coletor.orquestrador import executar


def test_marcada_desabilitada_com_motivo():
    assert BASES["scielo"] is SciELO and "robots.txt" in SciELO.desabilitado
    assert SciELO.suporta(object.__new__(SciELO), Filtros()).incompativel


def test_fora_das_bases_ativas_do_exemplo():
    assert "scielo" not in carregar("config.yaml").bases_ativas


def test_listar_bases_mostra_desabilitada():
    assert "scielo            desabilitada" in listar_bases(["scielo"], CRED)


async def test_se_ativada_e_pulada_sem_rede(tmp_path, relogio):
    codigo, d = await executar(config(bases_ativas=["scielo"], saida={"diretorio": str(tmp_path)}), CRED,
                               opcoes_limitador=opcoes_rapidas(relogio))
    rel = json.loads((d / "relatorio.json").read_text())["bases"][0]
    assert codigo == 1 and rel["status"] == "pulada" and "desabilitada" in rel["motivo"]
    assert (d / "scielo.csv").exists()
