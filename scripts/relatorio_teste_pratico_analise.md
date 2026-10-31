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
