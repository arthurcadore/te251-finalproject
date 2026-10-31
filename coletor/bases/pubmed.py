"""PubMed (NCBI E-utilities) — esearch + efetch (mapeamento a partir de tests/fixtures/pubmed/).

`esearch` com `sort=relevance` (sem ele a API devolve os mais recentes — ESCOPO 15.2); `efetch` em lote
(XML). Livros vêm como `PubmedBookArticle/BookDocument`.
"""

from __future__ import annotations

from typing import AsyncIterator

from lxml import etree

from ..config import Enriquecimento, Filtros
from ..consulta import No, para_pubmed
from ..enriquecimento import opencitations
from ..filtros import LOCAL, NATIVO, PlanoFiltros, planejar
from ..modelo import Registro, espacos, normalizar_doi, unicos
from ..segredos import Credenciais
from ..texto import ISO1_PARA_ISO2B, ano_de, data_iso, idioma_iso1, orcid
from .base import Adaptador, Pagina

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
TIPO_NATIVO = {"artigo": '"Journal Article"[pt]', "revisao": "Review[pt]", "preprint": "Preprint[pt]",
               "livro_capitulo": "booksdocs[filter]"}  # conferência: local (Congress[pt] não funciona)
REVISOES = {"Review", "Systematic Review", "Meta-Analysis", "Scoping Review"}


def _t(el, xp: str) -> str | None:
    r = el.xpath(xp)
    if not r:
        return None
    v = r[0] if isinstance(r[0], str) else "".join(r[0].itertext())
    return espacos(v)


def _todos(el, xp: str) -> list[str]:
    return unicos(espacos(x if isinstance(x, str) else "".join(x.itertext())) for x in el.xpath(xp))


def tipo_canonico(tipos: list[str], livro: bool = False) -> str | None:
    if livro:
        return "livro_capitulo"
    if set(tipos) & REVISOES:
        return "revisao"
    if "Preprint" in tipos:
        return "preprint"
    if "Congress" in tipos:
        return "conferencia"
    if "Journal Article" in tipos:
        return "artigo"
    return tipos[0] if tipos else None


def _resumo(el) -> str | None:
    partes = []
    for a in el.xpath(".//Abstract/AbstractText"):
        txt = espacos("".join(a.itertext()))
        if not txt:
            continue
        rotulo = a.get("Label")
        partes.append(f"{rotulo}: {txt}" if rotulo else txt)
    return "\n".join(partes) or None


def _data(el, livro: bool) -> tuple[int | None, str | None]:
    if not livro:
        ad = el.xpath("MedlineCitation/Article/ArticleDate")
        if ad:
            d = ad[0]
            return int(d.findtext("Year")), data_iso(d.findtext("Year"), d.findtext("Month"), d.findtext("Day"))
    pd = el.xpath(".//PubDate")
    if not pd:
        return None, None
    p = pd[0]
    if p.findtext("Year"):
        return int(p.findtext("Year")), data_iso(p.findtext("Year"), p.findtext("Month"), p.findtext("Day"))
    a = ano_de(p.findtext("MedlineDate"))
    return a, data_iso(a) if a else None


def _referencias(el) -> tuple[list[str], int | None]:
    refs = el.xpath("PubmedData/ReferenceList/Reference")
    if not refs:
        return [], None
    saida = []
    for r in refs:
        ids = {i.get("IdType"): (i.text or "").strip() for i in r.xpath("ArticleIdList/ArticleId")}
        if ids.get("doi"):
            saida.append(normalizar_doi(ids["doi"]))
        elif ids.get("pubmed"):
            saida.append(f"pmid:{ids['pubmed']}")
        elif ids.get("pmc"):
            saida.append(f"pmcid:{ids['pmc']}")
    return unicos(saida), len(refs)


