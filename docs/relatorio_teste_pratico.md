# Relatório do teste prático das APIs

Gerado em 2026-10-31 por `scripts/teste_pratico.py relatorio` a partir de `tests/fixtures/`.
Consulta: `machine learning`, 5 resultados por chamada. Período testado: 2021–2022. Idioma testado: `pt`.

Credenciais usadas na coleta: `OPENALEX_API_KEY` e `CONTACT_EMAIL`. `NCBI_API_KEY`, `S2_API_KEY`, `CORE_API_KEY` e `OPENCITATIONS_TOKEN` estavam vazias (todas as bases foram testadas no modo sem chave, exceto OpenAlex).

## 1. Chamadas, erros e limites observados

| Base | Chamadas HTTP | 429 | Taxa inicial → final (req/s) | Status das respostas gravadas | Headers de limite |
|---|---|---|---|---|---|
| openalex | 12 | 0 | 10 → 10 | 200: 12 | `x-ratelimit-cost-usd`, `x-ratelimit-credits-used`, `x-ratelimit-limit`, `x-ratelimit-limit-usd`, `x-ratelimit-onetime-remaining`, `x-ratelimit-prepaid-remaining-usd`, `x-ratelimit-remaining`, `x-ratelimit-remaining-usd`, `x-ratelimit-reset` |
| semantic_scholar | 63 | 57 | 1 → 0.1; 0.2 → 0.1 | 200: 6, 429: 3 | nenhum |
| crossref | 10 | 0 | 3 → 3; 3 → 3 | 200: 10 | `x-concurrency-limit`, `x-rate-limit-interval`, `x-rate-limit-limit` |
| arxiv | 6 | 0 | 0.33 → 0.33 | 200: 6 | nenhum |
| pubmed | 27 | 0 | 3 → 3; 3 → 3; 3 → 3; 3 → 3 | 200: 20 | `x-ratelimit-limit`, `x-ratelimit-remaining` |
| europepmc | 34 | 0 | 2 → 2 | 200: 14 | nenhum |
| core | 7 | 0 | 0.5 → 0.5 | 200: 7 | `x-ratelimit-limit`, `x-ratelimit-remaining`, `x-ratelimit-retry-after` |
| doaj | 6 | 0 | 2 → 2 | 200: 5, 400: 1 | nenhum |
| scielo | 7 | 0 | 1 → 1 | 200: 3, 403: 3, 404: 1 | nenhum |
| opencitations | 8 | 0 | 3 → 3; 3 → 3 | 200: 8 | nenhum |

- **OpenAlex:** cada busca custou `x-ratelimit-cost-usd: 0.001`; orçamento diário `x-ratelimit-limit-usd: 1`, restante em `x-ratelimit-remaining-usd`; `x-ratelimit-reset` em segundos. O campo `meta.cost_usd` também vem no corpo. A lista por filtro (`filter=openalex_id:…`) também é cobrada.
- **Crossref (com `mailto`):** `x-rate-limit-limit: 3`, `x-rate-limit-interval: 1s`, `x-concurrency-limit: 3` — confere com 3 req/s e 3 conexões.
- **PubMed (sem chave):** `x-ratelimit-limit: 3` — confere com 3 req/s.
- **CORE (anônimo):** `x-ratelimit-limit: 10`, `x-ratelimit-remaining` e `x-ratelimit-retry-after` (data ISO, não segundos). Nenhum 429 em 7 chamadas a 0,5 req/s.
- **Europe PMC:** rajada sustentada de 20 chamadas a 2 req/s em 11.1 s → **0 respostas 429**. Nenhum header de limite.
- **Semantic Scholar (sem chave):** 57 respostas 429 em 63 chamadas; a taxa adaptativa caiu até o piso (0,1 req/s). Sem headers de limite nem `Retry-After`.
- **DOAJ:** `page=201&pageSize=5` → HTTP 400 "You cannot access results beyond 1000 records via this API" (limite de 1.000 confirmado). Nenhum header de limite.
- **arXiv:** sem headers de limite; nenhum 429 a 1 req/3 s.

## 2. Colunas da seção 9.3 × campos realmente retornados

Legenda: **n/N** = registros da amostra com o campo preenchido; **E** = preenchido no enriquecimento; **F** = valor fixo da base; **—** = a base não fornece; **G** = coluna gerada pelo coletor.

