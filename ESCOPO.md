# Escopo fechado — Coletor multibase de artigos científicos

Versão 1.3 · 31/10/2026 · Status: **fechado para implementação** (ajustado pelo teste prático, CSV consolidado e decisão do usuário sobre triagem LLM/interface local — ver seções 15 e 16)

Este documento é a especificação completa do projeto. Tudo o que não está aqui está fora do escopo. Orientações de execução para o Claude Code estão em `CLAUDE.md`.

---

## 1. Objetivo

Ferramenta para Linux com CLI e interface HTTP restrita a localhost. Recebe uma consulta em texto livre (palavras-chave, nome de um tema ou título de um artigo), consulta **em paralelo** várias bases acadêmicas por APIs gratuitas e grava **um CSV por base** e um consolidado. Opcionalmente, valida cada registro consolidado por critérios configuráveis usando Ollama local e grava `ranking.csv`.

Uso: **acadêmico**, execução **pontual sob demanda**.

---

## 2. Decisões fechadas

| # | Tema | Decisão |
|---|---|---|
| 1 | Stack | Python 3.11+, `asyncio` + `httpx`. CLI + `config.yaml` + `.env`. Só Linux; sem Docker. |
| 2 | Bases | Todas as 9 implementadas. Lista `bases_ativas` no `config.yaml` permite desativar qualquer uma sem mexer no código. **SciELO desabilitada** (o teste prático não encontrou busca por palavra-chave estruturada — seção 15). |
| 3 | Credenciais | Só a do OpenAlex é obrigatória. As demais ficam como variáveis opcionais e vazias no `.env`. |
| 4 | Conteúdo | Apenas texto completo entregue pronto pela API (CORE; Europe PMC para artigos OA), **numa coluna do próprio CSV**. Sem arquivos separados, sem download/extração de PDF. |
| 5 | Referências e relações | Lista de DOIs/IDs das referências de cada artigo; contagem de citações; indicadores macro (citações por ano, citações influentes, percentil, FWCI); lista de trabalhos relacionados quando a base fornecer. Lista de artigos que **citam**: só a contagem. |
| 6 | Volume | `max_artigos_por_base`, padrão **100**, configurável. Vale para cada base, não para o total. |
| 7 | Consulta | Uma consulta única para todas as bases. Sem sobrescrita por base nesta versão. |
| 8 | Consolidação | **`consolidado.csv`** gerado em toda execução, além dos CSVs por base: uma linha por artigo, duplicatas entre bases fundidas (seção 9.5). Incluído nesta versão por decisão do usuário (seção 15.4). |
| 9 | Formato | CSV RFC 4180, vírgula, todos os campos entre aspas, UTF-8 com BOM. Coluna `raw_json` incluída, com opção para desligar. |
| 10 | Filtros | Período, tipo de documento, idioma, só acesso aberto, campo de busca. Filtro sem suporte nativo é aplicado localmente, com teto de páginas. |
| 11 | Execução | Pontual, sob demanda. Sem agendamento nem coleta incremental. |
| 12 | Ordenação da coleta | Nenhuma; os CSVs por base e o consolidado usam a ordem padrão de cada API (em geral, relevância). O arquivo separado `ranking.csv` é ordenado pelo score LLM (seção 16). |
| 13 | Limites de taxa | Taxa inicial por base + retentativa com espera + redução automática da taxa ao receber 429 (seção 7). |
| 14 | Triagem LLM | Depois da busca, o Ollama local avalia título, resumo e palavras-chave do consolidado contra critérios digitados na interface. A justificativa inclui trecho literal do resumo, validado pelo programa. |
| 15 | `ranking.csv` | Cópia das colunas do consolidado, mais colunas LLM; ordenado pelo score descendente. Fórmula: aderência 70%, recência 15%, citações 15%; citações usam `log(1+n)` e metadados ausentes recebem 0,5. |
| 16 | Interface HTTP | Formulário para consulta, parâmetros equivalentes ao YAML, critérios e modelo local. O bind padrão é `0.0.0.0`; clientes remotos entram por página de login com token e sessão segura; recomenda-se proxy reverso HTTPS. Credenciais continuam no `.env`. |

---

## 3. Fora do escopo

- Exposição sem autenticação ou sem HTTPS/TLS à Internet; Docker; suporte a Windows/macOS; provedores LLM hospedados.
- Bases pagas ou com assinatura institucional (Scopus, Web of Science, ScienceDirect); Google Scholar; raspagem de HTML.
- Download de PDFs e extração de texto de PDFs; arquivos de texto separados do CSV.
- Lista dos artigos que citam cada artigo (só a contagem).
- Ordenação dos resultados de busca por base; sobrescrita da consulta por base.
- Agendamento, coleta incremental, retomada de execução interrompida.
- Banco de dados.

---

## 4. Bases

