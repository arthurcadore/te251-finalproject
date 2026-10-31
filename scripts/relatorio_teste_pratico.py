"""Gera docs/relatorio_teste_pratico.md a partir de tests/fixtures/ (offline).

O mapeamento coluna → campo de cada base abaixo foi escrito a partir das respostas
gravadas; a taxa de preenchimento é recalculada sobre todos os registros das fixtures
de busca da base (busca, página 2 e variantes de filtro, sem repetir IDs).
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from lxml import etree

COLUNAS = [
    "base", "id_na_base", "doi", "pmid", "pmcid", "arxiv_id", "url_pagina", "consulta", "coletado_em",
    "titulo", "autores", "autores_orcid", "afiliacoes", "ano", "data_publicacao", "tipo", "idioma",
    "veiculo", "issn", "editora", "volume", "numero", "paginas", "resumo", "tldr", "palavras_chave",
    "assuntos", "texto_completo", "acesso_aberto", "status_oa", "licenca", "url_pdf", "n_citacoes",
    "n_citacoes_influentes", "citacoes_por_ano", "percentil_citacoes", "fwci", "n_referencias",
    "referencias", "relacionados", "fonte_referencias", "fonte_citacoes", "financiadores", "retratado",
    "avisos",
]
GERADAS = {"base", "consulta", "coletado_em", "fonte_referencias", "fonte_citacoes", "avisos"}
BASES = ["openalex", "semantic_scholar", "crossref", "arxiv", "pubmed", "europepmc", "core", "doaj", "scielo"]
ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom",
        "opensearch": "http://a9.com/-/spec/opensearch/1.1/"}

# ---------------------------------------------------------------- acesso a campos


def pegar(obj, caminho: str) -> list:
    """Caminho pontuado; listas são percorridas automaticamente. Devolve folhas não vazias."""
    atuais = [obj]
    for parte in caminho.split("."):
        prox = []
        for a in atuais:
            if isinstance(a, list):
                prox += [x.get(parte) for x in a if isinstance(x, dict)]
            elif isinstance(a, dict):
                prox.append(a.get(parte))
        atuais = []
        for p in prox:
            atuais += p if isinstance(p, list) else [p]
    return [a for a in atuais if a not in (None, "", [], {})]


def xp(expr: str):
    def f(rec):
        r = rec.xpath(expr, namespaces=ATOM)
        return [x for x in r if (x.strip() if isinstance(x, str) else True)]
    return f


# Cada mapeamento: coluna → (descrição da fonte, função | caminho | None).
# "E:" na descrição = preenchido no enriquecimento (seção 8.1); "fixo:" = valor constante da base.

def _oa_arxiv(rec):
    urls = pegar(rec, "locations.landing_page_url")
    return [u for u in urls if "arxiv.org/abs/" in u]


MAPA: dict[str, dict] = {
    "openalex": {
        "id_na_base": ("id", "id"), "doi": ("doi", "doi"), "pmid": ("ids.pmid", "ids.pmid"),
        "pmcid": ("ids.pmcid", "ids.pmcid"),
        "arxiv_id": ("derivado de locations[].landing_page_url (arxiv.org/abs/…)", _oa_arxiv),
        "url_pagina": ("primary_location.landing_page_url", "primary_location.landing_page_url"),
        "titulo": ("title", "title"), "autores": ("authorships[].author.display_name", "authorships.author.display_name"),
        "autores_orcid": ("authorships[].author.orcid", "authorships.author.orcid"),
        "afiliacoes": ("authorships[].institutions[].display_name (alt.: raw_affiliation_strings)", "authorships.institutions.display_name"),
        "ano": ("publication_year", "publication_year"), "data_publicacao": ("publication_date", "publication_date"),
        "tipo": ("type", "type"), "idioma": ("language", "language"),
        "veiculo": ("primary_location.source.display_name", "primary_location.source.display_name"),
        "issn": ("primary_location.source.issn[]", "primary_location.source.issn"),
        "editora": ("primary_location.source.host_organization_name", "primary_location.source.host_organization_name"),
        "volume": ("biblio.volume", "biblio.volume"), "numero": ("biblio.issue", "biblio.issue"),
        "paginas": ("biblio.first_page–last_page", "biblio.first_page"),
        "resumo": ("abstract_inverted_index (reconstruído)", "abstract_inverted_index"),
        "tldr": ("—", None), "palavras_chave": ("keywords[].display_name", "keywords.display_name"),
        "assuntos": ("topics[].display_name (+ concepts[].display_name)", "topics.display_name"),
        "texto_completo": ("— (endpoint de conteúdo é pago)", None),
        "acesso_aberto": ("open_access.is_oa", lambda r: [str(x) for x in pegar(r, "open_access.is_oa")]),
        "status_oa": ("open_access.oa_status", "open_access.oa_status"),
        "licenca": ("best_oa_location.license (alt.: primary_location.license)", "best_oa_location.license"),
        "url_pdf": ("best_oa_location.pdf_url (alt.: open_access.oa_url)", "best_oa_location.pdf_url"),
        "n_citacoes": ("cited_by_count", lambda r: [str(x) for x in pegar(r, "cited_by_count")]),
        "n_citacoes_influentes": ("—", None),
        "citacoes_por_ano": ("counts_by_year[] (year:cited_by_count)", "counts_by_year.year"),
        "percentil_citacoes": ("citation_normalized_percentile.value", "citation_normalized_percentile.value"),
        "fwci": ("fwci", "fwci"),
        "n_referencias": ("referenced_works_count", lambda r: [str(x) for x in pegar(r, "referenced_works_count")]),
        "referencias": ("referenced_works[] (IDs W; E: convertidos em DOI por lote)", "referenced_works"),
        "relacionados": ("related_works[] (IDs W; E: convertidos em DOI por lote)", "related_works"),
        "financiadores": ("funders[].display_name (alt.: awards[].funder_display_name)", "funders.display_name"),
        "retratado": ("is_retracted", lambda r: [str(x) for x in pegar(r, "is_retracted")]),
    },
    "semantic_scholar": {
        "id_na_base": ("paperId", "paperId"), "doi": ("externalIds.DOI", "externalIds.DOI"),
        "pmid": ("externalIds.PubMed", "externalIds.PubMed"), "pmcid": ("externalIds.PubMedCentral", "externalIds.PubMedCentral"),
        "arxiv_id": ("externalIds.ArXiv", "externalIds.ArXiv"), "url_pagina": ("url", "url"),
        "titulo": ("title", "title"), "autores": ("authors[].name", "authors.name"),
        "autores_orcid": ("authors[].externalIds.ORCID", "authors.externalIds.ORCID"),
        "afiliacoes": ("authors[].affiliations[]", "authors.affiliations"),
        "ano": ("year", "year"), "data_publicacao": ("publicationDate", "publicationDate"),
        "tipo": ("publicationTypes[]", "publicationTypes"), "idioma": ("—", None),
        "veiculo": ("publicationVenue.name (alt.: venue, journal.name)", "publicationVenue.name"),
        "issn": ("publicationVenue.issn", "publicationVenue.issn"), "editora": ("—", None),
        "volume": ("journal.volume", "journal.volume"), "numero": ("—", None), "paginas": ("journal.pages", "journal.pages"),
        "resumo": ("abstract", "abstract"), "tldr": ("tldr.text", "tldr.text"), "palavras_chave": ("—", None),
        "assuntos": ("s2FieldsOfStudy[].category (+ fieldsOfStudy[])", "s2FieldsOfStudy.category"),
        "texto_completo": ("—", None),
        "acesso_aberto": ("isOpenAccess", lambda r: [str(x) for x in pegar(r, "isOpenAccess")]),
        "status_oa": ("openAccessPdf.status", "openAccessPdf.status"), "licenca": ("openAccessPdf.license", "openAccessPdf.license"),
        "url_pdf": ("openAccessPdf.url", "openAccessPdf.url"),
        "n_citacoes": ("citationCount", lambda r: [str(x) for x in pegar(r, "citationCount")]),
        "n_citacoes_influentes": ("influentialCitationCount", lambda r: [str(x) for x in pegar(r, "influentialCitationCount")]),
        "citacoes_por_ano": ("—", None), "percentil_citacoes": ("—", None), "fwci": ("—", None),
        "n_referencias": ("referenceCount", lambda r: [str(x) for x in pegar(r, "referenceCount")]),
        "referencias": ("E: POST /paper/batch → references[].externalIds.DOI | s2:paperId", None),
        "relacionados": ("—", None), "financiadores": ("—", None), "retratado": ("—", None),
    },
    "crossref": {
        "id_na_base": ("DOI", "DOI"), "doi": ("DOI", "DOI"), "pmid": ("—", None), "pmcid": ("—", None),
        "arxiv_id": ("—", None), "url_pagina": ("URL (doi.org) / resource.primary.URL", "URL"),
        "titulo": ("title[] (+ subtitle[])", "title"), "autores": ("author[].given + family (ou name)", "author.family"),
        "autores_orcid": ("author[].ORCID", "author.ORCID"), "afiliacoes": ("author[].affiliation[].name", "author.affiliation.name"),
        "ano": ("published.date-parts[0][0] (alt.: issued)", "published.date-parts"),
        "data_publicacao": ("published.date-parts (precisão variável: ano, ano-mês ou data)", "published.date-parts"),
        "tipo": ("type", "type"), "idioma": ("language", "language"), "veiculo": ("container-title[]", "container-title"),
        "issn": ("ISSN[]", "ISSN"), "editora": ("publisher", "publisher"), "volume": ("volume", "volume"),
        "numero": ("issue", "issue"), "paginas": ("page", "page"), "resumo": ("abstract (JATS → texto)", "abstract"),
        "tldr": ("—", None), "palavras_chave": ("—", None), "assuntos": ("subject[] (ausente nas respostas)", "subject"),
        "texto_completo": ("—", None),
        "acesso_aberto": ("derivado: license[].URL creativecommons (filtro local)", lambda r: [u for u in pegar(r, "license.URL") if "creativecommons" in u]),
        "status_oa": ("—", None), "licenca": ("license[].URL", "license.URL"),
        "url_pdf": ("link[] com content-type application/pdf", lambda r: [l for l in (r.get("link") or []) if l.get("content-type") == "application/pdf"]),
        "n_citacoes": ("is-referenced-by-count", lambda r: [str(x) for x in pegar(r, "is-referenced-by-count")]),
        "n_citacoes_influentes": ("—", None), "citacoes_por_ano": ("—", None), "percentil_citacoes": ("—", None),
        "fwci": ("—", None), "n_referencias": ("references-count", lambda r: [str(x) for x in pegar(r, "references-count")]),
        "referencias": ("reference[].DOI (quando depositado; senão E: OpenCitations)", "reference.DOI"),
        "relacionados": ("—", None), "financiadores": ("funder[].name", "funder.name"),
        "retratado": ("updated-by[] tipo retraction (ausente nas respostas)", "updated-by"),
    },
    "arxiv": {
        "id_na_base": ("id (http://arxiv.org/abs/<id>v<n>)", xp("a:id/text()")), "doi": ("arxiv:doi", xp("arxiv:doi/text()")),
        "pmid": ("—", None), "pmcid": ("—", None), "arxiv_id": ("id sem versão", xp("a:id/text()")),
        "url_pagina": ("link[@rel=alternate]/@href", xp("a:link[@rel='alternate']/@href")),
        "titulo": ("title", xp("a:title/text()")), "autores": ("author/name", xp("a:author/a:name/text()")),
        "autores_orcid": ("—", None), "afiliacoes": ("author/arxiv:affiliation", xp("a:author/arxiv:affiliation/text()")),
        "ano": ("published (ano)", xp("a:published/text()")), "data_publicacao": ("published (data da v1)", xp("a:published/text()")),
        "tipo": ("fixo: preprint", True), "idioma": ("—", None), "veiculo": ("fixo: arXiv", True),
        "issn": ("—", None), "editora": ("—", None), "volume": ("—", None), "numero": ("—", None), "paginas": ("—", None),
        "resumo": ("summary", xp("a:summary/text()")), "tldr": ("—", None), "palavras_chave": ("—", None),
        "assuntos": ("category/@term", xp("a:category/@term")), "texto_completo": ("—", None),
        "acesso_aberto": ("fixo: true", True), "status_oa": ("—", None), "licenca": ("— (não vem na API Atom)", None),
        "url_pdf": ("link[@title=pdf]/@href", xp("a:link[@title='pdf']/@href")),
        "n_citacoes": ("E: OpenCitations /citation-count (pelo DOI)", None), "n_citacoes_influentes": ("—", None),
        "citacoes_por_ano": ("—", None), "percentil_citacoes": ("—", None), "fwci": ("—", None),
        "n_referencias": ("E: OpenCitations", None), "referencias": ("E: OpenCitations (pelo DOI)", None),
        "relacionados": ("—", None), "financiadores": ("—", None), "retratado": ("—", None),
    },
    "pubmed": {
        "id_na_base": ("MedlineCitation/PMID", xp("MedlineCitation/PMID/text()")),
        "doi": ("ArticleIdList/ArticleId[@IdType=doi]", xp("PubmedData/ArticleIdList/ArticleId[@IdType='doi']/text()")),
        "pmid": ("MedlineCitation/PMID", xp("MedlineCitation/PMID/text()")),
        "pmcid": ("ArticleIdList/ArticleId[@IdType=pmc]", xp("PubmedData/ArticleIdList/ArticleId[@IdType='pmc']/text()")),
        "arxiv_id": ("—", None), "url_pagina": ("derivado: https://pubmed.ncbi.nlm.nih.gov/<PMID>/", xp("MedlineCitation/PMID/text()")),
        "titulo": ("Article/ArticleTitle", xp("MedlineCitation/Article/ArticleTitle//text()")),
        "autores": ("Author/LastName + ForeName (ou CollectiveName)", xp("MedlineCitation/Article/AuthorList/Author/LastName/text()")),
        "autores_orcid": ("Author/Identifier[@Source=ORCID]", xp("MedlineCitation/Article/AuthorList/Author/Identifier[@Source='ORCID']/text()")),
        "afiliacoes": ("Author/AffiliationInfo/Affiliation", xp("MedlineCitation/Article/AuthorList/Author/AffiliationInfo/Affiliation/text()")),
        "ano": ("JournalIssue/PubDate/Year (alt.: MedlineDate)", xp("MedlineCitation/Article/Journal/JournalIssue/PubDate/Year/text()")),
        "data_publicacao": ("Article/ArticleDate (alt.: PubDate)", xp("MedlineCitation/Article/ArticleDate/Year/text()")),
        "tipo": ("PublicationTypeList/PublicationType", xp("MedlineCitation/Article/PublicationTypeList/PublicationType/text()")),
        "idioma": ("Article/Language (3 letras → ISO 639-1)", xp("MedlineCitation/Article/Language/text()")),
        "veiculo": ("Journal/Title", xp("MedlineCitation/Article/Journal/Title/text()")),
        "issn": ("Journal/ISSN", xp("MedlineCitation/Article/Journal/ISSN/text()")), "editora": ("—", None),
        "volume": ("JournalIssue/Volume", xp("MedlineCitation/Article/Journal/JournalIssue/Volume/text()")),
        "numero": ("JournalIssue/Issue", xp("MedlineCitation/Article/Journal/JournalIssue/Issue/text()")),
        "paginas": ("Pagination/MedlinePgn", xp("MedlineCitation/Article/Pagination/MedlinePgn/text()")),
        "resumo": ("Abstract/AbstractText (com @Label)", xp("MedlineCitation/Article/Abstract/AbstractText//text()")),
        "tldr": ("—", None), "palavras_chave": ("KeywordList/Keyword", xp("MedlineCitation/KeywordList/Keyword/text()")),
        "assuntos": ("MeshHeadingList/MeshHeading/DescriptorName", xp("MedlineCitation/MeshHeadingList/MeshHeading/DescriptorName/text()")),
        "texto_completo": ("—", None), "acesso_aberto": ("— (filtro nativo apenas)", None), "status_oa": ("—", None),
        "licenca": ("—", None), "url_pdf": ("—", None),
        "n_citacoes": ("E: OpenCitations /citation-count", None), "n_citacoes_influentes": ("—", None),
        "citacoes_por_ano": ("—", None), "percentil_citacoes": ("—", None), "fwci": ("—", None),
        "n_referencias": ("contagem de PubmedData/ReferenceList/Reference", xp("PubmedData/ReferenceList/Reference")),
        "referencias": ("PubmedData/ReferenceList/Reference/ArticleIdList (nativo, quando houver; senão E: OpenCitations)",
                        xp("PubmedData/ReferenceList/Reference/ArticleIdList/ArticleId/text()")),
        "relacionados": ("—", None),
        "financiadores": ("GrantList/Grant/Agency", xp("MedlineCitation/Article/GrantList/Grant/Agency/text()")),
        "retratado": ("derivado: PublicationType 'Retracted Publication'", None),
    },
    "europepmc": {
        "id_na_base": ("id (com source em x_epmc_fonte)", "id"), "doi": ("doi", "doi"), "pmid": ("pmid", "pmid"),
        "pmcid": ("pmcid", "pmcid"), "arxiv_id": ("—", None),
        "url_pagina": ("derivado: https://europepmc.org/article/<source>/<id>", "id"),
        "titulo": ("title", "title"), "autores": ("authorList.author[].fullName", "authorList.author.fullName"),
        "autores_orcid": ("authorList.author[].authorId (type=ORCID)", "authorList.author.authorId.value"),
        "afiliacoes": ("authorList.author[].authorAffiliationDetailsList…affiliation (alt.: affiliation)", "authorList.author.authorAffiliationDetailsList.authorAffiliation.affiliation"),
        "ano": ("pubYear", "pubYear"), "data_publicacao": ("firstPublicationDate", "firstPublicationDate"),
        "tipo": ("pubTypeList.pubType[]", "pubTypeList.pubType"), "idioma": ("language (3 letras → ISO 639-1)", "language"),
        "veiculo": ("journalInfo.journal.title (preprint: bookOrReportDetails.publisher)", "journalInfo.journal.title"),
        "issn": ("journalInfo.journal.issn / essn", "journalInfo.journal.issn"), "editora": ("—", None),
        "volume": ("journalInfo.volume", "journalInfo.volume"), "numero": ("journalInfo.issue", "journalInfo.issue"),
        "paginas": ("pageInfo", "pageInfo"), "resumo": ("abstractText (HTML → texto)", "abstractText"), "tldr": ("—", None),
        "palavras_chave": ("keywordList.keyword[]", "keywordList.keyword"),
        "assuntos": ("meshHeadingList.meshHeading[].descriptorName", "meshHeadingList.meshHeading.descriptorName"),
        "texto_completo": ("E: /{PMCID}/fullTextXML (OA com PMCID) → texto", None),
        "acesso_aberto": ("isOpenAccess (Y/N)", "isOpenAccess"), "status_oa": ("—", None), "licenca": ("license", "license"),
        "url_pdf": ("fullTextUrlList.fullTextUrl[] documentStyle=pdf, availability=Open access",
                    lambda r: [u for u in pegar(r, "fullTextUrlList.fullTextUrl") if u.get("documentStyle") == "pdf" and u.get("availabilityCode") == "OA"]),
        "n_citacoes": ("citedByCount", lambda r: [str(x) for x in pegar(r, "citedByCount")]),
        "n_citacoes_influentes": ("—", None), "citacoes_por_ano": ("—", None), "percentil_citacoes": ("—", None),
        "fwci": ("—", None), "n_referencias": ("E: /{source}/{id}/references (hitCount)", None),
        "referencias": ("E: /{source}/{id}/references quando hasReferences=Y", None), "relacionados": ("—", None),
        "financiadores": ("grantsList.grant[].agency", "grantsList.grant.agency"),
        "retratado": ("derivado: pubType 'Retracted Publication'", None),
    },
    "core": {
        "id_na_base": ("id", lambda r: [str(r["id"])] if r.get("id") else []), "doi": ("doi", "doi"),
        "pmid": ("pubmedId", "pubmedId"), "pmcid": ("—", None), "arxiv_id": ("arxivId", "arxivId"),
        "url_pagina": ("links[] type=display", lambda r: [l for l in r.get("links") or [] if l.get("type") == "display"]),
        "titulo": ("title", "title"), "autores": ("authors[].name", "authors.name"), "autores_orcid": ("—", None),
        "afiliacoes": ("—", None), "ano": ("yearPublished", "yearPublished"), "data_publicacao": ("publishedDate", "publishedDate"),
        "tipo": ("documentType", "documentType"), "idioma": ("language.code", "language.code"),
        "veiculo": ("journals[].title", "journals.title"), "issn": ("journals[].identifiers[] (issn:…)", "journals.identifiers"),
        "editora": ("publisher", "publisher"), "volume": ("—", None), "numero": ("—", None), "paginas": ("—", None),
        "resumo": ("abstract", "abstract"), "tldr": ("—", None), "palavras_chave": ("—", None),
        "assuntos": ("fieldOfStudy", "fieldOfStudy"),
        "texto_completo": ("fullText — sem chave vem 'Not available for public API users.'",
                           lambda r: [t for t in pegar(r, "fullText") if t != "Not available for public API users."]),
        "acesso_aberto": ("fixo: true", True), "status_oa": ("—", None), "licenca": ("—", None),
        "url_pdf": ("downloadUrl", "downloadUrl"),
        "n_citacoes": ("citationCount vem sempre 0 → E: OpenCitations", lambda r: [x for x in pegar(r, "citationCount") if x]),
        "n_citacoes_influentes": ("—", None), "citacoes_por_ano": ("—", None), "percentil_citacoes": ("—", None),
        "fwci": ("—", None), "n_referencias": ("contagem de references[]", "references"),
        "referencias": ("references[].doi (parcial; E: OpenCitations)", "references.doi"), "relacionados": ("—", None),
        "financiadores": ("—", None), "retratado": ("—", None),
    },
    "doaj": {
        "id_na_base": ("id", "id"),
        "doi": ("bibjson.identifier[type=doi].id", lambda r: [i["id"] for i in pegar(r, "bibjson.identifier") if i.get("type") == "doi"]),
        "pmid": ("—", None), "pmcid": ("—", None), "arxiv_id": ("—", None),
        "url_pagina": ("bibjson.link[type=fulltext].url", "bibjson.link.url"), "titulo": ("bibjson.title", "bibjson.title"),
        "autores": ("bibjson.author[].name", "bibjson.author.name"), "autores_orcid": ("bibjson.author[].orcid_id", "bibjson.author.orcid_id"),
        "afiliacoes": ("bibjson.author[].affiliation", "bibjson.author.affiliation"), "ano": ("bibjson.year", "bibjson.year"),
        "data_publicacao": ("bibjson.year + month (só ano-mês)", "bibjson.month"), "tipo": ("fixo: artigo", True),
        "idioma": ("bibjson.journal.language[] (idioma do periódico, maiúsculas)", "bibjson.journal.language"),
        "veiculo": ("bibjson.journal.title", "bibjson.journal.title"), "issn": ("bibjson.journal.issns[]", "bibjson.journal.issns"),
        "editora": ("bibjson.journal.publisher", "bibjson.journal.publisher"), "volume": ("bibjson.journal.volume", "bibjson.journal.volume"),
        "numero": ("bibjson.journal.number", "bibjson.journal.number"), "paginas": ("bibjson.start_page–end_page", "bibjson.start_page"),
        "resumo": ("bibjson.abstract", "bibjson.abstract"), "tldr": ("—", None), "palavras_chave": ("bibjson.keywords[]", "bibjson.keywords"),
        "assuntos": ("bibjson.subject[].term", "bibjson.subject.term"), "texto_completo": ("—", None),
        "acesso_aberto": ("fixo: true", True), "status_oa": ("—", None), "licenca": ("— (licença é do periódico)", None),
        "url_pdf": ("bibjson.link[content_type=PDF].url", lambda r: [l for l in pegar(r, "bibjson.link") if str(l.get("content_type")).upper() == "PDF"]),
        "n_citacoes": ("E: OpenCitations", None), "n_citacoes_influentes": ("—", None), "citacoes_por_ano": ("—", None),
        "percentil_citacoes": ("—", None), "fwci": ("—", None), "n_referencias": ("E: OpenCitations", None),
        "referencias": ("E: OpenCitations (pelo DOI)", None), "relacionados": ("—", None), "financiadores": ("—", None),
        "retratado": ("—", None),
    },
}

# Colunas x_<base>_* propostas: (coluna, campo de origem)
EXTRAS = {
    "openalex": [("x_openalex_topico_principal", "primary_topic.display_name", "primary_topic.display_name"),
                 ("x_openalex_area", "primary_topic.field.display_name", "primary_topic.field.display_name"),
                 ("x_openalex_tipo_fonte", "primary_location.source.type", "primary_location.source.type"),
                 ("x_openalex_paises", "authorships[].countries[] (únicos)", "authorships.countries"),
                 ("x_openalex_indexado_em", "indexed_in[]", "indexed_in"),
                 ("x_openalex_apc_usd", "apc_paid.value_usd", "apc_paid.value_usd"),
                 ("x_openalex_ods", "sustainable_development_goals[].display_name", "sustainable_development_goals.display_name"),
                 ("x_openalex_mesh", "mesh[].descriptor_name", "mesh.descriptor_name")],
    "semantic_scholar": [("x_s2_corpus_id", "corpusId", "corpusId"), ("x_s2_dblp", "externalIds.DBLP", "externalIds.DBLP"),
                         ("x_s2_mag", "externalIds.MAG", "externalIds.MAG"),
                         ("x_s2_tipo_veiculo", "publicationVenue.type", "publicationVenue.type")],
    "crossref": [("x_crossref_isbn", "ISBN[]", "ISBN"), ("x_crossref_evento", "event.name", "event.name"),
                 ("x_crossref_numero_artigo", "article-number", "article-number"), ("x_crossref_subtitulo", "subtitle[]", "subtitle"),
                 ("x_crossref_subtipo", "subtype", "subtype"), ("x_crossref_membro", "member", "member")],
    "arxiv": [("x_arxiv_comentario", "arxiv:comment", xp("arxiv:comment/text()")),
              ("x_arxiv_journal_ref", "arxiv:journal_ref", xp("arxiv:journal_ref/text()")),
              ("x_arxiv_categoria_primaria", "arxiv:primary_category/@term", xp("arxiv:primary_category/@term")),
              ("x_arxiv_atualizado_em", "updated", xp("a:updated/text()")),
              ("x_arxiv_versao", "sufixo vN do id", xp("a:id/text()"))],
    "pubmed": [("x_pubmed_mesh_qualificadores", "MeshHeading/QualifierName (Descritor/Qualificador)", xp("MedlineCitation/MeshHeadingList/MeshHeading/QualifierName/text()")),
               ("x_pubmed_pais_periodico", "MedlineJournalInfo/Country", xp("MedlineCitation/MedlineJournalInfo/Country/text()")),
               ("x_pubmed_nlm_id", "MedlineJournalInfo/NlmUniqueID", xp("MedlineCitation/MedlineJournalInfo/NlmUniqueID/text()")),
               ("x_pubmed_status", "MedlineCitation/@Status", xp("MedlineCitation/@Status")),
               ("x_pubmed_conflito_interesses", "CoiStatement", xp("MedlineCitation/CoiStatement//text()"))],
    "europepmc": [("x_epmc_fonte", "source (MED, PMC, PPR, AGR…)", "source"),
                  ("x_epmc_grants", "grantsList.grant[] (agency: grantId)", "grantsList.grant.agency"),
                  ("x_epmc_substancias", "chemicalList.chemical[].name", "chemicalList.chemical.name"),
                  ("x_epmc_mesh_qualificadores", "meshHeadingList…meshQualifier[].qualifierName", "meshHeadingList.meshHeading.meshQualifierList.meshQualifier.qualifierName"),
                  ("x_epmc_versao_preprint", "versionNumber", "versionNumber"),
                  ("x_epmc_tem_dados", "hasData", "hasData")],
    "core": [("x_core_provedores", "dataProviders[].name", "dataProviders.name"),
             ("x_core_oai", "oaiIds[]", "oaiIds"),
             ("x_core_data_deposito", "depositedDate", "depositedDate")],
    "doaj": [("x_doaj_pais_periodico", "bibjson.journal.country", "bibjson.journal.country"),
             ("x_doaj_assunto_lcc", "bibjson.subject[].code (scheme LCC)", "bibjson.subject.code")],
}

# ---------------------------------------------------------------- carga das fixtures


def carregar_registros(fx: Path, base: str, arquivo: str) -> list:
    p = fx / base / arquivo
    if not p.exists():
        return []
    if base == "arxiv":
        return etree.parse(str(p)).getroot().xpath("//a:entry", namespaces=ATOM)
    if base == "pubmed":
        return etree.parse(str(p)).getroot().xpath("//PubmedArticle")
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return []
    if base == "openalex":
        return d.get("results", [])
    if base == "semantic_scholar":
        return d.get("data", []) if isinstance(d, dict) else []
    if base == "crossref":
        return d.get("message", {}).get("items", [])
    if base == "europepmc":
        return d.get("resultList", {}).get("result", [])
    if base in ("core", "doaj"):
        return d.get("results", [])
    return []


def total_api(fx: Path, base: str, arquivo: str):
    p = fx / base / arquivo
    if not p.exists():
        return None
    texto = p.read_text(encoding="utf-8")
    if base == "arxiv":
        m = re.search(r"<opensearch:totalResults>(\d+)<", texto)
        return int(m.group(1)) if m else None
    try:
        d = json.loads(texto)
    except ValueError:
        return None
    return {
        "openalex": lambda: d["meta"]["count"], "semantic_scholar": lambda: d["total"],
        "crossref": lambda: d["message"]["total-results"], "pubmed": lambda: int(d["esearchresult"]["count"]),
        "europepmc": lambda: d["hitCount"], "core": lambda: d["totalHits"], "doaj": lambda: d["total"],
    }[base]() if isinstance(d, dict) else None


def chave_registro(base: str, rec) -> str:
    if base == "arxiv":
        return rec.xpath("a:id/text()", namespaces=ATOM)[0]
    if base == "pubmed":
        return rec.xpath("MedlineCitation/PMID/text()")[0]
    for k in ("id", "paperId", "DOI"):
        if isinstance(rec, dict) and rec.get(k):
            return str(rec[k])
    return json.dumps(rec)[:200]


def todos_registros(fx: Path, base: str) -> list:
    vistos, regs = set(), []
    padrao = "*.xml" if base in ("arxiv", "pubmed") else "*.json"
    for p in sorted((fx / base).glob(padrao)):
        if p.name.startswith("_") or "enriq" in p.name:
            continue
        if base == "pubmed" and not p.name.startswith("efetch"):
            continue
        for r in carregar_registros(fx, base, p.name):
            k = chave_registro(base, r)
            if k not in vistos:
                vistos.add(k)
                regs.append(r)
    return regs


def aplicar(regra, rec) -> list:
    if regra is None:
        return []
    if regra is True:
        return [True]
    if callable(regra):
        return regra(rec)
    return pegar(rec, regra)


def indice(fx: Path, base: str) -> dict:
    p = fx / base / "_index.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"execucoes": [], "chamadas": []}


def chamada(fx: Path, base: str, nome: str) -> dict | None:
    return next((c for c in indice(fx, base)["chamadas"] if c["nome"] == nome), None)


# ---------------------------------------------------------------- verificação dos filtros

ANOS = (2021, 2022)


def _ano(base, rec):
    v = aplicar(MAPA[base]["ano"][1], rec)
    if not v:
        return None
    if base == "crossref":
        return v[0][0] if isinstance(v[0], list) and v[0] else None  # date-parts: [[a, m, d]]
    m = re.match(r"(\d{4})", str(v[0]))
    return int(m.group(1)) if m else None


def p_periodo(base, rec):
    a = _ano(base, rec)
    return None if a is None else ANOS[0] <= a <= ANOS[1]


def p_idioma_pt(base, rec):
    v = [str(x).lower() for x in aplicar(MAPA[base]["idioma"][1], rec)]
    return None if not v else any(x in ("pt", "por", "portuguese") for x in v)


def p_tipo(*aceitos):
    def f(base, rec):
        v = [str(x) for x in aplicar(MAPA[base]["tipo"][1], rec)]
        return None if not v else any(x in aceitos for x in v)
    return f


def p_oa(base, rec):
    if base == "semantic_scholar":
        return bool(pegar(rec, "openAccessPdf.url"))
    v = [str(x) for x in aplicar(MAPA[base]["acesso_aberto"][1], rec)]
    return None if not v else any(x in ("True", "Y", "true") for x in v)


def p_conferencia_openalex(base, rec):
    return "conference" in pegar(rec, "primary_location.source.type")


def _tem_ml(txt: str) -> bool:
    t = txt.lower()
    return "machine" in t and "learning" in t


def p_titulo(base, rec):
    return _tem_ml(" ".join(str(x) for x in aplicar(MAPA[base]["titulo"][1], rec)))


def p_titulo_resumo(base, rec):
    t = " ".join(str(x) for x in aplicar(MAPA[base]["titulo"][1], rec))
    r = aplicar(MAPA[base]["resumo"][1], rec)
    if base == "openalex" and r:
        r = list(r[0].keys())
    return _tem_ml(t + " " + " ".join(str(x) for x in r))


# (base, filtro canônico, fixture, parâmetro enviado, predicado | None, busca de referência)
FILTROS = [
    ("openalex", "período", "filtro_periodo", "filter=from_publication_date:2021-01-01,to_publication_date:2022-12-31", p_periodo),
    ("openalex", "idioma=pt", "filtro_idioma", "filter=language:pt", p_idioma_pt),
    ("openalex", "tipo=revisao", "filtro_tipo_revisao", "filter=type:review", p_tipo("review")),
    ("openalex", "tipo=preprint", "filtro_tipo_preprint", "filter=type:preprint", p_tipo("preprint")),
    ("openalex", "tipo=conferencia", "filtro_tipo_conferencia", "filter=primary_location.source.type:conference", p_conferencia_openalex),
    ("openalex", "tipo=livro_capitulo", "filtro_tipo_livro", "filter=type:book|book-chapter", p_tipo("book", "book-chapter")),
    ("openalex", "somente_oa", "filtro_oa", "filter=open_access.is_oa:true", p_oa),
    ("openalex", "campo=titulo", "campo_titulo", "filter=title.search:<q>", p_titulo),
    ("openalex", "campo=titulo_resumo", "campo_titulo_resumo", "filter=title_and_abstract.search:<q>", p_titulo_resumo),
    ("semantic_scholar", "período", "filtro_periodo", "year=2021-2022", p_periodo),
    ("semantic_scholar", "tipo=artigo", "filtro_tipo_artigo", "publicationTypes=JournalArticle", p_tipo("JournalArticle")),
    ("semantic_scholar", "tipo=revisao", "filtro_tipo_revisao", "publicationTypes=Review", p_tipo("Review")),
    ("semantic_scholar", "tipo=conferencia", "filtro_tipo_conferencia", "publicationTypes=Conference", p_tipo("Conference")),
    ("semantic_scholar", "tipo=livro_capitulo", "filtro_tipo_livro", "publicationTypes=Book,BookSection", p_tipo("Book", "BookSection")),
    ("semantic_scholar", "somente_oa", "filtro_oa", "openAccessPdf (sem valor)", p_oa),
    ("crossref", "período", "filtro_periodo", "filter=from-pub-date:2021-01-01,until-pub-date:2022-12-31", p_periodo),
    ("crossref", "tipo=artigo", "filtro_tipo_artigo", "filter=type:journal-article", p_tipo("journal-article")),
    ("crossref", "tipo=preprint", "filtro_tipo_preprint", "filter=type:posted-content", p_tipo("posted-content")),
    ("crossref", "tipo=conferencia", "filtro_tipo_conferencia", "filter=type:proceedings-article", p_tipo("proceedings-article")),
    ("crossref", "tipo=livro_capitulo", "filtro_tipo_livro", "filter=type:book,type:book-chapter", p_tipo("book", "book-chapter", "monograph")),
    ("arxiv", "período", "filtro_periodo", "AND submittedDate:[202101010000 TO 202212312359]", p_periodo),
    ("arxiv", "campo=titulo", "campo_titulo", "ti:machine AND ti:learning", p_titulo),
    ("arxiv", "campo=titulo_resumo", "campo_titulo_resumo", "(ti:machine OR abs:machine) AND (ti:learning OR abs:learning)", p_titulo_resumo),
    ("pubmed", "período", "esearch_filtro_periodo", "AND 2021:2022[dp]", None),
    ("pubmed", "idioma=pt", "esearch_filtro_idioma_por", "AND por[la]", None),
    ("pubmed", "idioma=pt", "esearch_filtro_idioma_portuguese", "AND portuguese[la]", None),
    ("pubmed", "tipo=artigo", "esearch_filtro_tipo_artigo", '"Journal Article"[pt]', None),
    ("pubmed", "tipo=revisao", "esearch_filtro_tipo_revisao", "Review[pt]", None),
    ("pubmed", "tipo=preprint", "esearch_filtro_tipo_preprint", "Preprint[pt]", None),
    ("pubmed", "tipo=conferencia", "esearch_filtro_tipo_conferencia", "Congress[pt]", None),
    ("pubmed", "tipo=conferencia", "esearch_filtro_tipo_conferencia_pt_aspas", '"Congress"[Publication Type]', None),
    ("pubmed", "tipo=livro_capitulo", "esearch_filtro_tipo_livro", '"Book Chapter"[pt]', None),
    ("pubmed", "tipo=livro_capitulo", "esearch_filtro_tipo_livro_booksdocs", "booksdocs[filter]", None),
    ("pubmed", "somente_oa", "esearch_filtro_oa", "free full text[sb]", None),
    ("pubmed", "campo=titulo", "esearch_campo_titulo", "<q>[ti]", None),
    ("pubmed", "campo=titulo_resumo", "esearch_campo_titulo_resumo", "<q>[tiab]", None),
    ("europepmc", "período", "filtro_periodo", "PUB_YEAR:[2021 TO 2022]", p_periodo),
    ("europepmc", "idioma=pt", "filtro_idioma_por", 'LANG:"por"', p_idioma_pt),
    ("europepmc", "idioma=pt", "filtro_idioma_pt", 'LANG:"pt"', p_idioma_pt),
    ("europepmc", "tipo=artigo", "filtro_tipo_artigo", 'PUB_TYPE:"journal article"', p_tipo("Journal Article", "journal article", "research-article")),
    ("europepmc", "tipo=revisao", "filtro_tipo_revisao", 'PUB_TYPE:"review"', p_tipo("Review", "review-article", "Systematic Review")),
    ("europepmc", "tipo=preprint", "filtro_tipo_preprint", "SRC:PPR", p_tipo("Preprint", "preprint")),
    ("europepmc", "somente_oa", "filtro_oa", "OPEN_ACCESS:y", p_oa),
    ("europepmc", "campo=titulo", "campo_titulo", 'TITLE:"<q>"', p_titulo),
    ("europepmc", "campo=titulo_resumo", "campo_titulo_resumo", '(TITLE:"<q>" OR ABSTRACT:"<q>")', p_titulo_resumo),
    ("core", "período", "filtro_periodo", "yearPublished>=2021 AND yearPublished<=2022", p_periodo),
    ("core", "idioma=pt", "filtro_idioma", "language.code:pt", p_idioma_pt),
    ("core", "campo=titulo", "campo_titulo", 'title:"<q>"', p_titulo),
    ("core", "campo=titulo_resumo", "campo_titulo_resumo", '(title:"<q>" OR abstract:"<q>")', p_titulo_resumo),
    ("doaj", "período", "filtro_periodo", "bibjson.year:[2021 TO 2022]", p_periodo),
    ("doaj", "campo=titulo", "campo_titulo", 'bibjson.title:"<q>"', p_titulo),
    ("doaj", "campo=titulo_resumo", "campo_titulo_resumo", 'bibjson.title:"<q>" OR bibjson.abstract:"<q>"', p_titulo_resumo),
]
REFERENCIA = {"pubmed": "esearch", "crossref": "busca_sem_cursor", "semantic_scholar": "busca_campos_completos"}


def verificar_filtros(fx: Path) -> list[dict]:
    linhas = []
    for base, filtro, nome, param, pred in FILTROS:
        ext = "json"
        meta = chamada(fx, base, nome)
        ref = REFERENCIA.get(base, "busca")
        tot_ref = total_api(fx, base, f"{ref}.{'xml' if base == 'arxiv' else 'json'}")
        if meta is None:
            linhas.append(dict(base=base, filtro=filtro, param=param, status="—", total=None, ref=tot_ref,
                               amostra="", veredito="não testado"))
            continue
        ext = meta["arquivo"].rsplit(".", 1)[-1] if meta.get("arquivo") else ext
        tot = total_api(fx, base, f"{nome}.{ext}") if meta["status"] == 200 else None
        amostra, veredito = "", ""
        if meta["status"] != 200:
            veredito = f"não verificado (HTTP {meta['status']})"
        elif base == "pubmed":
            d = json.loads((fx / base / f"{nome}.json").read_text())["esearchresult"]
            traducao = d.get("querytranslation", "")
            erros = {k: v for k, v in (d.get("errorlist") or {}).items() if v}
            amostra = f"tradução: `{traducao[-60:]}`" + (f"; erro: {erros}" if erros else "")
            veredito = "funciona" if tot and not erros and (tot_ref is None or tot < tot_ref) else "não funciona"
        else:
            regs = carregar_registros(fx, base, f"{nome}.{ext}")
            res = [pred(base, r) for r in regs]
            ok = sum(1 for x in res if x is True)
            sem = sum(1 for x in res if x is None)
            amostra = f"{ok}/{len(res)} registros atendem" + (f" ({sem} sem o dado)" if sem else "")
            reduziu = tot is not None and tot_ref is not None and tot < tot_ref
            if not regs:
                veredito = "não funciona (0 resultados)"
            elif ok + sem == len(res) and reduziu:
                veredito = "funciona"
            elif ok + sem == len(res):
                veredito = "funciona (total não diminuiu)"
            elif ok:
                veredito = "não funciona (mistura)"
            else:
                veredito = "não funciona"
        linhas.append(dict(base=base, filtro=filtro, param=param, status=meta["status"], total=tot, ref=tot_ref,
                           amostra=amostra, veredito=veredito))
    return linhas


# ---------------------------------------------------------------- relatório


def _fmt(n):
    return "—" if n is None else f"{n:,}".replace(",", ".")


def gerar(fx: Path, saida: Path) -> None:
    L: list[str] = []
    w = L.append
    w("# Relatório do teste prático das APIs")
    w("")
    w(f"Gerado em {date.today().isoformat()} por `scripts/teste_pratico.py relatorio` a partir de `tests/fixtures/`.")
    w("Consulta: `machine learning`, 5 resultados por chamada. Período testado: 2021–2022. Idioma testado: `pt`.")
    w("")
    w("Credenciais usadas na coleta: `OPENALEX_API_KEY` e `CONTACT_EMAIL`. "
      "`NCBI_API_KEY`, `S2_API_KEY`, `CORE_API_KEY` e `OPENCITATIONS_TOKEN` estavam vazias "
      "(todas as bases foram testadas no modo sem chave, exceto OpenAlex).")
    w("")

    # 1. resumo de chamadas
    w("## 1. Chamadas, erros e limites observados")
    w("")
    w("| Base | Chamadas HTTP | 429 | Taxa inicial → final (req/s) | Status das respostas gravadas | Headers de limite |")
    w("|---|---|---|---|---|---|")
    for base in BASES + ["opencitations"]:
        idx = indice(fx, base)
        if not idx["chamadas"]:
            continue
        ex = idx["execucoes"]
        n_http = sum(e["chamadas_http"] for e in ex)
        n429 = sum(e["n_429"] for e in ex)
        taxas = "; ".join(f"{e['taxa_inicial']:.2g} → {e['taxa_final']:.2g}" for e in ex)
        sts: dict = {}
        for c in idx["chamadas"]:
            sts[c["status"]] = sts.get(c["status"], 0) + 1
        hdr = {}
        for c in idx["chamadas"]:
            hdr.update(c.get("headers_limite") or {})
        hdr_txt = ", ".join(f"`{k}`" for k in sorted(hdr)) or "nenhum"
        w(f"| {base} | {n_http} | {n429} | {taxas} | {', '.join(f'{k}: {v}' for k, v in sorted(sts.items(), key=str))} | {hdr_txt} |")
    w("")
    oa = chamada(fx, "openalex", "busca")
    if oa:
        h = oa["headers_limite"]
        w(f"- **OpenAlex:** cada busca custou `x-ratelimit-cost-usd: {h.get('x-ratelimit-cost-usd')}`; "
          f"orçamento diário `x-ratelimit-limit-usd: {h.get('x-ratelimit-limit-usd')}`, restante em "
          f"`x-ratelimit-remaining-usd`; `x-ratelimit-reset` em segundos. O campo `meta.cost_usd` também vem no corpo. "
          "A lista por filtro (`filter=openalex_id:…`) também é cobrada.")
    cr = chamada(fx, "crossref", "busca")
    if cr:
        h = cr["headers_limite"]
        w(f"- **Crossref (com `mailto`):** `x-rate-limit-limit: {h.get('x-rate-limit-limit')}`, "
          f"`x-rate-limit-interval: {h.get('x-rate-limit-interval')}`, `x-concurrency-limit: {h.get('x-concurrency-limit')}` — confere com 3 req/s e 3 conexões.")
    pm = chamada(fx, "pubmed", "esearch")
    if pm:
        w(f"- **PubMed (sem chave):** `x-ratelimit-limit: {pm['headers_limite'].get('x-ratelimit-limit')}` — confere com 3 req/s.")
    co = chamada(fx, "core", "busca")
    if co:
        w(f"- **CORE (anônimo):** `x-ratelimit-limit: {co['headers_limite'].get('x-ratelimit-limit')}`, "
          "`x-ratelimit-remaining` e `x-ratelimit-retry-after` (data ISO, não segundos). Nenhum 429 em "
          f"{sum(e['chamadas_http'] for e in indice(fx, 'core')['execucoes'])} chamadas a 0,5 req/s.")
    ep = next((e.get("teste_rajada") for e in indice(fx, "europepmc")["execucoes"] if e.get("teste_rajada")), None)
    if ep:
        w(f"- **Europe PMC:** rajada sustentada de {ep['chamadas']} chamadas a 2 req/s em {ep['duracao_s']} s → "
          f"**{ep['n_429']} respostas 429**. Nenhum header de limite.")
    s2 = indice(fx, "semantic_scholar")
    if s2["chamadas"]:
        ex = s2["execucoes"]
        w(f"- **Semantic Scholar (sem chave):** {sum(e['n_429'] for e in ex)} respostas 429 em "
          f"{sum(e['chamadas_http'] for e in ex)} chamadas; a taxa adaptativa caiu até o piso (0,1 req/s). "
          "Sem headers de limite nem `Retry-After`.")
    dj = chamada(fx, "doaj", "limite_1000")
    if dj:
        w(f"- **DOAJ:** `page=201&pageSize=5` → HTTP {dj['status']} \"You cannot access results beyond 1000 records via this API\" "
          "(limite de 1.000 confirmado). Nenhum header de limite.")
    w("- **arXiv:** sem headers de limite; nenhum 429 a 1 req/3 s.")
    w("")

    # 2. matriz de colunas
    w("## 2. Colunas da seção 9.3 × campos realmente retornados")
    w("")
    w("Legenda: **n/N** = registros da amostra com o campo preenchido; **E** = preenchido no enriquecimento; "
      "**F** = valor fixo da base; **—** = a base não fornece; **G** = coluna gerada pelo coletor.")
    w("")
    bases_m = [b for b in BASES if b in MAPA]
    regs = {b: todos_registros(fx, b) for b in bases_m}
    w("| Coluna | " + " | ".join(bases_m) + " |")
    w("|---|" + "---|" * len(bases_m))
    for col in COLUNAS:
        if col in GERADAS:
            w(f"| `{col}` | " + " | ".join("G" for _ in bases_m) + " |")
            continue
        cel = []
        for b in bases_m:
            desc, regra = MAPA[b].get(col, ("—", None))
            if regra is None:
                cel.append("E" if desc.startswith("E:") else "—")
            elif regra is True:
                cel.append("F")
            else:
                n = sum(1 for r in regs[b] if aplicar(regra, r))
                cel.append(f"{n}/{len(regs[b])}" + ("+E" if "E:" in desc else ""))
        w(f"| `{col}` | " + " | ".join(cel) + " |")
    w("")
    w("Amostra por base (registros únicos de todas as fixtures de busca): " +
      ", ".join(f"{b} = {len(regs[b])}" for b in bases_m) + ". "
      "PubMed: `PubmedArticle` de `efetch.xml` (5 mais recentes), `efetch_indexados.xml` (2021–2022) e "
      "`efetch_relevancia.xml` (`sort=relevance`); os livros de `efetch_livro.xml` (`PubmedBookArticle`) ficam fora da matriz.")
    w("")
    for b in bases_m:
        w(f"<details><summary><b>{b}</b> — campo de origem de cada coluna</summary>")
        w("")
        w("| Coluna | Campo na resposta |")
        w("|---|---|")
        for col in COLUNAS:
            if col in GERADAS:
                continue
            desc = MAPA[b].get(col, ("—", None))[0]
            w(f"| `{col}` | {desc} |")
        w("")
        w("</details>")
        w("")

    # 3. filtros
    w("## 3. Parâmetros de filtro (seção 6)")
    w("")
    w("Verificação: total informado pela API com o filtro × total sem filtro, e conferência do valor "
      "nos registros devolvidos. PubMed: conferência pela tradução do `esearch` (`querytranslation`).")
    w("")
    w("| Base | Filtro | Parâmetro enviado | HTTP | Total com filtro | Total sem filtro | Amostra | Veredito |")
    w("|---|---|---|---|---|---|---|---|")
    for l in verificar_filtros(fx):
        w(f"| {l['base']} | {l['filtro']} | `{l['param']}` | {l['status']} | {_fmt(l['total'])} | {_fmt(l['ref'])} | {l['amostra']} | **{l['veredito']}** |")
    w("")

    # 4. tipos observados
    w("### Valores de tipo observados nas respostas")
    w("")
    for b in bases_m:
        regra = MAPA[b]["tipo"][1]
        if regra is True:
            continue
        vals: dict = {}
        for r in regs[b]:
            for v in aplicar(regra, r):
                vals[str(v)] = vals.get(str(v), 0) + 1
        w(f"- **{b}:** " + ", ".join(f"`{k}` ({v})" for k, v in sorted(vals.items(), key=lambda x: -x[1])))
    w("")
    w("### Valores de idioma observados")
    w("")
    for b in bases_m:
        regra = MAPA[b]["idioma"][1]
        if regra is None:
            continue
        vals = {}
        for r in regs[b]:
            for v in aplicar(regra, r):
                vals[str(v)] = vals.get(str(v), 0) + 1
        sem = sum(1 for r in regs[b] if not aplicar(regra, r))
        w(f"- **{b}:** " + ", ".join(f"`{k}` ({v})" for k, v in sorted(vals.items(), key=lambda x: -x[1])) + f"; sem idioma: {sem}")
    w("")

    # 5. enriquecimento
    w("## 4. Endpoints de enriquecimento")
    w("")
    w("| Serviço | Chamada | HTTP | Observação |")
    w("|---|---|---|---|")
    for base, nome, obs in OBS_ENRIQ:
        c = chamada(fx, base, nome)
        if c:
            w(f"| {base} | `{c['metodo']} {c['url'][:90]}` | {c['status']} | {obs(fx) if callable(obs) else obs} |")
    w("")

    # 6. SciELO
    w("## 5. SciELO")
    w("")
    for nome, obs in [("search_robots", "`robots.txt` do search.scielo.org: `User-agent: *` → `Disallow: /` (só buscadores nomeados são liberados)"),
                      ("articlemeta_identificadores", "ArticleMeta lista identificadores por coleção e data de processamento — não há busca por palavra-chave"),
                      ("articlemeta_busca_q", "ArticleMeta com `q=` → 404"),
                      ("search_output_json", "search.scielo.org `output=json` → 403 (desafio anti-robô “Establishing a secure connection”)"),
                      ("search_output_xml", "`output=xml` → 403 (mesmo desafio)"),
                      ("search_output_rss", "`output=rss` → 403 (mesmo desafio)")]:
        c = chamada(fx, "scielo", nome)
        if c:
            w(f"- HTTP {c['status']} — {obs}.")
    w("")

    # 7. colunas extras
    w("## 6. Colunas `x_<base>_*` propostas")
    w("")
    w("| Base | Coluna | Campo de origem | Preenchido na amostra |")
    w("|---|---|---|---|")
    for b, cols in EXTRAS.items():
        for col, desc, regra in cols:
            n = sum(1 for r in regs[b] if aplicar(regra, r))
            w(f"| {b} | `{col}` | {desc} | {n}/{len(regs[b])} |")
    w("")
    w("Posição no CSV: após `avisos` e antes de `raw_json`, na ordem desta tabela.")
    w("")

    # 8. observações e decisões — texto de análise
    w((Path(__file__).parent / "relatorio_teste_pratico_analise.md").read_text(encoding="utf-8"))

    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text("\n".join(L), encoding="utf-8")
    print(f"relatório gravado em {saida}")


def _obs_oa_ids(fx):
    d = json.loads((fx / "openalex" / "enriq_ids_para_doi.json").read_text())
    com = sum(1 for r in d["results"] if r.get("doi"))
    return f"{d['meta']['count']} IDs W resolvidos numa chamada; {com} com DOI (`select=id,doi`)"


def _obs_s2_batch(fx):
    d = json.loads((fx / "semantic_scholar" / "enriq_batch_referencias.json").read_text())
    refs = [x for p in d if p for x in (p.get("references") or [])]
    com_doi = sum(1 for x in refs if (x.get("externalIds") or {}).get("DOI"))
    return (f"{len(d)} artigos; {len(refs)} referências, {com_doi} com DOI (demais: `s2:paperId`). "
            "Aceita `tldr`, `citationCount`, `influentialCitationCount` no mesmo lote")


def _obs_epmc_refs(fx):
    d = json.loads((fx / "europepmc" / "enriq_referencias.json").read_text())
    r = d["referenceList"]["reference"]
    return (f"hitCount={d['hitCount']}; cada referência traz `source`/`id` (MED → PMID) e às vezes `doi`; "
            f"{sum(1 for x in r if x.get('doi'))}/{len(r)} com DOI")


def _obs_epmc_ft(fx):
    t = (fx / "europepmc" / "enriq_texto_completo.xml").read_text()
    return (f"JATS XML ({len(t) // 1024} KiB) com `<body>`/`<sec>`/`<p>`, MathML e `<ref-list>`; "
            "converter `<p>` de `<body>` em parágrafos de texto")


def _obs_oc(nome):
    def f(fx):
        d = json.loads((fx / "opencitations" / f"{nome}.json").read_text())
        if isinstance(d, list) and d and "count" in d[0]:
            return f"`count` = {d[0]['count']} (string)"
        return f"{len(d)} referências (`cited` = lista de IDs `omid:… doi:… pmid:… openalex:…` separados por espaço)" if d else "lista vazia (sem referências no índice)"
    return f


OBS_ENRIQ = [
    ("openalex", "enriq_ids_para_doi", _obs_oa_ids),
    ("semantic_scholar", "enriq_batch_referencias", _obs_s2_batch),
    ("europepmc", "enriq_referencias", _obs_epmc_refs),
    ("europepmc", "enriq_texto_completo", _obs_epmc_ft),
    ("core", "enriq_work", "`/v3/works/{id}` traz os mesmos campos da busca + `arxivId`, `pubmedId`, `magId`, `acceptedDate`; "
                           "`fullText` = \"Not available for public API users.\" (sem chave)"),
    ("opencitations", "referencias_doi", _obs_oc("referencias_doi")),
    ("opencitations", "citation_count_doi", _obs_oc("citation_count_doi")),
    ("opencitations", "reference_count_doi", _obs_oc("reference_count_doi")),
    ("opencitations", "referencias_doi_conhecido", _obs_oc("referencias_doi_conhecido")),
    ("opencitations", "citation_count_doi_conhecido", _obs_oc("citation_count_doi_conhecido")),
    ("opencitations", "referencias_pmid", _obs_oc("referencias_pmid")),
    ("opencitations", "referencias_pmid_conhecido", _obs_oc("referencias_pmid_conhecido")),
    ("opencitations", "citation_count_pmid", _obs_oc("citation_count_pmid")),
]