| Coluna | openalex | semantic_scholar | crossref | arxiv | pubmed | europepmc | core | doaj |
|---|---|---|---|---|---|---|---|---|
| `base` | G | G | G | G | G | G | G | G |
| `id_na_base` | 37/37 | 17/17 | 35/35 | 22/22 | 16/16 | 33/33 | 30/30 | 17/17 |
| `doi` | 35/37 | 11/17 | 35/35 | 8/22 | 16/16 | 31/33 | 14/30 | 17/17 |
| `pmid` | 9/37 | 5/17 | — | — | 16/16 | 24/33 | 0/30 | — |
| `pmcid` | 5/37 | 3/17 | — | — | 9/16 | 17/33 | — | — |
| `arxiv_id` | 6/37 | 9/17 | — | 22/22 | — | — | 0/30 | — |
| `url_pagina` | 37/37 | 17/17 | 35/35 | 22/22 | 16/16 | 33/33 | 30/30 | 17/17 |
| `consulta` | G | G | G | G | G | G | G | G |
| `coletado_em` | G | G | G | G | G | G | G | G |
| `titulo` | 37/37 | 17/17 | 35/35 | 22/22 | 16/16 | 33/33 | 30/30 | 17/17 |
| `autores` | 35/37 | 17/17 | 28/35 | 22/22 | 16/16 | 33/33 | 28/30 | 17/17 |
| `autores_orcid` | 32/37 | 1/17 | 3/35 | — | 6/16 | 24/33 | — | 4/17 |
| `afiliacoes` | 32/37 | 3/17 | 5/35 | 0/22 | 16/16 | 26/33 | — | 17/17 |
| `ano` | 37/37 | 17/17 | 35/35 | 22/22 | 16/16 | 33/33 | 30/30 | 17/17 |
| `data_publicacao` | 37/37 | 16/17 | 35/35 | 22/22 | 14/16 | 33/33 | 20/30 | 12/17 |
| `tipo` | 37/37 | 14/17 | 35/35 | F | 16/16 | 33/33 | 13/30 | F |
| `idioma` | 37/37 | — | 18/35 | — | 16/16 | 26/33 | 9/30 | 17/17 |
| `veiculo` | 36/37 | 15/17 | 28/35 | F | 16/16 | 26/33 | 0/30 | 17/17 |
| `issn` | 21/37 | 9/17 | 16/35 | — | 16/16 | 26/33 | 0/30 | 17/17 |
| `editora` | 31/37 | — | 35/35 | — | — | — | 23/30 | 17/17 |
| `volume` | 13/37 | 11/17 | 16/35 | — | 16/16 | 25/33 | — | 17/17 |
| `numero` | 11/37 | — | 16/35 | — | 9/16 | 17/33 | — | 12/17 |
| `paginas` | 23/37 | 9/17 | 25/35 | — | 14/16 | 24/33 | — | 15/17 |
| `resumo` | 27/37 | 13/17 | 8/35 | 22/22 | 15/16 | 29/33 | 25/30 | 17/17 |
| `tldr` | — | 17/17 | — | — | — | — | — | — |
| `palavras_chave` | 37/37 | — | — | — | 13/16 | 16/33 | — | 16/17 |
| `assuntos` | 37/37 | 17/17 | 0/35 | 22/22 | 7/16 | 14/33 | 10/30 | 17/17 |
| `texto_completo` | — | — | — | — | — | E | 0/30 | — |
| `acesso_aberto` | 37/37 | 17/17 | 2/35 | F | — | 33/33 | F | F |
| `status_oa` | 37/37 | 11/17 | — | — | — | — | — | — |
| `licenca` | 9/37 | 3/17 | 23/35 | — | — | 22/33 | — | — |
| `url_pdf` | 16/37 | 8/17 | 11/35 | 22/22 | — | 16/33 | 9/30 | 2/17 |
| `n_citacoes` | 37/37 | 17/17 | 35/35 | E | E | 33/33 | 0/30+E | E |
| `n_citacoes_influentes` | — | 17/17 | — | — | — | — | — | — |
| `citacoes_por_ano` | 35/37 | — | — | — | — | — | — | — |
| `percentil_citacoes` | 30/37 | — | — | — | — | — | — | — |
| `fwci` | 30/37 | — | — | — | — | — | — | — |
| `n_referencias` | 37/37 | 17/17 | 35/35 | E | 4/16 | E | 3/30 | E |
| `referencias` | 27/37+E | E | 10/35+E | E | 4/16+E | E | 3/30+E | E |
| `relacionados` | 37/37+E | — | — | — | — | — | — | — |
| `fonte_referencias` | G | G | G | G | G | G | G | G |
| `fonte_citacoes` | G | G | G | G | G | G | G | G |
| `financiadores` | 7/37 | — | 2/35 | — | 2/16 | 5/33 | — | — |
| `retratado` | 37/37 | — | 0/35 | — | — | — | — | — |
| `avisos` | G | G | G | G | G | G | G | G |

Amostra por base (registros únicos de todas as fixtures de busca): openalex = 37, semantic_scholar = 17, crossref = 35, arxiv = 22, pubmed = 16, europepmc = 33, core = 30, doaj = 17. PubMed: `PubmedArticle` de `efetch.xml` (5 mais recentes), `efetch_indexados.xml` (2021–2022) e `efetch_relevancia.xml` (`sort=relevance`); os livros de `efetch_livro.xml` (`PubmedBookArticle`) ficam fora da matriz.

<details><summary><b>openalex</b> — campo de origem de cada coluna</summary>

| Coluna | Campo na resposta |
|---|---|
| `id_na_base` | id |
| `doi` | doi |
| `pmid` | ids.pmid |
| `pmcid` | ids.pmcid |
| `arxiv_id` | derivado de locations[].landing_page_url (arxiv.org/abs/…) |
| `url_pagina` | primary_location.landing_page_url |
| `titulo` | title |
| `autores` | authorships[].author.display_name |
| `autores_orcid` | authorships[].author.orcid |
| `afiliacoes` | authorships[].institutions[].display_name (alt.: raw_affiliation_strings) |
| `ano` | publication_year |
| `data_publicacao` | publication_date |
| `tipo` | type |
| `idioma` | language |
| `veiculo` | primary_location.source.display_name |
| `issn` | primary_location.source.issn[] |
| `editora` | primary_location.source.host_organization_name |
| `volume` | biblio.volume |
| `numero` | biblio.issue |
| `paginas` | biblio.first_page–last_page |
| `resumo` | abstract_inverted_index (reconstruído) |
| `tldr` | — |
| `palavras_chave` | keywords[].display_name |
| `assuntos` | topics[].display_name (+ concepts[].display_name) |
| `texto_completo` | — (endpoint de conteúdo é pago) |
| `acesso_aberto` | open_access.is_oa |
| `status_oa` | open_access.oa_status |
| `licenca` | best_oa_location.license (alt.: primary_location.license) |
| `url_pdf` | best_oa_location.pdf_url (alt.: open_access.oa_url) |
| `n_citacoes` | cited_by_count |
| `n_citacoes_influentes` | — |
| `citacoes_por_ano` | counts_by_year[] (year:cited_by_count) |
| `percentil_citacoes` | citation_normalized_percentile.value |
| `fwci` | fwci |
| `n_referencias` | referenced_works_count |
| `referencias` | referenced_works[] (IDs W; E: convertidos em DOI por lote) |
| `relacionados` | related_works[] (IDs W; E: convertidos em DOI por lote) |
| `financiadores` | funders[].display_name (alt.: awards[].funder_display_name) |
| `retratado` | is_retracted |

</details>

<details><summary><b>semantic_scholar</b> — campo de origem de cada coluna</summary>

| Coluna | Campo na resposta |
|---|---|
| `id_na_base` | paperId |
| `doi` | externalIds.DOI |
| `pmid` | externalIds.PubMed |
| `pmcid` | externalIds.PubMedCentral |
| `arxiv_id` | externalIds.ArXiv |
| `url_pagina` | url |
| `titulo` | title |
| `autores` | authors[].name |
| `autores_orcid` | authors[].externalIds.ORCID |
| `afiliacoes` | authors[].affiliations[] |
| `ano` | year |
| `data_publicacao` | publicationDate |
| `tipo` | publicationTypes[] |
| `idioma` | — |
| `veiculo` | publicationVenue.name (alt.: venue, journal.name) |
| `issn` | publicationVenue.issn |
| `editora` | — |
| `volume` | journal.volume |
| `numero` | — |
| `paginas` | journal.pages |
| `resumo` | abstract |
| `tldr` | tldr.text |
| `palavras_chave` | — |
| `assuntos` | s2FieldsOfStudy[].category (+ fieldsOfStudy[]) |
| `texto_completo` | — |
| `acesso_aberto` | isOpenAccess |
| `status_oa` | openAccessPdf.status |
| `licenca` | openAccessPdf.license |
| `url_pdf` | openAccessPdf.url |
| `n_citacoes` | citationCount |
| `n_citacoes_influentes` | influentialCitationCount |
| `citacoes_por_ano` | — |
| `percentil_citacoes` | — |
| `fwci` | — |
| `n_referencias` | referenceCount |
| `referencias` | E: POST /paper/batch → references[].externalIds.DOI | s2:paperId |
| `relacionados` | — |
| `financiadores` | — |
| `retratado` | — |