| Chave no config | Base | Endpoint principal | Autenticação | Observações |
|---|---|---|---|---|
| `openalex` | OpenAlex | `GET https://api.openalex.org/works` | `OPENALEX_API_KEY` **obrigatória** (parâmetro `api_key` ou header `Authorization: Bearer`) | Orçamento diário gratuito de US$ 1 (busca ≈ US$ 0,001/chamada; listagem por filtro ≈ US$ 0,0001). Headers `X-RateLimit-*`. Máx. 100 req/s, `per_page` ≤ 100, paginação por `cursor`. |
| `semantic_scholar` | Semantic Scholar | `GET https://api.semanticscholar.org/graph/v1/paper/search` + `POST /graph/v1/paper/batch` | `S2_API_KEY` opcional (header `x-api-key`) | Sem chave: pool compartilhado, 429 frequentes. Com chave: 1 req/s. `limit` ≤ 100, paginação por `offset`. |
| `crossref` | Crossref | `GET https://api.crossref.org/works` | Nenhuma; `mailto=CONTACT_EMAIL` ativa o pool "polite" | Listas: 3 req/s e 3 conexões com e-mail (1 e 1 sem) — confirmado nos headers `x-rate-limit-*`. `rows` ≤ 1000, paginação por **`offset`** (≤ 10.000): com `cursor=*` a ordem por relevância se perde. |
| `arxiv` | arXiv | `GET https://export.arxiv.org/api/query` (Atom XML) | Nenhuma | 1 requisição a cada 3 s, uma conexão. Pode devolver 429 quando sobrecarregado. Metadados CC0. |
| `pubmed` | PubMed (NCBI E-utilities) | `esearch.fcgi` + `efetch.fcgi` em `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/` | `NCBI_API_KEY` opcional; enviar `tool` e `email` | 3 req/s sem chave, 10 com chave. `esearch` com `retmax` e **`sort=relevance`** (sem `sort` a API devolve os mais recentes); `efetch` em lote (XML; livros vêm como `PubmedBookArticle`). |
| `europepmc` | Europe PMC | `GET https://www.ebi.ac.uk/europepmc/webservices/rest/search` | Nenhuma | Limite não publicado: 2 req/s confirmado sem 429. `format=json`, `resultType=core`, paginação por `cursorMark`. Endpoints extras: `/{source}/{id}/references` e `/{PMCID}/fullTextXML`. |
| `core` | CORE | `GET https://api.core.ac.uk/v3/search/works/` (barra final obrigatória) | `CORE_API_KEY` opcional (header `Authorization: Bearer`) | Sem chave: ~1 lote ou 5 req a cada 10 s; o acesso anônimo funcionou sem 429. **Sem chave o `fullText` não é entregue** (texto fixo "Not available for public API users."). `limit` ≤ 100, paginação por `offset`. Consulta com sintaxe de campos no `q`. |
| `doaj` | DOAJ | `GET https://doaj.org/api/search/articles/{consulta}` | Nenhuma | 2 req/s (rajadas de até 5). `pageSize` ≤ 100. **Máximo de 1.000 resultados por busca** (confirmado: HTTP 400 além disso). Consulta em sintaxe Elasticsearch/Lucene. |
| `scielo` | SciELO | ArticleMeta `https://articlemeta.scielo.org/api/v1/article/` ou busca pública `https://search.scielo.org/` | Nenhuma | **Desabilitada.** ArticleMeta não tem busca por palavra-chave; search.scielo.org proíbe robôs (`robots.txt`: `Disallow: /`) e devolve 403 com desafio anti-robô para `output=json/xml/rss`. Adaptador mantido e marcado `desabilitado`, fora de `bases_ativas`. |

Enriquecedor (não é base de busca):

| Chave | Serviço | Endpoints | Autenticação | Limite |
|---|---|---|---|---|
| `opencitations` | OpenCitations Index v2 | `https://api.opencitations.net/index/v2/references/{id}`, `/citation-count/{id}`, `/reference-count/{id}` com `{id}` = `doi:...` ou `pmid:...` | `OPENCITATIONS_TOKEN` opcional (header `authorization`) | ~180 req/min por IP. |

---

## 5. Entrada

### 5.1 `config.yaml`

```yaml
query: '"machine learning" AND agriculture'   # texto livre: palavras-chave, tema ou título

bases_ativas:            # remova uma linha para desativar a base
  - openalex
  - semantic_scholar
  - crossref
  - arxiv
  - pubmed
  - europepmc
  - core
  - doaj
  # - scielo             # desabilitada: sem busca por palavra-chave via API (seção 15)

max_artigos_por_base: 100

filtros:
  ano_de: null           # ex.: 2020
  ano_ate: null          # ex.: 2026
  tipos: []              # subconjunto de: artigo, revisao, preprint, conferencia, livro_capitulo
  idiomas: []            # códigos ISO 639-1: en, pt, es, ...
  somente_oa: false
  campo_busca: tudo      # tudo | titulo | titulo_resumo

enriquecimento:
  referencias: true      # lista de referências + contagem de citações quando faltar
  resolver_ids_para_doi: true   # converte IDs internos (ex.: OpenAlex W...) em DOI quando possível
  texto_completo: true   # CORE e Europe PMC (OA)

saida:
  diretorio: saida
  raw_json: true         # inclui a resposta original da API em cada linha
  separador_lista: " | "

execucao:
  max_paginas_extras_filtro_local: 10   # teto de páginas além do necessário quando há filtro local
  cache_http: true                      # cache em disco das respostas (TTL 24 h)
  timeout_s: 30
  log_nivel: INFO

limites:                 # sobrescreve os padrões da seção 7 (opcional)
  # arxiv: {taxa_rps: 0.33, concorrencia: 1}
```

### 5.2 `.env` (gerar `.env.example` com comentários)

```bash
# Obrigatória — conta gratuita em https://openalex.org → Settings → API
OPENALEX_API_KEY=

# Recomendado — e-mail de contato (Crossref polite pool, NCBI, User-Agent)
CONTACT_EMAIL=

# Opcionais — deixar vazio se não tiver
NCBI_API_KEY=            # https://www.ncbi.nlm.nih.gov/account/
S2_API_KEY=              # https://www.semanticscholar.org/product/api (formulário)
CORE_API_KEY=            # https://core.ac.uk/services/api
OPENCITATIONS_TOKEN=     # https://opencitations.net/accesstoken
```

Regras:
- Base cuja credencial obrigatória está vazia é **pulada**, com aviso no relatório (não derruba a execução).
- Segredos nunca aparecem em logs, CSV, `raw_json` (remover `api_key`/`mailto` de URLs gravadas) nem no relatório.

### 5.3 CLI

```bash
python -m coletor --config config.yaml
python -m coletor --config config.yaml --query "deep learning" --max 50 --bases openalex,arxiv
python -m coletor --config config.yaml --sem-raw-json
python -m coletor --listar-bases          # mostra bases, status (ativa/inativa) e credenciais detectadas
```

Argumentos de linha de comando sobrescrevem o `config.yaml`. Código de saída: `0` se ao menos uma base gerou CSV; `1` se todas falharam; `2` erro de configuração.

---

## 6. Filtros e mapeamento por base

Valores canônicos: `tipos ∈ {artigo, revisao, preprint, conferencia, livro_capitulo}`; `idiomas` em ISO 639-1; `campo_busca ∈ {tudo, titulo, titulo_resumo}`.

