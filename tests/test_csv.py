import csv
import io

from coletor.modelo import COLUNAS, Registro
from coletor.saida.csv_writer import EscritorCSV, formatar
from conftest import CHAVE_FALSA

RESUMO = 'Primeira linha, com vírgula; "aspas" internas\r\nsegunda linha\rterceira — ação ✓'


def registro(**kw) -> Registro:
    r = Registro(base="openalex", id_na_base="W1", titulo='Título, "difícil"', resumo=RESUMO,
                 autores=["Ana | Silva", "Bob"], autores_orcid=["0000-0001", ""], acesso_aberto=True,
                 retratado=False, ano=2021, percentil_citacoes=0.9999, citacoes_por_ano={2024: 3, 2026: 1, 2025: 2},
                 extras={"x_a": ["p", "q"], "x_b": None}, raw={"api": "x", "texto": "a,b\n\"c\""})
    for k, v in kw.items():
        setattr(r, k, v)
    return r


def ler(caminho):
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))


def test_ida_e_volta(tmp_path):
    p = tmp_path / "openalex.csv"
    w = EscritorCSV(p, ["x_a", "x_b"])
    assert w.escrever([registro(), registro(id_na_base="W2")]) == 2
    w.fechar()
    linhas = ler(p)
    assert linhas[0] == COLUNAS + ["x_a", "x_b", "raw_json"]
    assert len(linhas) == 3
    lin = dict(zip(linhas[0], linhas[1]))
    assert lin["titulo"] == 'Título, "difícil"'
    assert lin["resumo"] == RESUMO.replace("\r\n", "\n").replace("\r", "\n")
    assert lin["autores"] == "Ana / Silva | Bob"
    assert lin["autores_orcid"] == "0000-0001 | "
    assert lin["acesso_aberto"] == "true" and lin["retratado"] == "false"
    assert lin["ano"] == "2021" and lin["percentil_citacoes"] == "0.9999"
    assert lin["citacoes_por_ano"] == "2026:1 | 2025:2 | 2024:3"
    assert lin["doi"] == "" and lin["fonte_referencias"] == "nenhuma"
    assert lin["x_a"] == "p | q" and lin["x_b"] == ""
    assert lin["raw_json"] == '{"api":"x","texto":"a,b\\n\\"c\\""}'


def test_formato_bruto_bom_aspas_e_crlf(tmp_path):
    p = tmp_path / "a.csv"
    w = EscritorCSV(p, [])
    w.escrever([registro()])
    w.fechar()
    bruto = p.read_bytes()
    assert bruto.startswith(b"\xef\xbb\xbf")
    texto = bruto.decode("utf-8-sig")
    cab = texto.split("\r\n", 1)[0]
    assert cab.startswith('"base","id_na_base"') and all(c.startswith('"') and c.endswith('"') for c in cab.split(","))
    assert '""difícil""' in texto  # aspas internas duplicadas
    assert "\r" not in texto.replace("\r\n", "")  # \r só como fim de registro


def test_sem_raw_json(tmp_path):
    p = tmp_path / "a.csv"
    w = EscritorCSV(p, ["x_a"], raw_json=False)
    w.escrever([registro()])
    w.fechar()
    assert ler(p)[0][-1] == "x_a"


def test_somente_cabecalho(tmp_path):
    p = tmp_path / "vazio.csv"
    EscritorCSV(p, []).fechar()
    assert ler(p) == [COLUNAS + ["raw_json"]]


def test_segredo_removido_do_raw_json(tmp_path):
    p = tmp_path / "a.csv"
    w = EscritorCSV(p, [])
    w.escrever([registro(raw={"url": f"https://x.org/?api_key={CHAVE_FALSA}"})])
    w.fechar()
    assert CHAVE_FALSA not in p.read_text(encoding="utf-8-sig")


def test_formatar():
    assert formatar(None) == "" and formatar([]) == "" and formatar(["", ""]) == ""
    assert formatar(["a|b", "c"]) == "a/b | c"
    assert formatar(["a", "b"], ";") == "a;b"
    assert formatar(float("nan")) == ""
    assert formatar("x\x00y") == "xy"


def test_le_com_modulo_csv_padrao_excel(tmp_path):
    """Leitura no dialeto padrão (o mesmo do Excel/LibreOffice/pandas) preserva as células."""
    p = tmp_path / "a.csv"
    w = EscritorCSV(p, [])
    w.escrever([registro()])
    w.fechar()
    dados = list(csv.DictReader(io.StringIO(p.read_text(encoding="utf-8-sig"))))
    assert dados[0]["resumo"].count("\n") == 2 and dados[0]["resumo"].startswith("Primeira linha, com vírgula")