</details>

<details><summary><b>crossref</b> — campo de origem de cada coluna</summary>

| Coluna | Campo na resposta |
|---|---|
| `id_na_base` | DOI |
| `doi` | DOI |
| `pmid` | — |
| `pmcid` | — |
| `arxiv_id` | — |
| `url_pagina` | URL (doi.org) / resource.primary.URL |
| `titulo` | title[] (+ subtitle[]) |
| `autores` | author[].given + family (ou name) |
| `autores_orcid` | author[].ORCID |
| `afiliacoes` | author[].affiliation[].name |
| `ano` | published.date-parts[0][0] (alt.: issued) |
| `data_publicacao` | published.date-parts (precisão variável: ano, ano-mês ou data) |
| `tipo` | type |
| `idioma` | language |
| `veiculo` | container-title[] |
| `issn` | ISSN[] |
| `editora` | publisher |
| `volume` | volume |
| `numero` | issue |
| `paginas` | page |
| `resumo` | abstract (JATS → texto) |
| `tldr` | — |
| `palavras_chave` | — |
| `assuntos` | subject[] (ausente nas respostas) |
| `texto_completo` | — |
| `acesso_aberto` | derivado: license[].URL creativecommons (filtro local) |
| `status_oa` | — |
| `licenca` | license[].URL |
| `url_pdf` | link[] com content-type application/pdf |
| `n_citacoes` | is-referenced-by-count |
| `n_citacoes_influentes` | — |
| `citacoes_por_ano` | — |
| `percentil_citacoes` | — |
| `fwci` | — |
| `n_referencias` | references-count |
| `referencias` | reference[].DOI (quando depositado; senão E: OpenCitations) |
| `relacionados` | — |
| `financiadores` | funder[].name |
| `retratado` | updated-by[] tipo retraction (ausente nas respostas) |

</details>

<details><summary><b>arxiv</b> — campo de origem de cada coluna</summary>