Legenda: **N** nativo na API · **L** local (aplicado após a coleta) · **—** não se aplica (ver regra).

| Filtro | OpenAlex | Semantic Scholar | Crossref | arXiv | PubMed | Europe PMC | CORE | DOAJ | SciELO |
|---|---|---|---|---|---|---|---|---|---|
| Período | N `from_publication_date`/`to_publication_date` | N `year=AAAA-AAAA` (não verificado: 429 sem chave) | N `from-pub-date`/`until-pub-date` | N `submittedDate:[AAAAMMDD0000 TO AAAAMMDD2359]` (data de submissão) | N `AAAA:AAAA[dp]` | N `PUB_YEAR:[a TO b]` | N `yearPublished>=a AND yearPublished<=b` | N `bibjson.year:[a TO b]` | — (desabilitada) |
| Tipo | N `type` (+ `primary_location.source.type:conference` p/ conferência) | N `publicationTypes` (preprint: L) | N `type` (revisão: L) | — só preprints | N `[pt]` / `booksdocs[filter]`; conferência: L | N `PUB_TYPE` / `SRC:PPR`; conferência e livro: L | L `documentType` | — só artigos | — |
| Idioma | N `language` | L | L (campo `language`) | L | N `por[la]` (ISO 639-2) | N `LANG:"por"` (**ISO 639-2, 3 letras**; `LANG:"pt"` não funciona) | N `language.code:pt` | L (idioma do periódico) | — |
| Só OA | N `open_access.is_oa:true` | N `openAccessPdf` (não verificado: 429 sem chave) | L (licença/link aberto) | — tudo OA | N `free full text[sb]` | N `OPEN_ACCESS:y` | — tudo OA | — tudo OA | — |
| Campo de busca | N `search` / `title.search` / `title_and_abstract.search` | L (só busca geral; filtrar título localmente) | N `query.bibliographic` para `tudo`; L para `titulo` | N `all:` / `ti:` / `ti: OR abs:` | N `[tiab]` / `[ti]` | N `TITLE:` / `TITLE: OR ABSTRACT:` | N `title:` / `abstract:` | N `bibjson.title:` / `bibjson.abstract:` | — |

Observação: no OpenAlex, `search=` é executado como `fulltext.search` (título, resumo e texto completo) — usado para `campo_busca: tudo`.

Tabela de tipos (confirmada no teste prático; **L** = filtro local):

| Canônico | OpenAlex `type` | S2 `publicationTypes` | Crossref `type` | PubMed | Europe PMC | CORE `documentType` (L) |
|---|---|---|---|---|---|---|
| artigo | `article` | `JournalArticle` | `journal-article` | `"Journal Article"[pt]` | `PUB_TYPE:"journal article"` | `research article`, `journal article`, `article` |
| revisao | `review` | `Review` | L | `Review[pt]` | `PUB_TYPE:"review"` | `review` |
| preprint | `preprint` | L | `posted-content` | `Preprint[pt]` | `SRC:PPR` | `preprint` |
| conferencia | filtro `primary_location.source.type:conference`; valor `conference-paper` | `Conference` | `proceedings-article` | **L** (`PublicationType` = `Congress`) | L | `conference paper` |
| livro_capitulo | `book`, `book-chapter` | `Book`, `BookSection` (não verificado) | `book`, `book-chapter`, `monograph` | **`booksdocs[filter]`** | L | `book`, `book chapter` |

Regras de filtro:
1. **Filtro local:** a base é paginada além do necessário até atingir `max_artigos_por_base` registros aprovados ou `max_paginas_extras_filtro_local` páginas extras, o que vier primeiro. O relatório informa quantos registros foram descartados e se o teto foi atingido.
2. **Registro sem o dado do filtro local** (ex.: sem idioma informado): é **mantido** e recebe aviso na coluna `avisos` (`idioma_nao_verificado`).
3. **Base sem nenhum dado para o filtro** (ex.: idioma no Semantic Scholar e no arXiv): o filtro é ignorado naquela base, com aviso no relatório.
4. **Filtro incompatível com a base** (ex.: `tipos: [revisao]` no arXiv, que só tem preprints; ou DOAJ, que só tem artigos): a base é pulada com aviso.
5. **Tradução da consulta:** AND / OR / aspas da `query` são convertidos para a sintaxe de cada base (OpenAlex/S2/Crossref: texto; arXiv: `AND`/`OR` com prefixo de campo; PubMed/Europe PMC/CORE/DOAJ: booleanos nativos). Escapar caracteres especiais de Lucene no DOAJ/CORE.

---

## 7. Paralelismo e limites de taxa

- O orquestrador executa uma tarefa assíncrona por base ativa (`asyncio.gather` com `return_exceptions=True`). Uma base lenta ou com falha não afeta as outras.
- Cada base tem seu próprio **limitador**: taxa (token bucket, req/s) + semáforo de concorrência. O enriquecedor OpenCitations tem limitador próprio, compartilhado entre as bases.

Padrões (sobrescrevíveis em `limites:`):

| Base | Taxa inicial (req/s) | Concorrência | Itens por página |
|---|---|---|---|
| openalex | 10 | 5 | 100 |
| semantic_scholar | 1 | 1 | 100 |
| crossref | 3 com e-mail / 1 sem | 3 / 1 | 100 |
| arxiv | 0,33 (1 a cada 3 s) | 1 | 100 |
| pubmed | 3 sem chave / 9 com chave | 3 | 100 (efetch em lote) |
| europepmc | 2 (confirmado: 0 × 429) | 2 | 100 |
| core | 0,5 sem chave / 2 com chave | 1 | 100 |
| doaj | 2 | 1 | 100 |
| scielo | — (desabilitada) | — | — |
| opencitations | 3 | 3 | — |

