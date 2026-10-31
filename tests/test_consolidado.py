"""CSV consolidado (ESCOPO 9.5): deduplicação entre bases e regras de fusão."""

import csv
import json

import httpx
import respx

from coletor.modelo import Registro
from coletor.orquestrador import executar
from coletor.saida.consolidado import COLUNAS_CONSOLIDADO, agrupar, consolidar, escrever, fundir, titulo_normalizado
from conftest import CRED, config, fixture, opcoes_rapidas

ORDEM = ["openalex", "semantic_scholar", "crossref", "arxiv", "pubmed", "europepmc", "core", "doaj"]
TITULO = "Machine learning applied to precision agriculture in Brazil"


def r(base, ident, **kw) -> Registro:
    return Registro(base=base, id_na_base=ident, **kw)


def grupos_ids(regs):
    return [[f"{x.base}:{x.id_na_base}" for x in g] for g in agrupar(regs)]


def test_agrupa_por_doi_pmid_pmcid_e_arxiv_transitivamente():
    regs = [
        r("pubmed", "1", doi="10.1/a", pmid="1"),
        r("europepmc", "1", pmid="1", pmcid="PMC9"),      # liga ao PubMed pelo PMID
        r("semantic_scholar", "s", pmcid="pmc9"),          # liga pelo PMCID (sem diferenciar caixa)
        r("arxiv", "2101.1", arxiv_id="2101.1"),
        r("openalex", "W1", doi="10.9/z", arxiv_id="2101.1v2"),  # liga pelo arXiv sem versão
        r("crossref", "10.5/x", doi="10.5/x"),
    ]
    assert grupos_ids(regs) == [
        ["pubmed:1", "europepmc:1", "semantic_scholar:s"],
        ["arxiv:2101.1", "openalex:W1"],
        ["crossref:10.5/x"],
    ]


def test_funde_por_titulo_longo_e_ano():
    regs = [r("core", "1", titulo=TITULO, ano=2021), r("core", "2", titulo=TITULO.upper() + ".", ano=2021),
            r("doaj", "d", titulo=TITULO, ano=2021, doi="10.1/a")]
    assert len(agrupar(regs)) == 1


def test_nao_funde_titulo_curto_ano_diferente_ou_dois_diferentes():
    assert len(agrupar([r("openalex", "1", titulo="Machine Learning", ano=2021),
                        r("crossref", "2", titulo="Machine learning", ano=2021)])) == 2
    assert len(agrupar([r("core", "1", titulo=TITULO, ano=2021), r("core", "2", titulo=TITULO, ano=2022)])) == 2
    assert len(agrupar([r("openalex", "1", titulo=TITULO, ano=2021, doi="10.1/preprint"),
                        r("crossref", "2", titulo=TITULO, ano=2021, doi="10.1/publicado")])) == 2


def test_titulo_normalizado():
    assert titulo_normalizado("Aprendizado de Máquina: uma revisão!") == "aprendizado de maquina uma revisao"


def test_regras_de_fusao():
    grupo = [
        r("arxiv", "2101.1", arxiv_id="2101.1", titulo="Título arXiv", resumo="resumo arxiv", tipo="preprint",
          url_pdf="https://arxiv.org/pdf/2101.1", n_citacoes=4, referencias=["10.1/r1", "10.1/r2"]),
        r("openalex", "W1", doi="10.9/z", arxiv_id="2101.1", titulo="Título OpenAlex", ano=2021, tipo="artigo",
          resumo="resumo openalex", idioma="en", issn=["1234-5678"], palavras_chave=["Machine Learning"],
          n_citacoes=10, fwci=1.5, n_referencias=30, referencias=["10.1/r2", "openalex:W9"], autores=["Ana"]),
        r("crossref", "10.9/z", doi="10.9/z", titulo="Título Crossref", ano=2022, tipo="artigo",
          issn=["1234-5678", "8765-4321"], palavras_chave=["machine learning", "agro"], n_citacoes=7,
          autores=["Ana Silva"]),
    ]
    linha = fundir(grupo, ORDEM)
    assert list(linha) == COLUNAS_CONSOLIDADO
    assert linha["doi"] == "10.9/z"
    assert linha["bases"] == ["openalex", "crossref", "arxiv"]
    assert linha["ids_por_base"] == ["arxiv:2101.1", "openalex:W1", "crossref:10.9/z"]
    assert linha["titulo"] == "Título Crossref" and linha["ano"] == 2022 and linha["autores"] == ["Ana Silva"]
    assert linha["resumo"] == "resumo openalex"  # prioridade de resumo: OpenAlex antes do arXiv
    assert linha["tipo"] == "artigo" and linha["idioma"] == "en"
    assert linha["palavras_chave"] == ["machine learning", "agro"]
    assert linha["url_pdf"] == "https://arxiv.org/pdf/2101.1"
    assert linha["n_citacoes"] == 10 and linha["n_referencias"] == 30
    assert linha["referencias"] == ["10.1/r2", "openalex:W9", "10.1/r1"]