| Coluna | Campo na resposta |
|---|---|
| `id_na_base` | id (http://arxiv.org/abs/<id>v<n>) |
| `doi` | arxiv:doi |
| `pmid` | — |
| `pmcid` | — |
| `arxiv_id` | id sem versão |
| `url_pagina` | link[@rel=alternate]/@href |
| `titulo` | title |
| `autores` | author/name |
| `autores_orcid` | — |
| `afiliacoes` | author/arxiv:affiliation |
| `ano` | published (ano) |
| `data_publicacao` | published (data da v1) |
| `tipo` | fixo: preprint |
| `idioma` | — |
| `veiculo` | fixo: arXiv |
| `issn` | — |
| `editora` | — |
| `volume` | — |
| `numero` | — |
| `paginas` | — |
| `resumo` | summary |
| `tldr` | — |
| `palavras_chave` | — |
| `assuntos` | category/@term |
| `texto_completo` | — |
| `acesso_aberto` | fixo: true |
| `status_oa` | — |
| `licenca` | — (não vem na API Atom) |
| `url_pdf` | link[@title=pdf]/@href |
| `n_citacoes` | E: OpenCitations /citation-count (pelo DOI) |
| `n_citacoes_influentes` | — |
| `citacoes_por_ano` | — |
| `percentil_citacoes` | — |
| `fwci` | — |
| `n_referencias` | E: OpenCitations |
| `referencias` | E: OpenCitations (pelo DOI) |
| `relacionados` | — |
| `financiadores` | — |
| `retratado` | — |

</details>

<details><summary><b>pubmed</b> — campo de origem de cada coluna</summary>

| Coluna | Campo na resposta |
|---|---|
| `id_na_base` | MedlineCitation/PMID |
| `doi` | ArticleIdList/ArticleId[@IdType=doi] |
| `pmid` | MedlineCitation/PMID |
| `pmcid` | ArticleIdList/ArticleId[@IdType=pmc] |
| `arxiv_id` | — |
| `url_pagina` | derivado: https://pubmed.ncbi.nlm.nih.gov/<PMID>/ |
| `titulo` | Article/ArticleTitle |
| `autores` | Author/LastName + ForeName (ou CollectiveName) |
| `autores_orcid` | Author/Identifier[@Source=ORCID] |
| `afiliacoes` | Author/AffiliationInfo/Affiliation |
| `ano` | JournalIssue/PubDate/Year (alt.: MedlineDate) |
| `data_publicacao` | Article/ArticleDate (alt.: PubDate) |
| `tipo` | PublicationTypeList/PublicationType |
| `idioma` | Article/Language (3 letras → ISO 639-1) |
| `veiculo` | Journal/Title |
| `issn` | Journal/ISSN |
| `editora` | — |
| `volume` | JournalIssue/Volume |
| `numero` | JournalIssue/Issue |
| `paginas` | Pagination/MedlinePgn |
| `resumo` | Abstract/AbstractText (com @Label) |
| `tldr` | — |
| `palavras_chave` | KeywordList/Keyword |
| `assuntos` | MeshHeadingList/MeshHeading/DescriptorName |
| `texto_completo` | — |
| `acesso_aberto` | — (filtro nativo apenas) |
| `status_oa` | — |
| `licenca` | — |
| `url_pdf` | — |
| `n_citacoes` | E: OpenCitations /citation-count |
| `n_citacoes_influentes` | — |
| `citacoes_por_ano` | — |
| `percentil_citacoes` | — |
| `fwci` | — |
| `n_referencias` | contagem de PubmedData/ReferenceList/Reference |
| `referencias` | PubmedData/ReferenceList/Reference/ArticleIdList (nativo, quando houver; senão E: OpenCitations) |
| `relacionados` | — |
| `financiadores` | GrantList/Grant/Agency |
| `retratado` | derivado: PublicationType 'Retracted Publication' |

</details>

<details><summary><b>europepmc</b> — campo de origem de cada coluna</summary>

| Coluna | Campo na resposta |
|---|---|
| `id_na_base` | id (com source em x_epmc_fonte) |
| `doi` | doi |
| `pmid` | pmid |
| `pmcid` | pmcid |
| `arxiv_id` | — |
| `url_pagina` | derivado: https://europepmc.org/article/<source>/<id> |
| `titulo` | title |
| `autores` | authorList.author[].fullName |
| `autores_orcid` | authorList.author[].authorId (type=ORCID) |
| `afiliacoes` | authorList.author[].authorAffiliationDetailsList…affiliation (alt.: affiliation) |
| `ano` | pubYear |
| `data_publicacao` | firstPublicationDate |
| `tipo` | pubTypeList.pubType[] |
| `idioma` | language (3 letras → ISO 639-1) |
| `veiculo` | journalInfo.journal.title (preprint: bookOrReportDetails.publisher) |
| `issn` | journalInfo.journal.issn / essn |
| `editora` | — |
| `volume` | journalInfo.volume |
| `numero` | journalInfo.issue |
| `paginas` | pageInfo |
| `resumo` | abstractText (HTML → texto) |
| `tldr` | — |
| `palavras_chave` | keywordList.keyword[] |
| `assuntos` | meshHeadingList.meshHeading[].descriptorName |
| `texto_completo` | E: /{PMCID}/fullTextXML (OA com PMCID) → texto |
| `acesso_aberto` | isOpenAccess (Y/N) |
| `status_oa` | — |
| `licenca` | license |
| `url_pdf` | fullTextUrlList.fullTextUrl[] documentStyle=pdf, availability=Open access |
| `n_citacoes` | citedByCount |
| `n_citacoes_influentes` | — |
| `citacoes_por_ano` | — |
| `percentil_citacoes` | — |
| `fwci` | — |
| `n_referencias` | E: /{source}/{id}/references (hitCount) |
| `referencias` | E: /{source}/{id}/references quando hasReferences=Y |
| `relacionados` | — |
| `financiadores` | grantsList.grant[].agency |
| `retratado` | derivado: pubType 'Retracted Publication' |

</details>

<details><summary><b>core</b> — campo de origem de cada coluna</summary>

| Coluna | Campo na resposta |
|---|---|
| `id_na_base` | id |
| `doi` | doi |
| `pmid` | pubmedId |
| `pmcid` | — |
| `arxiv_id` | arxivId |
| `url_pagina` | links[] type=display |
| `titulo` | title |
| `autores` | authors[].name |
| `autores_orcid` | — |
| `afiliacoes` | — |
| `ano` | yearPublished |
| `data_publicacao` | publishedDate |
| `tipo` | documentType |
| `idioma` | language.code |
| `veiculo` | journals[].title |
| `issn` | journals[].identifiers[] (issn:…) |
| `editora` | publisher |
| `volume` | — |
| `numero` | — |
| `paginas` | — |
| `resumo` | abstract |
| `tldr` | — |
| `palavras_chave` | — |
| `assuntos` | fieldOfStudy |
| `texto_completo` | fullText — sem chave vem 'Not available for public API users.' |
| `acesso_aberto` | fixo: true |
| `status_oa` | — |
| `licenca` | — |
| `url_pdf` | downloadUrl |
| `n_citacoes` | citationCount vem sempre 0 → E: OpenCitations |
| `n_citacoes_influentes` | — |
| `citacoes_por_ano` | — |
| `percentil_citacoes` | — |
| `fwci` | — |
| `n_referencias` | contagem de references[] |
| `referencias` | references[].doi (parcial; E: OpenCitations) |
| `relacionados` | — |
| `financiadores` | — |
| `retratado` | — |

</details>

<details><summary><b>doaj</b> — campo de origem de cada coluna</summary>

| Coluna | Campo na resposta |
|---|---|
| `id_na_base` | id |
| `doi` | bibjson.identifier[type=doi].id |
| `pmid` | — |
| `pmcid` | — |
| `arxiv_id` | — |
| `url_pagina` | bibjson.link[type=fulltext].url |
| `titulo` | bibjson.title |
| `autores` | bibjson.author[].name |
| `autores_orcid` | bibjson.author[].orcid_id |
| `afiliacoes` | bibjson.author[].affiliation |
| `ano` | bibjson.year |
| `data_publicacao` | bibjson.year + month (só ano-mês) |
| `tipo` | fixo: artigo |
| `idioma` | bibjson.journal.language[] (idioma do periódico, maiúsculas) |
| `veiculo` | bibjson.journal.title |
| `issn` | bibjson.journal.issns[] |
| `editora` | bibjson.journal.publisher |
| `volume` | bibjson.journal.volume |
| `numero` | bibjson.journal.number |
| `paginas` | bibjson.start_page–end_page |
| `resumo` | bibjson.abstract |
| `tldr` | — |
| `palavras_chave` | bibjson.keywords[] |
| `assuntos` | bibjson.subject[].term |
| `texto_completo` | — |
| `acesso_aberto` | fixo: true |
| `status_oa` | — |
| `licenca` | — (licença é do periódico) |
| `url_pdf` | bibjson.link[content_type=PDF].url |
| `n_citacoes` | E: OpenCitations |
| `n_citacoes_influentes` | — |
| `citacoes_por_ano` | — |
| `percentil_citacoes` | — |
| `fwci` | — |
| `n_referencias` | E: OpenCitations |
| `referencias` | E: OpenCitations (pelo DOI) |
| `relacionados` | — |
| `financiadores` | — |
| `retratado` | — |

</details>

## 3. Parâmetros de filtro (seção 6)

Verificação: total informado pela API com o filtro × total sem filtro, e conferência do valor nos registros devolvidos. PubMed: conferência pela tradução do `esearch` (`querytranslation`).

| Base | Filtro | Parâmetro enviado | HTTP | Total com filtro | Total sem filtro | Amostra | Veredito |
|---|---|---|---|---|---|---|---|
| openalex | período | `filter=from_publication_date:2021-01-01,to_publication_date:2022-12-31` | 200 | 730.943 | 6.214.372 | 5/5 registros atendem | **funciona** |
| openalex | idioma=pt | `filter=language:pt` | 200 | 48.518 | 6.214.372 | 5/5 registros atendem | **funciona** |
| openalex | tipo=revisao | `filter=type:review` | 200 | 135.571 | 6.214.372 | 5/5 registros atendem | **funciona** |
| openalex | tipo=preprint | `filter=type:preprint` | 200 | 481.493 | 6.214.372 | 5/5 registros atendem | **funciona** |
| openalex | tipo=conferencia | `filter=primary_location.source.type:conference` | 200 | 533.013 | 6.214.372 | 5/5 registros atendem | **funciona** |
| openalex | tipo=livro_capitulo | `filter=type:book|book-chapter` | 200 | 1.376.191 | 6.214.372 | 5/5 registros atendem | **funciona** |
| openalex | somente_oa | `filter=open_access.is_oa:true` | 200 | 4.200.969 | 6.214.372 | 5/5 registros atendem | **funciona** |
| openalex | campo=titulo | `filter=title.search:<q>` | 200 | 541.045 | 6.214.372 | 5/5 registros atendem | **funciona** |
| openalex | campo=titulo_resumo | `filter=title_and_abstract.search:<q>` | 200 | 2.919.860 | 6.214.372 | 5/5 registros atendem | **funciona** |
| semantic_scholar | período | `year=2021-2022` | 429 | — | 7.918.459 |  | **não verificado (HTTP 429)** |
| semantic_scholar | tipo=artigo | `publicationTypes=JournalArticle` | 200 | 3.424.025 | 7.918.459 | 5/5 registros atendem | **funciona** |
| semantic_scholar | tipo=revisao | `publicationTypes=Review` | 200 | 974.687 | 7.918.459 | 5/5 registros atendem | **funciona** |
| semantic_scholar | tipo=conferencia | `publicationTypes=Conference` | 200 | 849.542 | 7.918.459 | 5/5 registros atendem | **funciona** |
| semantic_scholar | tipo=livro_capitulo | `publicationTypes=Book,BookSection` | 429 | — | 7.918.459 |  | **não verificado (HTTP 429)** |
| semantic_scholar | somente_oa | `openAccessPdf (sem valor)` | 429 | — | 7.918.459 |  | **não verificado (HTTP 429)** |
| crossref | período | `filter=from-pub-date:2021-01-01,until-pub-date:2022-12-31` | 200 | 425.105 | 3.054.951 | 5/5 registros atendem | **funciona** |
| crossref | tipo=artigo | `filter=type:journal-article` | 200 | 1.772.770 | 3.054.951 | 5/5 registros atendem | **funciona** |
| crossref | tipo=preprint | `filter=type:posted-content` | 200 | 112.857 | 3.054.951 | 5/5 registros atendem | **funciona** |
| crossref | tipo=conferencia | `filter=type:proceedings-article` | 200 | 550.483 | 3.054.951 | 5/5 registros atendem | **funciona** |
| crossref | tipo=livro_capitulo | `filter=type:book,type:book-chapter` | 200 | 493.645 | 3.054.951 | 5/5 registros atendem | **funciona** |
| arxiv | período | `AND submittedDate:[202101010000 TO 202212312359]` | 200 | 65.761 | 358.373 | 5/5 registros atendem | **funciona** |
| arxiv | campo=titulo | `ti:machine AND ti:learning` | 200 | 21.205 | 358.373 | 5/5 registros atendem | **funciona** |
| arxiv | campo=titulo_resumo | `(ti:machine OR abs:machine) AND (ti:learning OR abs:learning)` | 200 | 100.840 | 358.373 | 5/5 registros atendem | **funciona** |
| pubmed | período | `AND 2021:2022[dp]` | 200 | 54.553 | 288.778 | tradução: `"[All Fields]) AND 2021/01/01:2022/12/31[Date - Publication]` | **funciona** |
| pubmed | idioma=pt | `AND por[la]` | 200 | 41 | 288.778 | tradução: `R "machine learning"[All Fields]) AND "portuguese"[Language]` | **funciona** |
| pubmed | idioma=pt | `AND portuguese[la]` | 200 | 41 | 288.778 | tradução: `R "machine learning"[All Fields]) AND "portuguese"[Language]` | **funciona** |
| pubmed | tipo=artigo | `"Journal Article"[pt]` | 200 | 282.038 | 288.778 | tradução: `arning"[All Fields]) AND "Journal Article"[Publication Type]` | **funciona** |
| pubmed | tipo=revisao | `Review[pt]` | 200 | 31.406 | 288.778 | tradução: `achine learning"[All Fields]) AND "Review"[Publication Type]` | **funciona** |
| pubmed | tipo=preprint | `Preprint[pt]` | 200 | 2.783 | 288.778 | tradução: `hine learning"[All Fields]) AND "Preprint"[Publication Type]` | **funciona** |
| pubmed | tipo=conferencia | `Congress[pt]` | 200 | 0 | 288.778 | tradução: `(machine learning) AND Congress[pt]`; erro: {'phrasesnotfound': ['Congress']} | **não funciona** |
| pubmed | tipo=conferencia | `"Congress"[Publication Type]` | 200 | 0 | 288.778 | tradução: `(machine learning) AND "Congress"[Publication Type]` | **não funciona** |
| pubmed | tipo=livro_capitulo | `"Book Chapter"[pt]` | 200 | 0 | 288.778 | tradução: `(machine learning) AND "Book Chapter"[pt]` | **não funciona** |
| pubmed | tipo=livro_capitulo | `booksdocs[filter]` | 200 | 152 | 288.778 | tradução: `R "machine learning"[All Fields]) AND "pubmed books"[Filter]` | **funciona** |
| pubmed | somente_oa | `free full text[sb]` | 200 | 195.399 | 288.778 | tradução: `ne learning"[All Fields]) AND "loattrfree full text"[Filter]` | **funciona** |
| pubmed | campo=titulo | `<q>[ti]` | 200 | 77.795 | 288.778 | tradução: `"machine learning"[Title]` | **funciona** |
| pubmed | campo=titulo_resumo | `<q>[tiab]` | 200 | 217.295 | 288.778 | tradução: `"machine learning"[Title/Abstract]` | **funciona** |
| europepmc | período | `PUB_YEAR:[2021 TO 2022]` | 200 | 125.176 | 657.876 | 5/5 registros atendem | **funciona** |
| europepmc | idioma=pt | `LANG:"por"` | 200 | 35 | 657.876 | 5/5 registros atendem | **funciona** |
| europepmc | idioma=pt | `LANG:"pt"` | 200 | 60 | 657.876 | 2/5 registros atendem | **não funciona (mistura)** |
| europepmc | tipo=artigo | `PUB_TYPE:"journal article"` | 200 | 582.153 | 657.876 | 5/5 registros atendem | **funciona** |
| europepmc | tipo=revisao | `PUB_TYPE:"review"` | 200 | 99.480 | 657.876 | 5/5 registros atendem | **funciona** |
| europepmc | tipo=preprint | `SRC:PPR` | 200 | 48.747 | 657.876 | 5/5 registros atendem | **funciona** |
| europepmc | somente_oa | `OPEN_ACCESS:y` | 200 | 446.833 | 657.876 | 5/5 registros atendem | **funciona** |
| europepmc | campo=titulo | `TITLE:"<q>"` | 200 | 95.927 | 657.876 | 5/5 registros atendem | **funciona** |
| europepmc | campo=titulo_resumo | `(TITLE:"<q>" OR ABSTRACT:"<q>")` | 200 | 235.489 | 657.876 | 5/5 registros atendem | **funciona** |
| core | período | `yearPublished>=2021 AND yearPublished<=2022` | 200 | 175.690 | 7.331.145 | 5/5 registros atendem | **funciona** |
| core | idioma=pt | `language.code:pt` | 200 | 3.447 | 7.331.145 | 5/5 registros atendem | **funciona** |
| core | campo=titulo | `title:"<q>"` | 200 | 2.652.720 | 7.331.145 | 5/5 registros atendem | **funciona** |
| core | campo=titulo_resumo | `(title:"<q>" OR abstract:"<q>")` | 200 | 858.398 | 7.331.145 | 5/5 registros atendem | **funciona** |
| doaj | período | `bibjson.year:[2021 TO 2022]` | 200 | 37.605 | 208.931 | 5/5 registros atendem | **funciona** |
| doaj | campo=titulo | `bibjson.title:"<q>"` | 200 | 69.729 | 208.931 | 5/5 registros atendem | **funciona** |
| doaj | campo=titulo_resumo | `bibjson.title:"<q>" OR bibjson.abstract:"<q>"` | 200 | 172.409 | 208.931 | 5/5 registros atendem | **funciona** |

### Valores de tipo observados nas respostas

- **openalex:** `book` (8), `book-chapter` (6), `review` (6), `article` (5), `preprint` (5), `conference-paper` (5), `reference-entry` (1), `editorial` (1)
- **semantic_scholar:** `JournalArticle` (13), `Review` (5), `Conference` (5), `Book` (2)
- **crossref:** `journal-article` (16), `proceedings-article` (5), `posted-content` (5), `book-chapter` (4), `other` (3), `monograph` (1), `book` (1)
- **pubmed:** `Journal Article` (16), `Review` (6), `Research Support, Non-U.S. Gov't` (2), `Evaluation Study` (1), `Research Support, N.I.H., Extramural` (1)
- **europepmc:** `Journal Article` (25), `research-article` (9), `Review` (8), `Preprint` (7), `review-article` (6), `Systematic Review` (2), `Comparative Study` (1), `English Abstract` (1), `Editorial` (1), `Validation Study` (1), `methods-article` (1), `Research Support, Non-U.S. Gov't` (1)
- **core:** `research article` (4), `conference paper` (3), `text` (3), `project` (1), `thesis` (1), `journal article` (1)

### Valores de idioma observados

- **openalex:** `en` (32), `pt` (5); sem idioma: 0
- **crossref:** `en` (18); sem idioma: 17
- **pubmed:** `eng` (16); sem idioma: 0
- **europepmc:** `eng` (21), `por` (5); sem idioma: 7
- **core:** `pt` (5), `en` (4); sem idioma: 21
- **doaj:** `EN` (17), `AR` (1), `FR` (1); sem idioma: 0

## 4. Endpoints de enriquecimento

| Serviço | Chamada | HTTP | Observação |
|---|---|---|---|
| openalex | `GET https://api.openalex.org/works?filter=openalex_id%3AW822801274%7CW1506806321%7CW1565746575` | 200 | 45 IDs W resolvidos numa chamada; 36 com DOI (`select=id,doi`) |
| semantic_scholar | `POST https://api.semanticscholar.org/graph/v1/paper/batch?fields=paperId%2CexternalIds%2Ccitati` | 200 | 5 artigos; 364 referências, 272 com DOI (demais: `s2:paperId`). Aceita `tldr`, `citationCount`, `influentialCitationCount` no mesmo lote |
| europepmc | `GET https://www.ebi.ac.uk/europepmc/webservices/rest/MED/42955678/references?format=json&pageS` | 200 | hitCount=10; cada referência traz `source`/`id` (MED → PMID) e às vezes `doi`; 0/10 com DOI |
| europepmc | `GET https://www.ebi.ac.uk/europepmc/webservices/rest/PMC13686947/fullTextXML` | 200 | JATS XML (197 KiB) com `<body>`/`<sec>`/`<p>`, MathML e `<ref-list>`; converter `<p>` de `<body>` em parágrafos de texto |
| core | `GET https://api.core.ac.uk/v3/works/171513974` | 200 | `/v3/works/{id}` traz os mesmos campos da busca + `arxivId`, `pubmedId`, `magId`, `acceptedDate`; `fullText` = "Not available for public API users." (sem chave) |
| opencitations | `GET https://api.opencitations.net/index/v2/references/doi:10.1067/msy.2099.99951b` | 200 | lista vazia (sem referências no índice) |
| opencitations | `GET https://api.opencitations.net/index/v2/citation-count/doi:10.1067/msy.2099.99951b` | 200 | `count` = 8 (string) |
| opencitations | `GET https://api.opencitations.net/index/v2/reference-count/doi:10.1067/msy.2099.99951b` | 200 | `count` = 0 (string) |
| opencitations | `GET https://api.opencitations.net/index/v2/references/doi:10.1038/nature14539` | 200 | 40 referências (`cited` = lista de IDs `omid:… doi:… pmid:… openalex:…` separados por espaço) |
| opencitations | `GET https://api.opencitations.net/index/v2/citation-count/doi:10.1038/nature14539` | 200 | `count` = 73495 (string) |
| opencitations | `GET https://api.opencitations.net/index/v2/references/pmid:42964336` | 200 | lista vazia (sem referências no índice) |
| opencitations | `GET https://api.opencitations.net/index/v2/references/pmid:26017442` | 200 | 40 referências (`cited` = lista de IDs `omid:… doi:… pmid:… openalex:…` separados por espaço) |
| opencitations | `GET https://api.opencitations.net/index/v2/citation-count/pmid:42964336` | 200 | `count` = 0 (string) |

## 5. SciELO

- HTTP 200 — `robots.txt` do search.scielo.org: `User-agent: *` → `Disallow: /` (só buscadores nomeados são liberados).
- HTTP 200 — ArticleMeta lista identificadores por coleção e data de processamento — não há busca por palavra-chave.
- HTTP 404 — ArticleMeta com `q=` → 404.
- HTTP 403 — search.scielo.org `output=json` → 403 (desafio anti-robô “Establishing a secure connection”).
- HTTP 403 — `output=xml` → 403 (mesmo desafio).
- HTTP 403 — `output=rss` → 403 (mesmo desafio).

## 6. Colunas `x_<base>_*` propostas

| Base | Coluna | Campo de origem | Preenchido na amostra |
|---|---|---|---|
| openalex | `x_openalex_topico_principal` | primary_topic.display_name | 37/37 |
| openalex | `x_openalex_area` | primary_topic.field.display_name | 37/37 |
| openalex | `x_openalex_tipo_fonte` | primary_location.source.type | 36/37 |
| openalex | `x_openalex_paises` | authorships[].countries[] (únicos) | 32/37 |
| openalex | `x_openalex_indexado_em` | indexed_in[] | 35/37 |
| openalex | `x_openalex_apc_usd` | apc_paid.value_usd | 2/37 |
| openalex | `x_openalex_ods` | sustainable_development_goals[].display_name | 5/37 |
| openalex | `x_openalex_mesh` | mesh[].descriptor_name | 8/37 |
| semantic_scholar | `x_s2_corpus_id` | corpusId | 17/17 |
| semantic_scholar | `x_s2_dblp` | externalIds.DBLP | 12/17 |
| semantic_scholar | `x_s2_mag` | externalIds.MAG | 14/17 |
| semantic_scholar | `x_s2_tipo_veiculo` | publicationVenue.type | 13/17 |
| crossref | `x_crossref_isbn` | ISBN[] | 7/35 |
| crossref | `x_crossref_evento` | event.name | 5/35 |
| crossref | `x_crossref_numero_artigo` | article-number | 3/35 |
| crossref | `x_crossref_subtitulo` | subtitle[] | 2/35 |
| crossref | `x_crossref_subtipo` | subtype | 5/35 |
| crossref | `x_crossref_membro` | member | 35/35 |
| arxiv | `x_arxiv_comentario` | arxiv:comment | 18/22 |
| arxiv | `x_arxiv_journal_ref` | arxiv:journal_ref | 11/22 |
| arxiv | `x_arxiv_categoria_primaria` | arxiv:primary_category/@term | 22/22 |
| arxiv | `x_arxiv_atualizado_em` | updated | 22/22 |
| arxiv | `x_arxiv_versao` | sufixo vN do id | 22/22 |
| pubmed | `x_pubmed_mesh_qualificadores` | MeshHeading/QualifierName (Descritor/Qualificador) | 5/16 |
| pubmed | `x_pubmed_pais_periodico` | MedlineJournalInfo/Country | 16/16 |
| pubmed | `x_pubmed_nlm_id` | MedlineJournalInfo/NlmUniqueID | 16/16 |
| pubmed | `x_pubmed_status` | MedlineCitation/@Status | 16/16 |
| pubmed | `x_pubmed_conflito_interesses` | CoiStatement | 11/16 |
| europepmc | `x_epmc_fonte` | source (MED, PMC, PPR, AGR…) | 33/33 |
| europepmc | `x_epmc_grants` | grantsList.grant[] (agency: grantId) | 5/33 |
| europepmc | `x_epmc_substancias` | chemicalList.chemical[].name | 4/33 |
| europepmc | `x_epmc_mesh_qualificadores` | meshHeadingList…meshQualifier[].qualifierName | 13/33 |
| europepmc | `x_epmc_versao_preprint` | versionNumber | 7/33 |
| europepmc | `x_epmc_tem_dados` | hasData | 33/33 |
| core | `x_core_provedores` | dataProviders[].name | 30/30 |
| core | `x_core_oai` | oaiIds[] | 30/30 |
| core | `x_core_data_deposito` | depositedDate | 30/30 |
| doaj | `x_doaj_pais_periodico` | bibjson.journal.country | 17/17 |
| doaj | `x_doaj_assunto_lcc` | bibjson.subject[].code (scheme LCC) | 17/17 |

Posição no CSV: após `avisos` e antes de `raw_json`, na ordem desta tabela.

## 7. Decisões automáticas (regras da seção 11)

| Regra | Resultado do teste | Decisão |
|---|---|---|
| **SciELO** sem busca por palavra-chave estruturada | ArticleMeta só lista identificadores por coleção/data (`q=` → 404). search.scielo.org: `robots.txt` com `User-agent: *` / `Disallow: /`, e `output=json\|xml\|rss` → 403 com desafio anti-robô. | **Desabilitada.** Sai de `bases_ativas` no `config.yaml` de exemplo; adaptador marcado `desabilitado` com o motivo; documentar no README. |
| **CORE** anônimo recebe sempre 429? | 7 chamadas anônimas a 0,5 req/s, **0 respostas 429** (`x-ratelimit-limit: 10`). | `CORE_API_KEY` **continua opcional** para a busca. (O texto completo é outra questão: ver 8.1.) |
| **Europe PMC** com 429 a 2 req/s? | Rajada de 20 chamadas a 2 req/s + 14 chamadas do teste: **0 respostas 429**. | **Mantém 2 req/s**, concorrência 2. |
| Parâmetro de filtro que não funciona como descrito → local | PubMed `Congress[pt]`: termo não reconhecido (`phrasesnotfound`); `"Congress"[Publication Type]` é aceito mas devolve 0. | PubMed **tipo=conferencia → L** (local, por `PublicationType`). |
| Sintaxe correta (continua nativo) | PubMed `"Book Chapter"[pt]` → 0, termo inexistente; `booksdocs[filter]` → 152 (`"pubmed books"[Filter]`). | PubMed **tipo=livro_capitulo → N `booksdocs[filter]`**. Os registros vêm como `PubmedBookArticle/BookDocument`, com estrutura diferente de `PubmedArticle`. |
| Sintaxe correta (continua nativo) | Europe PMC `LANG:"pt"` mistura idiomas (2/5 em português); `LANG:"por"` → 5/5. | Europe PMC **idioma → N `LANG:"<ISO 639-2>"`** (converter `pt` → `por`, `en` → `eng`, `es` → `spa` …). |
| Não verificado | Semantic Scholar sem chave: `year=`, `publicationTypes=Book,BookSection` e `openAccessPdf` só receberam 429 em duas rodadas (a segunda a 0,2 req/s). | Mantidos como **N** com a sintaxe documentada; validar quando houver `S2_API_KEY`. Os demais parâmetros de tipo do S2 funcionaram. |

Todos os outros parâmetros da seção 6 funcionaram como descritos: total menor que o da busca sem filtro e 5/5 registros conferidos.

## 8. Constatações que afetam a implementação

### 8.1 Casos fora das regras da seção 11 — decididos pelo usuário em 31/10/2026

| Achado | Decisão |
|---|---|
| **CORE — texto completo exige chave.** Sem `CORE_API_KEY`, `fullText` vem como `"Not available for public API users."` em todos os registros, na busca e em `/v3/works/{id}`. A busca funciona sem chave. | `CORE_API_KEY` **continua opcional**. Sem chave, `texto_completo` fica vazio e o registro recebe o aviso `texto_completo_requer_chave`; o relatório e o README informam. A frase fixa da API nunca é gravada como texto. |
| **Semantic Scholar sem chave.** 57 de 63 chamadas receberam 429; cada página bem-sucedida levou de 20 a 100 s; 3 de 6 testes de filtro não passaram. Busca e `/paper/batch` responderam. | `S2_API_KEY` **continua opcional**; a base pode terminar `parcial`. Os 3 filtros não verificados ficam nativos com a sintaxe documentada. O README recomenda pedir a chave. |
| **PubMed — ordem padrão.** O `esearch` sem `sort` devolve os registros **mais recentes** (incluídos hoje, sem MeSH nem referências). Com `sort=relevance` (fixture `esearch_sort_relevance.json`), vêm artigos de 2018–2022 sobre o tema, com MeSH e, num caso, 74 referências nativas. | Enviar **`sort=relevance`** no `esearch`, para ficar coerente com as outras bases (relevância). Não é ordenação feita pelo coletor. |
| **Colunas `x_<base>_*`.** O escopo diz "colunas exclusivas da base", mas a seção 9.3 também diz "todas presentes em todos os CSVs". | Cada CSV tem as colunas 1–45, depois **só as `x_` da sua base** (seção 6 deste relatório) e depois `raw_json`. |

### 8.2 Ajustes técnicos (não mudam colunas, filtros nem bases)

1. **Crossref — paginação por `offset`, não `cursor`.** Com `cursor=*` a ordem por relevância se perde (scores 3,8–5,8, títulos sem "machine learning"); sem cursor e com `offset` os scores ficam em 16,0–16,6. Como `max_artigos_por_base` + páginas extras ficam muito abaixo do teto de `offset` (10.000), usar `rows` + `offset`.
2. **OpenAlex — `search=` é busca em texto completo.** A API traduz `search` para `fulltext.search` ("in the full text"). Mantido para `campo_busca: tudo`. Custos medidos: US$ 0,001 por busca (inclusive `title.search`), US$ 0,0001 pela listagem com `filter=openalex_id:` (conversão de IDs). Ler `x-ratelimit-remaining-usd` para o orçamento.
3. **OpenAlex — tipo `conference-paper`.** Existe como valor de `type`; mapear para o canônico `conferencia`. O filtro `primary_location.source.type:conference` funciona e continua sendo o filtro nativo.
4. **PubMed — referências nativas.** Registros depositados no PMC trazem `PubmedData/ReferenceList` (34, 50 e 76 referências em 3 de 6 registros indexados, a maioria com DOI/PMID). Usar a lista nativa quando existir (`fonte_referencias = nativa`) e o OpenCitations quando não existir, conforme a seção 8.1.
5. **PubMed e Europe PMC — idioma em 3 letras** (`eng`, `por`): converter para ISO 639-1 na coluna `idioma`.
6. **CORE:** `citationCount` vem sempre 0 (31/31): `n_citacoes` sai do OpenCitations, como a seção 8.1 já prevê. `documentType` é texto livre (`research article`, `conference paper`, `thesis`, `text`, `project`), então o filtro local de tipo precisa de mapeamento próprio (abaixo). Há duplicatas com IDs diferentes e mesmo título; a deduplicação do escopo (por `id_na_base` e `doi`) não as remove, e assim fica. `pubmedId` e `arxivId` só aparecem em `/v3/works/{id}`, não na busca. `journals[]` vem com `title: null`. `x-ratelimit-retry-after` vem como data ISO, não em segundos.
7. **DOAJ:** idioma é o do periódico (`bibjson.journal.language`, em maiúsculas, pode ter vários); filtro local por interseção. Limite de 1.000 resultados confirmado (HTTP 400).
8. **Europe PMC:** `abstractText` vem com HTML (`<h4>`, `<b>`); referências trazem `source`/`id` e raramente DOI (0/10 na amostra) → gravar como `pmid:<id>` quando `source = MED`. `fullTextXML` é JATS com MathML (197 KiB na amostra): extrair só os `<p>` de `<body>`.
9. **Semantic Scholar:** a busca aceita `tldr` e `authors.affiliations`; `/paper/batch` aceita `references.paperId,references.externalIds` e devolve tudo numa chamada (364 referências de 5 artigos, 272 com DOI). `openAccessPdf.disclaimer` vem sempre preenchido e não é dado do artigo; ignorar.
10. **Crossref:** idioma presente em 18/35 → filtro local por idioma gera muitos `idioma_nao_verificado`. `abstract` (8/35) em JATS. Sem `subject`. Datas com precisão variável (`date-parts` só com ano, ou ano e mês).
11. **OpenCitations:** `count` vem como string; em `references`, o campo `cited` é uma lista de IDs separados por espaço (`omid:… doi:… pmid:… openalex:…`): extrair o `doi:`, senão o `pmid:`.

### 8.3 Mapeamento de tipos confirmado

| Canônico | OpenAlex `type` | S2 `publicationTypes` | Crossref `type` | PubMed | Europe PMC | CORE `documentType` (L) |
|---|---|---|---|---|---|---|
| artigo | `article` | `JournalArticle` | `journal-article` | N `"Journal Article"[pt]` | N `PUB_TYPE:"journal article"` | `research article`, `journal article`, `article` |
| revisao | `review` | `Review` | L | N `Review[pt]` | N `PUB_TYPE:"review"` | `review` |
| preprint | `preprint` | L | `posted-content` | N `Preprint[pt]` | N `SRC:PPR` | `preprint` |
| conferencia | filtro `primary_location.source.type:conference` (tipo: `conference-paper`) | `Conference` | `proceedings-article` | **L** `PublicationType = Congress` | L | `conference paper` |
| livro_capitulo | `book`, `book-chapter` | `Book`, `BookSection` | `book`, `book-chapter`, `monograph` | **N `booksdocs[filter]`** | L | `book`, `book chapter` |