Política de retentativa e taxa adaptativa:
1. **429:** reduzir a taxa da base pela metade (piso: 1 req a cada 10 s); esperar `Retry-After` se vier, senão backoff exponencial com jitter (2, 4, 8, 16, 32 s; arXiv até ~3 min no total); repetir até **6 tentativas**.
2. **5xx, timeout, erro de conexão:** mesmo backoff, sem reduzir a taxa; até 6 tentativas.
3. **Recuperação:** após 20 respostas bem-sucedidas seguidas, aumentar a taxa em 25%, sem passar da taxa inicial.
4. **4xx diferente de 429:** não repetir; registrar erro e encerrar a base (erro de parâmetro ou credencial).
5. **OpenAlex:** ler `X-RateLimit-Remaining`; se o orçamento diário acabar, encerrar a base com o que já foi coletado e avisar.
6. Esgotadas as tentativas numa página, a base é encerrada com os registros já gravados e status `parcial` no relatório.
7. `User-Agent`: `coletor-artigos/1.0 (mailto:CONTACT_EMAIL)`.

---

## 8. Fluxo por base

1. Traduzir consulta e filtros nativos para a base.
2. Paginar a busca até `max_artigos_por_base` (aplicando filtros locais).
3. Normalizar cada registro para o esquema da seção 9; gravar `raw_json`.
4. Enriquecer (se ligado) — seção 8.1.
5. Gravar no CSV da base (escrita em fluxo, por lote).
6. Remover duplicatas dentro da base (por `id_na_base` e, depois, por `doi`).

### 8.1 Enriquecimento

| Base | Referências | Contagem de citações | Relacionados | Texto completo |
|---|---|---|---|---|
| openalex | nativo `referenced_works` (IDs W); se `resolver_ids_para_doi`, converter em DOI por lote (`filter=openalex_id:W1\|W2...`, até 100 IDs por chamada) | nativo `cited_by_count`, `counts_by_year`, `citation_normalized_percentile`, `fwci` | nativo `related_works` (convertidos em DOI pelo mesmo lote) | — (endpoint de conteúdo é pago; fora) |
| semantic_scholar | `POST /paper/batch` (até 500 IDs) com `fields=references.externalIds,references.paperId`; DOI quando houver, senão `S2:paperId` | nativo `citationCount`, `influentialCitationCount` | — | — |
| crossref | nativo `reference[].DOI` (quando depositado); se vazio e houver DOI → OpenCitations | nativo `is-referenced-by-count` | — | — |
| europepmc | `/{source}/{id}/references` quando `hasReferences=Y` (1 chamada por artigo, paginada); referência com `source=MED` sem DOI → `pmid:<id>` | nativo `citedByCount` | — | `/{PMCID}/fullTextXML` para artigos OA com PMCID, convertido em texto (seção 9.3) |
| core | OpenCitations pelo DOI | OpenCitations (o `citationCount` do CORE vem sempre 0) | — | campo `fullText` **somente com `CORE_API_KEY`** (se não vier na busca, `GET /v3/works/{id}`); sem chave: vazio + aviso `texto_completo_requer_chave` |
| pubmed | nativo `PubmedData/ReferenceList` quando houver; senão OpenCitations pelo DOI (`pmid:` se não houver DOI) | OpenCitations `/citation-count` | — | — |
| arxiv, doaj | OpenCitations pelo DOI | OpenCitations `/citation-count` | — | — |

- Artigo sem DOI (e sem PMID no PubMed) não é enriquecido via OpenCitations; `fonte_referencias = nenhuma`.
- OpenCitations: `count` vem como string; em `/references`, o campo `cited` traz vários IDs separados por espaço (`omid:… doi:… pmid:…`) — gravar o `doi:`, senão o `pmid:`.
- Falha no enriquecimento não descarta o artigo: grava com campos vazios e aviso.

---

## 9. Saída

### 9.1 Arquivos

```
saida/AAAA-MM-DD_HHMMSS_<slug-da-query>/
  openalex.csv
  semantic_scholar.csv
  ...                       # um CSV por base que retornou ao menos o cabeçalho
  consolidado.csv           # todas as bases, sem duplicatas (seção 9.5)
  relatorio.md              # resumo da execução
  relatorio.json            # mesmo conteúdo, legível por máquina
  execucao.log
  config_usada.yaml         # config efetiva (sem segredos)
```

Base que falhou ou não retornou nada também gera seu CSV, só com o cabeçalho, para padronizar.

### 9.2 Formato do CSV

- RFC 4180; separador `,`; **todos os campos entre aspas** (`csv.QUOTE_ALL`); aspas internas duplicadas; quebras de linha preservadas dentro das aspas (normalizar `\r\n` → `\n`).
- Codificação `utf-8-sig` (UTF-8 com BOM).
- Listas numa célula separadas por ` | ` (o caractere `|` dentro de um item é substituído por `/`).
- Booleanos `true`/`false`; datas ISO `AAAA-MM-DD`; vazio = campo vazio (nunca `None`, `null` ou `N/A`).
- Observação para o usuário (README): o Excel exibe no máximo 32.767 caracteres por célula; o arquivo mantém o texto inteiro.

### 9.3 Colunas (ordem fixa, todas presentes em todos os CSVs)

