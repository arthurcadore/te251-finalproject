from coletor.config import Filtros
from coletor.consulta import analisar
from coletor.filtros import LOCAL, NATIVO, SEM_DADO, TODOS, aplicar_locais, planejar
from coletor.modelo import Registro


def plano(f, **kw):
    padrao = dict(nome_base="Base", periodo=LOCAL, idiomas=LOCAL, somente_oa=LOCAL)
    return planejar(f, **{**padrao, **kw})


def reg(**kw):
    return Registro(base="b", id_na_base="1", **kw)


def test_sem_filtros_plano_vazio():
    p = plano(Filtros())
    assert p.modos == {} and not p.ignorados and p.incompativel is None


def test_modos_declarados():
    f = Filtros(ano_de=2020, idiomas=["pt"], somente_oa=True, tipos=["revisao"], campo_busca="titulo")
    p = plano(f, periodo=NATIVO, idiomas=SEM_DADO, somente_oa=TODOS, tipos_nativos=lambda t: True)
    assert p.nativos == ["periodo", "tipos"] and p.locais == ["campo_busca"]
    assert p.ignorados == ["idiomas: Base não informa esse dado"]
    assert p.atendidos and "somente_oa" in p.atendidos[0]


def test_tipos_unicos_incompativel_e_compativel():
    assert "só tem preprint" in plano(Filtros(tipos=["revisao"]), tipos_unicos=frozenset({"preprint"})).incompativel
    p = plano(Filtros(tipos=["revisao", "preprint"]), tipos_unicos=frozenset({"preprint"}))
    assert p.incompativel is None and "tipos" not in p.modos


def test_local_periodo_tipo_oa():
    f = Filtros(ano_de=2020, ano_ate=2022, tipos=["artigo"], somente_oa=True)
    p = plano(f)
    arv = analisar("x")
    assert aplicar_locais(reg(ano=2021, tipo="artigo", acesso_aberto=True), p, f, arv)
    assert not aplicar_locais(reg(ano=2019, tipo="artigo", acesso_aberto=True), p, f, arv)
    assert not aplicar_locais(reg(ano=2021, tipo="revisao", acesso_aberto=True), p, f, arv)
    assert not aplicar_locais(reg(ano=2021, tipo="artigo", acesso_aberto=False), p, f, arv)


def test_registro_sem_dado_e_mantido_com_aviso():
    f = Filtros(ano_de=2020, idiomas=["pt"], tipos=["artigo"], somente_oa=True)
    r = reg()
    assert aplicar_locais(r, plano(f), f, analisar("x"))
    assert set(r.avisos) == {"periodo_nao_verificado", "idioma_nao_verificado", "tipo_nao_verificado",
                             "oa_nao_verificado"}


def test_idioma_varios_do_registro():
    f = Filtros(idiomas=["pt"])
    r = reg(idioma="en")
    assert aplicar_locais(r, plano(f), f, analisar("x"), lambda r: ["en", "pt"])
    assert not aplicar_locais(r, plano(f), f, analisar("x"))


def test_campo_busca_local():
    arv = analisar('"machine learning"')
    f = Filtros(campo_busca="titulo")
    p = plano(f)
    assert aplicar_locais(reg(titulo="Machine learning for X"), p, f, arv)
    assert not aplicar_locais(reg(titulo="Deep nets", resumo="machine learning"), p, f, arv)
    f2 = Filtros(campo_busca="titulo_resumo")
    assert aplicar_locais(reg(titulo="Deep nets", resumo="uses machine learning"), plano(f2), f2, arv)