def test_colunas_removidas_pelo_usuario():
    removidas = {"id_consolidado", "pmid", "pmcid", "arxiv_id", "url_pagina", "n_bases", "acesso_aberto",
                 "status_oa", "licenca", "fonte_n_citacoes", "fwci", "tldr", "issn"}
    assert not removidas & set(COLUNAS_CONSOLIDADO) and len(COLUNAS_CONSOLIDADO) == 16


def test_filtro_doi_e_resumo_depois_da_fusao():
    regs = [
        r("pubmed", "1", pmid="1", resumo="tem resumo"),                 # sem DOI aqui…
        r("crossref", "10.1/a", doi="10.1/a", pmid="1"),                 # …mas o grupo ganha DOI pelo Crossref
        r("openalex", "W2", doi="10.1/b"),                                # DOI sem resumo: sai
        r("arxiv", "2101.9", arxiv_id="2101.9", resumo="sem DOI"),        # resumo sem DOI: sai
    ]
    linhas, res = consolidar(regs, ORDEM)
    assert [x["doi"] for x in linhas] == ["10.1/a"] and linhas[0]["resumo"] == "tem resumo"
    assert (res.registros_entrada, res.duplicatas_removidas, res.sem_doi_ou_resumo, res.linhas, res.em_varias_bases) \
        == (4, 1, 2, 1, 1)


def test_consolidar_e_escrever(tmp_path):
    regs = [r("openalex", "W1", doi="10.1/a", titulo="A", resumo="x"),
            r("crossref", "10.1/a", doi="10.1/a", titulo="A"),
            r("arxiv", "1", doi="10.2/b", titulo='Título com "aspas", vírgula\ne quebra', resumo="y")]
    linhas, resumo = consolidar(regs, ORDEM)
    assert (resumo.registros_entrada, resumo.linhas, resumo.duplicatas_removidas, resumo.em_varias_bases) == (3, 2, 1, 1)
    p = tmp_path / "consolidado.csv"
    escrever(p, linhas)
    assert p.read_bytes().startswith(b"\xef\xbb\xbf")
    lidas = list(csv.reader(open(p, encoding="utf-8-sig", newline="")))
    assert lidas[0] == COLUNAS_CONSOLIDADO and len(lidas) == 3
    assert lidas[1][COLUNAS_CONSOLIDADO.index("bases")] == "openalex | crossref"
    assert lidas[2][COLUNAS_CONSOLIDADO.index("titulo")] == 'Título com "aspas", vírgula\ne quebra'


# ---------------------------------------------------------------- de ponta a ponta


@respx.mock
async def test_execucao_gera_consolidado_sem_duplicatas(tmp_path, relogio):
    """busca.json (OpenAlex) e campo_titulo.xml (arXiv) compartilham o DOI 10.1007/s12525-021-00475-2."""
    respx.get("https://api.openalex.org/works").mock(return_value=httpx.Response(
        200, text=fixture("openalex", "busca.json"), headers={"x-ratelimit-remaining-usd": "0.9"}))
    respx.get("https://export.arxiv.org/api/query").mock(
        return_value=httpx.Response(200, text=fixture("arxiv", "campo_titulo.xml")))
    c = config(bases_ativas=["openalex", "arxiv"], max_artigos_por_base=5, saida={"diretorio": str(tmp_path)},
               enriquecimento={"referencias": False, "resolver_ids_para_doi": False, "texto_completo": False})
    codigo, d = await executar(c, CRED, opcoes_limitador=opcoes_rapidas(relogio))
    assert codigo == 0
    linhas = list(csv.DictReader(open(d / "consolidado.csv", encoding="utf-8-sig", newline="")))
    # 10 registros; 1 duplicata (DOI em comum); 5 descartados: 1 do OpenAlex sem resumo, 4 do arXiv sem DOI
    assert len(linhas) == 4 and all(x["doi"] and x["resumo"] for x in linhas)
    comum = [x for x in linhas if x["doi"] == "10.1007/s12525-021-00475-2"]
    assert len(comum) == 1 and comum[0]["bases"] == "openalex | arxiv" and comum[0]["n_citacoes"]
    assert "arxiv:" in comum[0]["ids_por_base"] and "openalex:W3153990350" in comum[0]["ids_por_base"]
    assert len({x["doi"] for x in linhas}) == 4
    rel = json.loads((d / "relatorio.json").read_text())
    assert rel["consolidado"] == {"registros_entrada": 10, "linhas": 4, "duplicatas_removidas": 1,
                                  "sem_doi_ou_resumo": 5, "em_varias_bases": 1, "arquivo": "consolidado.csv",
                                  "erro": None}
    assert "5 artigos sem DOI ou sem resumo descartados" in (d / "relatorio.md").read_text()
    # os CSVs por base continuam completos
    assert len(list(csv.reader(open(d / "openalex.csv", encoding="utf-8-sig", newline="")))) == 6


async def test_consolidado_so_cabecalho_quando_nenhuma_base_roda(tmp_path, relogio):
    codigo, d = await executar(config(bases_ativas=["scielo"], saida={"diretorio": str(tmp_path)}), CRED,
                               opcoes_limitador=opcoes_rapidas(relogio))
    assert codigo == 1
    assert list(csv.reader(open(d / "consolidado.csv", encoding="utf-8-sig", newline=""))) == [COLUNAS_CONSOLIDADO]