| # | Coluna | Conteúdo |
|---|---|---|
| 1 | `base` | chave da base |
| 2 | `id_na_base` | ID nativo (W..., paperId, PMID, arXiv ID, CORE ID, etc.) |
| 3 | `doi` | DOI normalizado (minúsculo, sem prefixo `https://doi.org/`) |
| 4 | `pmid` | |
| 5 | `pmcid` | |
| 6 | `arxiv_id` | |
| 7 | `url_pagina` | página do artigo |
| 8 | `consulta` | query usada |
| 9 | `coletado_em` | timestamp ISO 8601 UTC |
| 10 | `titulo` | |
| 11 | `autores` | nomes, em ordem, separados por ` | ` |
| 12 | `autores_orcid` | ORCID alinhado à ordem de `autores` (vazio quando não houver) |
| 13 | `afiliacoes` | afiliações únicas |
| 14 | `ano` | |
| 15 | `data_publicacao` | |
| 16 | `tipo` | valor canônico (seção 6) quando mapeável; senão o valor original |
| 17 | `idioma` | ISO 639-1 quando possível |
| 18 | `veiculo` | periódico / evento / repositório |
| 19 | `issn` | |
| 20 | `editora` | |
| 21 | `volume` | |
| 22 | `numero` | |
| 23 | `paginas` | |
| 24 | `resumo` | texto plano (sem tags JATS/HTML); OpenAlex: reconstruído do `abstract_inverted_index` |
| 25 | `tldr` | resumo automático (Semantic Scholar) |
| 26 | `palavras_chave` | |
| 27 | `assuntos` | categorias, MeSH, tópicos, áreas |
| 28 | `texto_completo` | texto plano; parágrafos separados por `\n` |
| 29 | `acesso_aberto` | true/false |
| 30 | `status_oa` | ex.: gold, green, hybrid, bronze |
| 31 | `licenca` | |
| 32 | `url_pdf` | |
| 33 | `n_citacoes` | |
| 34 | `n_citacoes_influentes` | |
| 35 | `citacoes_por_ano` | `AAAA:n | AAAA:n` (mais recente primeiro) |
| 36 | `percentil_citacoes` | |
| 37 | `fwci` | |
| 38 | `n_referencias` | |
| 39 | `referencias` | DOIs (ou IDs prefixados, ex.: `openalex:W123`, `pmid:123`, `s2:abc`) |
| 40 | `relacionados` | DOIs/IDs de trabalhos relacionados |
| 41 | `fonte_referencias` | `nativa` · `opencitations` · `nenhuma` |
| 42 | `fonte_citacoes` | `nativa` · `opencitations` · `nenhuma` |
| 43 | `financiadores` | |
| 44 | `retratado` | true/false/vazio |
| 45 | `avisos` | códigos de aviso separados por ` | ` (ex.: `idioma_nao_verificado`, `enriquecimento_falhou`, `texto_completo_requer_chave`) |
| 46+ | `x_<base>_<campo>` | colunas exclusivas da base, **só no CSV daquela base**, na ordem da tabela abaixo |
| último | `raw_json` | resposta original do registro, JSON compacto (omitida com `raw_json: false`) |

As colunas 1–45 estão em todos os CSVs, na ordem acima. Campos não mapeados continuam disponíveis no `raw_json`. O campo de origem de cada coluna, por base, está em `docs/relatorio_teste_pratico.md` (seção 2).

Colunas `x_<base>_*` (definidas no teste prático):

| Base | Colunas (campo de origem) |
|---|---|
| openalex | `x_openalex_topico_principal` (primary_topic.display_name), `x_openalex_area` (primary_topic.field.display_name), `x_openalex_tipo_fonte` (primary_location.source.type), `x_openalex_paises` (authorships[].countries[], únicos), `x_openalex_indexado_em` (indexed_in[]), `x_openalex_apc_usd` (apc_paid.value_usd), `x_openalex_ods` (sustainable_development_goals[].display_name), `x_openalex_mesh` (mesh[].descriptor_name) |
| semantic_scholar | `x_s2_corpus_id` (corpusId), `x_s2_dblp` (externalIds.DBLP), `x_s2_mag` (externalIds.MAG), `x_s2_tipo_veiculo` (publicationVenue.type) |
| crossref | `x_crossref_isbn` (ISBN[]), `x_crossref_evento` (event.name), `x_crossref_numero_artigo` (article-number), `x_crossref_subtitulo` (subtitle[]), `x_crossref_subtipo` (subtype), `x_crossref_membro` (member) |
| arxiv | `x_arxiv_comentario` (arxiv:comment), `x_arxiv_journal_ref` (arxiv:journal_ref), `x_arxiv_categoria_primaria` (arxiv:primary_category/@term), `x_arxiv_atualizado_em` (updated), `x_arxiv_versao` (sufixo vN do id) |
| pubmed | `x_pubmed_mesh_qualificadores` (MeshHeading: Descritor/Qualificador), `x_pubmed_pais_periodico` (MedlineJournalInfo/Country), `x_pubmed_nlm_id` (NlmUniqueID), `x_pubmed_status` (MedlineCitation/@Status), `x_pubmed_conflito_interesses` (CoiStatement) |
| europepmc | `x_epmc_fonte` (source), `x_epmc_grants` (grantsList.grant[]: agency: grantId), `x_epmc_substancias` (chemicalList.chemical[].name), `x_epmc_mesh_qualificadores` (meshQualifier[].qualifierName), `x_epmc_versao_preprint` (versionNumber), `x_epmc_tem_dados` (hasData) |
| core | `x_core_provedores` (dataProviders[].name), `x_core_oai` (oaiIds[]), `x_core_data_deposito` (depositedDate) |
| doaj | `x_doaj_pais_periodico` (bibjson.journal.country), `x_doaj_assunto_lcc` (bibjson.subject[].code) |

### 9.4 Relatório da execução

Por base: status (`ok` · `parcial` · `falhou` · `pulada`), motivo, artigos pedidos/gravados, total de resultados informado pela API, páginas e chamadas feitas, 429 recebidos, taxa final, registros descartados por filtro local, filtros ignorados, artigos enriquecidos, duração. No topo: query, filtros, horário, duração total. Consolidado: registros de entrada, duplicatas removidas, artigos descartados por falta de DOI ou resumo, linhas gravadas, artigos encontrados em 2 ou mais bases.

### 9.5 CSV consolidado (`consolidado.csv`)

Mesmo formato da seção 9.2. Gerado no fim de toda execução a partir dos registros gravados nos CSVs por base (que continuam existindo); base que falhou não contribui. Uma linha por artigo.

**Deduplicação (no momento da fusão):** dois registros são o mesmo artigo quando compartilham DOI, PMID, PMCID ou ID arXiv (ligação transitiva: PubMed com DOI+PMID e Europe PMC só com o PMID caem no mesmo grupo). Sem identificador em comum, também são fundidos quando têm o mesmo título normalizado (minúsculas, sem acentos e pontuação) com **5 palavras ou mais** e o mesmo ano — títulos curtos e genéricos ("Machine Learning") não são fundidos por título, e a fusão por título nunca junta grupos com DOIs diferentes. Vale também dentro de uma mesma base (ex.: registros repetidos do CORE). PMID, PMCID e ID arXiv são usados só para achar duplicatas; não são colunas do consolidado.