class PubMed(Adaptador):
    chave = "pubmed"
    nome = "PubMed"
    colunas_extras = ["x_pubmed_mesh_qualificadores", "x_pubmed_pais_periodico", "x_pubmed_nlm_id",
                      "x_pubmed_status", "x_pubmed_conflito_interesses"]

    @classmethod
    def limites_padrao(cls, cred: Credenciais) -> tuple[float, int]:
        return (9 if cred.NCBI_API_KEY else 3), 3

    def suporta(self, filtros: Filtros) -> PlanoFiltros:
        idiomas = NATIVO if all(i in ISO1_PARA_ISO2B for i in filtros.idiomas) else LOCAL
        return planejar(filtros, nome_base=self.nome, periodo=NATIVO, idiomas=idiomas, somente_oa=NATIVO,
                        tipos_nativos=lambda tipos: "conferencia" not in tipos,
                        campos_nativos=frozenset({"tudo", "titulo", "titulo_resumo"}))

    def traduzir(self, arvore: No, plano: PlanoFiltros) -> str:
        f = self.ctx.config.filtros
        partes = [para_pubmed(arvore, f.campo_busca if plano.nativo("campo_busca") else "tudo")]
        if plano.nativo("periodo"):
            partes.append(f"{f.ano_de if f.ano_de is not None else 1800}:"
                          f"{f.ano_ate if f.ano_ate is not None else 3000}[dp]")
        if plano.nativo("idiomas"):
            partes.append(" OR ".join(f"{ISO1_PARA_ISO2B[i]}[la]" for i in f.idiomas))
        if plano.nativo("tipos"):
            partes.append(" OR ".join(TIPO_NATIVO[t] for t in f.tipos))
        if plano.nativo("somente_oa"):
            partes.append("free full text[sb]")
        return partes[0] if len(partes) == 1 else " AND ".join(f"({p})" for p in partes)

    def _base(self) -> dict:
        c = self.ctx.credenciais
        p = {"db": "pubmed", "tool": "coletor-artigos"}
        if c.CONTACT_EMAIL:
            p["email"] = c.CONTACT_EMAIL
        if c.NCBI_API_KEY:
            p["api_key"] = c.NCBI_API_KEY
        return p

    async def paginas(self, arvore: No, plano: PlanoFiltros, tamanho: int) -> AsyncIterator[Pagina]:
        termo = self.traduzir(arvore, plano)
        inicio = 0
        while True:
            r = await self.ctx.cliente.get(EUTILS + "esearch.fcgi", params={
                **self._base(), "term": termo, "retmode": "json", "sort": "relevance",
                "retstart": inicio, "retmax": tamanho})
            res = r.json().get("esearchresult") or {}
            if res.get("ERROR"):
                raise ValueError(f"esearch: {res['ERROR']}")
            ids = res.get("idlist") or []
            total = int(res["count"]) if str(res.get("count", "")).isdigit() else None
            regs: list[Registro] = []
            if ids:
                x = await self.ctx.cliente.get(EUTILS + "efetch.fcgi", params={
                    **self._base(), "id": ",".join(ids), "retmode": "xml"})
                regs = self.analisar_efetch(x.texto, ids)
            inicio += len(ids)
            ultima = not ids or (total is not None and inicio >= total)
            yield Pagina(regs, total, ultima=ultima)
            if ultima:
                return

    async def enriquecer(self, registros: list[Registro], opcoes: Enriquecimento) -> list[Registro]:
        """Referências nativas (ReferenceList) ou OpenCitations; citações pelo OpenCitations (DOI, senão PMID)."""
        if opcoes.referencias:
            await opencitations.enriquecer(registros, self.ctx.opencitations, self.log, usar_pmid=True)
        return registros

    def analisar_efetch(self, xml: str, ordem: list[str] | None = None) -> list[Registro]:
        raiz = etree.fromstring(xml.encode("utf-8"))
        regs = [self.normalizar(el) for el in raiz.xpath("PubmedArticle | PubmedBookArticle")]
        if ordem:  # mantém a ordem de relevância do esearch
            pos = {pmid: i for i, pmid in enumerate(ordem)}
            regs.sort(key=lambda r: pos.get(r.id_na_base, len(pos)))
        return regs

    def normalizar(self, el) -> Registro:
        livro = el.tag == "PubmedBookArticle"
        doc = el.find("BookDocument") if livro else el.find("MedlineCitation")
        art = doc if livro else doc.find("Article")
        pmid = _t(doc, "PMID/text()") or ""
        ids_xp = "BookDocument/ArticleIdList/ArticleId" if livro else "PubmedData/ArticleIdList/ArticleId"
        ids = {i.get("IdType"): (i.text or "").strip() for i in el.xpath(ids_xp)}
        if livro:  # o PMC/DOI do livro fica em PubmedBookData
            ids = {**{i.get("IdType"): (i.text or "").strip() for i in el.xpath("PubmedBookData/ArticleIdList/ArticleId")}, **ids}
        autores_el = art.xpath("AuthorList/Author")
        autores = [espacos(" ".join(x for x in (a.findtext("ForeName"), a.findtext("LastName")) if x))
                   or espacos(a.findtext("CollectiveName")) or "" for a in autores_el]
        tipos = _todos(art, "PublicationTypeList/PublicationType | PublicationType")
        ano, data = _data(el, livro)
        refs, n_refs = _referencias(el)
        mesh = el.xpath("MedlineCitation/MeshHeadingList/MeshHeading")
        if livro:
            veiculo = _t(art, "Book/BookTitle")
            issn: list[str] = []
            editora = _t(art, "Book/Publisher/PublisherName")
        else:
            veiculo = _t(art, "Journal/Title")
            issn = _todos(art, "Journal/ISSN")
            editora = None
        reg = Registro(
            base=self.chave,
            id_na_base=pmid,
            doi=normalizar_doi(ids.get("doi")),
            pmid=pmid or None,
            pmcid=ids.get("pmc") or None,
            url_pagina=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
            titulo=_t(art, "ArticleTitle") or _t(art, "Book/BookTitle"),
            autores=autores,
            autores_orcid=[orcid(_t(a, "Identifier[@Source='ORCID']/text()")) for a in autores_el],
            afiliacoes=_todos(art, "AuthorList/Author/AffiliationInfo/Affiliation"),
            ano=ano,
            data_publicacao=data,
            tipo=tipo_canonico(tipos, livro),
            idioma=idioma_iso1(_t(art, "Language/text()")),
            veiculo=veiculo,
            issn=issn,
            editora=editora,
            volume=None if livro else _t(art, "Journal/JournalIssue/Volume"),
            numero=None if livro else _t(art, "Journal/JournalIssue/Issue"),
            paginas=None if livro else _t(art, "Pagination/MedlinePgn"),
            resumo=_resumo(art),
            palavras_chave=_todos(el, ".//KeywordList/Keyword"),
            assuntos=unicos(_t(m, "DescriptorName") for m in mesh),
            n_referencias=n_refs,
            referencias=refs,
            fonte_referencias="nativa" if refs else "nenhuma",
            financiadores=_todos(art, "GrantList/Grant/Agency"),
            retratado=("Retracted Publication" in tipos) if tipos else None,
            raw={"pubmed_xml": etree.tostring(el, encoding="unicode")},
        )
        reg.extras = {
            "x_pubmed_mesh_qualificadores": [
                f"{_t(m, 'DescriptorName')}/{_t(q, '.')}" for m in mesh for q in m.xpath("QualifierName")],
            "x_pubmed_pais_periodico": _t(el, "MedlineCitation/MedlineJournalInfo/Country"),
            "x_pubmed_nlm_id": _t(el, "MedlineCitation/MedlineJournalInfo/NlmUniqueID"),
            "x_pubmed_status": doc.get("Status"),
            "x_pubmed_conflito_interesses": _t(el, "MedlineCitation/CoiStatement"),
        }
        return reg