**Filtro (depois da fusão):** só ficam os artigos com **DOI e resumo**. Como o filtro é aplicado ao artigo já fundido, basta que o DOI venha de uma base e o resumo de outra.

Prioridade de bases para campos de valor único: **crossref > openalex > pubmed > europepmc > semantic_scholar > doaj > core > arxiv**; para `resumo`: **pubmed > europepmc > openalex > semantic_scholar > doaj > core > arxiv > crossref**.

| # | Coluna | Regra de fusão |
|---|---|---|
| 1 | `doi` | primeiro não vazio na prioridade (obrigatório: artigo sem DOI é descartado) |
| 2 | `bases` | bases em que o artigo apareceu, na ordem de `bases_ativas` |
| 3 | `ids_por_base` | `<base>:<id_na_base>` de cada registro fundido |
| 4 | `titulo` | primeiro não vazio na prioridade |
| 5 | `autores` | idem |
| 6 | `ano` | idem |
| 7 | `data_publicacao` | idem |
| 8 | `tipo` | primeiro valor canônico (seção 6) na prioridade; senão o primeiro não vazio |
| 9 | `idioma` | primeiro não vazio na prioridade |
| 10 | `resumo` | primeiro não vazio na prioridade de resumo (obrigatório: artigo sem resumo é descartado) |
| 11 | `palavras_chave` | união sem repetição (sem diferenciar maiúsculas) |
| 12 | `assuntos` | idem |
| 13 | `url_pdf` | primeiro não vazio na prioridade |
| 14 | `n_citacoes` | maior valor entre as bases |
| 15 | `n_referencias` | maior valor entre as bases |
| 16 | `referencias` | união sem repetição |

Ficam só nos CSVs por base: `id_na_base` (aparece em `ids_por_base`), `pmid`, `pmcid`, `arxiv_id`, `url_pagina`, `consulta`, `coletado_em`, `autores_orcid`, `afiliacoes`, `veiculo`, `issn`, `editora`, `volume`, `numero`, `paginas`, `tldr`, `texto_completo`, `acesso_aberto`, `status_oa`, `licenca`, `n_citacoes_influentes`, `citacoes_por_ano`, `percentil_citacoes`, `fwci`, `relacionados`, `fonte_referencias`, `fonte_citacoes`, `financiadores`, `retratado`, `avisos`, `x_<base>_*` e `raw_json`.

---

## 10. Arquitetura e estrutura do código

```
pyproject.toml          # dependências: httpx, pydantic, pyyaml, python-dotenv, lxml; dev: pytest, pytest-asyncio, respx
config.yaml             # exemplo da seção 5.1
.env.example
README.md               # instalação (venv), configuração, uso, colunas, limitações
coletor/
  __main__.py / cli.py  # argumentos, carga de config + .env, validação
  config.py             # modelo pydantic da configuração
  orquestrador.py       # uma tarefa por base, coleta de resultados, relatório
  http.py               # cliente httpx compartilhado, cache em disco, User-Agent
  limitador.py          # token bucket + semáforo + taxa adaptativa + retry
  modelo.py             # Registro (esquema da seção 9.3)
  consulta.py           # parser da query (AND/OR/aspas) e tradução por base
  filtros.py            # mapeamentos da seção 6 + filtro local
  bases/
    __init__.py         # registro BASES = {"openalex": OpenAlexAdapter, ...}
    base.py             # classe abstrata Adaptador
    openalex.py  semantic_scholar.py  crossref.py  arxiv.py
    pubmed.py  europepmc.py  core.py  doaj.py  scielo.py
  enriquecimento/
    opencitations.py  openalex_ids.py  semantic_scholar.py  europepmc.py  core.py
  saida/
    csv_writer.py  relatorio.py
scripts/
  teste_pratico.py      # validação real das APIs (seção 11)
tests/
  fixtures/<base>/      # respostas reais gravadas
  test_<base>.py        # normalização a partir das fixtures
  test_limitador.py  test_consulta.py  test_filtros.py  test_csv.py
docs/
  relatorio_teste_pratico.md
```

Interface do adaptador:

```python
class Adaptador(ABC):
    chave: str
    credencial_obrigatoria: str | None
    def suporta(self, filtros) -> SuporteFiltros          # nativo / local / incompatível por filtro
    async def buscar(self, consulta, filtros, limite) -> AsyncIterator[Registro]
    async def enriquecer(self, registros, opcoes) -> list[Registro]
```

Adicionar uma base nova = criar um adaptador e registrá-lo em `BASES`; remover = tirar de `bases_ativas`.

---

## 11. Teste prático (primeira fase da implementação)

> **Executado em 31/10/2026.** Resultados em `docs/relatorio_teste_pratico.md`; mudanças aplicadas a este documento na seção 15.

Script `scripts/teste_pratico.py` que, para cada base, faz uma busca real pequena (consulta `machine learning`, 5 resultados, mais 1 filtro de período e 1 de idioma) e uma chamada de cada endpoint de enriquecimento, salvando as respostas em `tests/fixtures/<base>/` e gerando `docs/relatorio_teste_pratico.md` com:

1. Campos realmente retornados × colunas da seção 9.3 (atualizar a matriz).
2. Confirmação de cada parâmetro de filtro da seção 6 (funciona / não funciona / sintaxe correta).
3. Limites observados (headers de rate limit, 429).
4. **Decisões automáticas:**
   - **SciELO:** sem busca por palavra-chave estruturada → remover de `bases_ativas` no `config.yaml` de exemplo, manter o adaptador marcado como `desabilitado` com o motivo, e documentar no README.
   - **CORE sem chave:** se anônimo receber sempre 429 → marcar `CORE_API_KEY` como obrigatória para essa base no adaptador e documentar (base pulada com aviso quando vazia).
   - **Europe PMC:** se houver 429 a 2 req/s → reduzir o padrão.
   - Qualquer parâmetro de filtro que não funcione como descrito → trocar para filtro local (L) e registrar.
5. Lista de colunas `x_<base>_*` propostas para cada base.

---

## 12. Critérios de aceite

1. `python -m coletor --config config.yaml` com OpenAlex configurado gera um CSV por base ativa, `consolidado.csv` (sem duplicatas entre bases), `relatorio.md`, `relatorio.json`, `execucao.log` e `config_usada.yaml`.
2. Com `max_artigos_por_base: 100`, cada base que tem ao menos 100 resultados grava 100 linhas (DOAJ e demais: menos apenas se a API tiver menos resultados ou o teto de filtro local for atingido, registrado no relatório).
3. As bases rodam em paralelo: o tempo total é próximo do da base mais lenta, não da soma.
4. Nenhuma base excede seus limites configurados; um 429 provoca redução de taxa e retentativa, visível no log.
5. Remover uma base de `bases_ativas` a desativa sem alteração de código.
6. Base sem credencial obrigatória é pulada com aviso; as demais rodam.
7. Os CSVs abrem corretamente no pandas (`pd.read_csv(..., encoding="utf-8-sig")`) e no LibreOffice/Excel, com vírgulas, aspas e quebras de linha em resumos intactas; todas as colunas da seção 9.3 presentes, na ordem.
8. `raw_json: false` (ou `--sem-raw-json`) remove a coluna.
9. Filtros nativos são enviados à API; filtros locais respeitam o teto e aparecem no relatório.
10. Referências preenchidas (nativas ou via OpenCitations) para artigos com DOI, quando a fonte as tiver.
11. Nenhum segredo aparece em arquivos de saída ou logs.
12. `pytest` passa sem acesso à internet (usa fixtures).
13. A interface HTTP recebe e valida parâmetros e critérios digitados na tela, persiste as entradas no `localStorage` do navegador e não expõe credenciais. Não lê `config.yaml` nem `criteria.txt` como entrada. Acesso não local exige token forte e POST remoto valida a origem.
14. Depois da busca, `ranking.csv` preserva as 16 colunas do consolidado e acrescenta `llm_label`, `llm_match`, `llm_justification`, `llm_score` e `llm_status`; score decrescente e falhas no fim.
15. O score inclui aderência, ano e `n_citacoes` nas proporções 70/15/15; citações são transformadas por `log(1+n)` e valores ausentes recebem 0,5.
16. A citação produzida pelo modelo deve aparecer literalmente no resumo; falha em um artigo não interrompe os demais.

---

## 13. Fases de implementação

1. **Teste prático** (seção 11) e ajuste deste escopo/matrizes com os resultados.
2. **Núcleo:** config, CLI, HTTP + cache, limitador adaptativo, modelo, gravador CSV, relatório, orquestrador; adaptadores **OpenAlex** e **arXiv**.
3. **Demais bases:** Semantic Scholar, Crossref, PubMed, Europe PMC, CORE, DOAJ, SciELO (ou desabilitada).
4. **Enriquecimento:** referências, conversão de IDs para DOI, OpenCitations, texto completo.
5. **Testes, README e verificação dos critérios de aceite.**
6. **Extensão autorizada (seção 16):** interface local e triagem LLM com geração de `ranking.csv`.

**Etapa 2 (futura, fora desta versão):** sobrescrita da consulta por base; ordenação. (O CSV consolidado passou para esta versão — seção 15.4.)

---

## 14. Fontes consultadas (out/2026)

- OpenAlex — autenticação, preços e limites: https://developers.openalex.org/api-reference/authentication
- OpenAlex — filtros: https://developers.openalex.org/guides/filtering
- Semantic Scholar — API: https://semanticscholar.org/product/api
- Crossref — limites da REST API: https://crossref.org/blog/announcing-changes-to-rest-api-rate-limits/ e https://community.crossref.org/t/refining-rest-api-limits-for-improved-stability-and-reliability/16137
- arXiv — termos de uso da API: https://info.arxiv.org/help/api/tou.html
- Europe PMC — métodos da API (cliente rOpenSci): https://docs.ropensci.org/europepmc/
- CORE — API: https://core.ac.uk/services/api
- DOAJ — documentação (limite de taxa): https://testdoaj.cottagelabs.com/api/v3/docs ; limite de 1.000 resultados: https://groups.google.com/g/doaj-public-api/c/wHecwneNrPM/m/Xp5NXP4FAQAJ
- OpenCitations — Index API v2: https://api.opencitations.net/index

---

## 15. Ajustes pós-teste prático (31/10/2026)

Teste executado com `scripts/teste_pratico.py` (respostas em `tests/fixtures/<base>/`, relatório em `docs/relatorio_teste_pratico.md`). Credenciais na coleta: só `OPENALEX_API_KEY` e `CONTACT_EMAIL`.

### 15.1 Decisões automáticas (regras da seção 11)

| Item | Evidência | Mudança |
|---|---|---|
| SciELO | ArticleMeta sem busca por palavra-chave (`q=` → 404); search.scielo.org com `robots.txt` `Disallow: /` para robôs e 403 (desafio anti-robô) em `output=json/xml/rss` | **Desabilitada**: fora de `bases_ativas` (5.1); adaptador marcado `desabilitado` com o motivo; documentar no README (seções 2, 4, 6, 7) |
| CORE sem chave | 0 respostas 429 em 7 chamadas anônimas | `CORE_API_KEY` continua **opcional** |
| Europe PMC | 0 respostas 429 em 34 chamadas, incluindo rajada de 20 a 2 req/s | Mantém 2 req/s (seção 7) |
| PubMed, tipo=conferencia | `Congress[pt]` não reconhecido; `"Congress"[Publication Type]` aceito, mas 0 resultados | **N → L** (seção 6) |
| PubMed, tipo=livro_capitulo | `"Book Chapter"[pt]` não existe; `booksdocs[filter]` → 152 resultados | Sintaxe corrigida: **N `booksdocs[filter]`** (seção 6) |
| Europe PMC, idioma | `LANG:"pt"` mistura idiomas; `LANG:"por"` → 5/5 | Sintaxe corrigida: **`LANG:"<ISO 639-2>"`** (seção 6) |

### 15.2 Decisões do usuário (casos fora da seção 11)

| Item | Decisão |
|---|---|
| CORE: sem chave, `fullText` = "Not available for public API users." | Chave continua opcional; sem chave, `texto_completo` vazio + aviso `texto_completo_requer_chave` (seções 4, 8.1, 9.3) |
| Semantic Scholar sem chave: 57 de 63 chamadas com 429; `year`, `publicationTypes=Book,BookSection` e `openAccessPdf` não verificados | Chave continua opcional; base pode terminar `parcial`; filtros não verificados ficam nativos (seção 6); README recomenda pedir a chave |
| PubMed: ordem padrão do `esearch` = mais recentes | Enviar `sort=relevance` (seção 4) |
| Posição das colunas `x_<base>_*` | Só no CSV da própria base, entre `avisos` e `raw_json` (seção 9.3) |

### 15.3 Ajustes técnicos

- Crossref: paginação por `offset` em vez de `cursor` (o cursor descarta a ordem por relevância) (seção 4).
- PubMed: referências nativas de `PubmedData/ReferenceList` quando houver, com OpenCitations como alternativa; livros vêm como `PubmedBookArticle` (seções 4, 8.1).
- CORE: `citationCount` vem sempre 0, então a contagem sai do OpenCitations (seção 8.1). `documentType` é texto livre, com mapeamento local na tabela de tipos (seção 6).
- OpenAlex: `search=` é executado como `fulltext.search`; tipo `conference-paper` mapeado para `conferencia`. Custo medido: US$ 0,001 por busca e US$ 0,0001 por lote de conversão de IDs (seções 6, 8.1).
- PubMed e Europe PMC devolvem idioma em 3 letras: converter para ISO 639-1 na coluna `idioma`.
- Matriz coluna × campo de cada base e lista das colunas `x_`: seção 9.3 e `docs/relatorio_teste_pratico.md`.

### 15.4 CSV consolidado (decisão do usuário, 31/10/2026)

O CSV consolidado sem duplicatas entre bases, antes previsto para a Etapa 2, passa a fazer parte desta versão: toda execução gera os CSVs por base **e** `consolidado.csv`, removendo duplicatas no momento da fusão (seções 2, 3, 9.1, 9.4, 9.5, 12 e 13). Colunas escolhidas pelo usuário a partir da proposta de integração: sem o grupo de controle (`financiadores`, `retratado`, `avisos`, `consulta`, `coletado_em`), sem `veiculo`, `editora`, `volume`, `numero`, `paginas` e sem `percentil_citacoes`.

Revisão do usuário (31/10/2026), depois da primeira versão: removidas do consolidado as colunas `id_consolidado`, `pmid`, `pmcid`, `arxiv_id`, `url_pagina`, `n_bases`, `acesso_aberto`, `status_oa`, `licenca` e `fonte_n_citacoes`; e só entram artigos com DOI e resumo (filtro aplicado depois da fusão). Resultado: 19 colunas (seção 9.5).

Segunda revisão do usuário (31/10/2026): removidas também `fwci`, `tldr` e `issn`. Resultado: 16 colunas (seção 9.5).

## 16. Adendo autorizado pelo usuário — triagem LLM e interface local (31/10/2026)

- A busca continua sendo feita pelo coletor existente. Consulta, parâmetros equivalentes ao YAML, critérios de triagem e modelo são fornecidos na interface. O botão de salvar persiste os campos no `localStorage` do navegador; a tela não carrega `config.yaml` nem `criteria.txt`.
- O processamento LLM usa o Ollama local (padrão `qwen3.5:0.8b`); não envia título/resumo a um serviço hospedado. O serviço Ollama precisa estar ativo e o modelo instalado. As APIs bibliográficas continuam sendo acessadas conforme as regras das seções 4 e 7.
- `ranking.csv` é uma saída separada na pasta da execução. `consolidado.csv` e os CSVs por base não são alterados nem reordenados.
- Colunas adicionais, na ordem: `llm_label`, `llm_match`, `llm_justification`, `llm_score`, `llm_status`. `llm_match` admite 1, 0,5 e 0; `llm_label` assume `incluido`, `duvidoso` e `excluido`. `llm_status` informa `ok` ou `erro`.
- Fórmula: `0,70 × match + 0,15 × recência + 0,15 × citações`. Recência é min-max do ano no próprio consolidado; citações aplicam `log(1+n_citacoes)` antes do min-max. Componentes ausentes ou constantes recebem 0,5. Score é arredondado a três casas.
- O HTML, CSS e JavaScript ficam em `web/` e são servidos por `python -m coletor --web` em `0.0.0.0:8000` por padrão (host e porta configuráveis). Cada execução cria uma nova pasta dentro de `./saida/`, contendo `config.yaml`, `criterios.txt`, `config_usada.yaml` e os demais artefatos, incluindo `ranking.csv` quando a triagem termina. O histórico lista pastas e permite baixar arquivos. Nenhum formulário de entrada é lido de YAML/TXT nem segredo é coletado pela interface.
- Ao iniciar o servidor web, a aplicação tenta iniciar `ollama serve` se ainda não estiver acessível e aquece o modelo padrão `qwen3.5:0.8b`, desde que já esteja instalado localmente. Não baixa automaticamente modelos grandes. O serviço iniciado pela aplicação é encerrado no desligamento do servidor; um serviço Ollama que já estava ativo não é encerrado.
- A ferramenta grava uma justificativa com citação literal do resumo e rejeita a resposta se o trecho não for encontrado no texto. Erros individuais não interrompem as avaliações restantes; registros com erro têm score vazio e ficam ao fim do ranking.
- A interface não edita o `.env` e não permite escolher provedores externos. Clientes fora de loopback usam página de login com `COLETOR_WEB_TOKEN` (mínimo 32 caracteres), sessão HMAC em cookie HttpOnly/Secure/SameSite, expiração de 12 h, limite de tentativas e verificação de origem em POST; acesso à Internet deve ser servido por proxy reverso HTTPS/TLS.
- O seletor de modelos enumera apenas modelos locais retornados pelo endpoint Ollama `list`; uma seleção alternativa é carregada no começo da pesquisa. O uso de acelerador é delegado ao Ollama, sem opção de forçar CPU/GPU no código; a UI exibe uma estimativa de alocação calculada com `size_vram / size` de `ollama ps`.
