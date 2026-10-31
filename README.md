# final-project-te251

Coletor multibase de artigos científicos: recebe uma consulta, busca em paralelo em várias bases acadêmicas (OpenAlex, Semantic Scholar, Crossref, arXiv, PubMed, Europe PMC, CORE e DOAJ) e grava um CSV por base e um CSV consolidado. Especificação completa em [ESCOPO.md](ESCOPO.md).

> A descrição das colunas dos CSVs por base será documentada na fase 5.

## Como executar

Requisitos: Linux e Python 3.11 ou mais recente.

### 1. Instalar (uma vez)

```bash
cd final-project-te251
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Credenciais (`.env`, uma vez)

```bash
cp .env.example .env
```

Edite o `.env`:

- `OPENALEX_API_KEY` — **obrigatória** para a base OpenAlex (conta gratuita em <https://openalex.org>, *Settings → API*). Sem ela, o OpenAlex é pulado e as demais bases rodam normalmente.
- `CONTACT_EMAIL` — recomendado: identifica você para Crossref e PubMed, que dão limites de taxa melhores com e-mail.
- `NCBI_API_KEY`, `S2_API_KEY`, `CORE_API_KEY`, `OPENCITATIONS_TOKEN` — opcionais; deixe vazio se não tiver. Sem `S2_API_KEY` o Semantic Scholar costuma falhar por limite de taxa; sem `CORE_API_KEY` o CORE não entrega texto completo.

O `.env` é lido da pasta em que o comando é executado (ou de uma pasta acima dela). As chaves nunca são gravadas nos arquivos de saída nem no log.

### 3. Configuração (`config.yaml`)

O `config.yaml` da raiz é um exemplo pronto. Para outra pesquisa, copie e edite:

```bash
cp config.yaml minha_pesquisa.yaml
```

Os campos mais usados:

```yaml
query: '"machine learning" AND agriculture'   # aspas = frase exata; AND / OR em maiúsculas; parênteses
bases_ativas: [openalex, crossref, pubmed, europepmc, core, doaj, arxiv, semantic_scholar]
max_artigos_por_base: 100                      # vale para cada base, não para o total

filtros:
  ano_de: 2020                                 # null = sem limite
  ano_ate: 2025
  tipos: [artigo, revisao]                     # artigo, revisao, preprint, conferencia, livro_capitulo; [] = todos
  idiomas: [en, pt]                            # códigos de duas letras; [] = todos
  somente_oa: false                            # true = só acesso aberto
  campo_busca: titulo_resumo                   # tudo | titulo | titulo_resumo

saida:
  diretorio: saida                             # onde criar a pasta de cada execução
```

Filtros que uma base não comporta fazem essa base ser pulada, com o motivo no relatório: com o exemplo acima (`tipos: [artigo, revisao]`), o arXiv é pulado porque só tem preprints, e o DOAJ seria pulado se `tipos` não incluísse `artigo`.

As demais opções (enriquecimento, cache, limites de taxa por base) estão comentadas no próprio `config.yaml` e descritas na seção 5.1 do [ESCOPO.md](ESCOPO.md). Uma chave escrita errada, uma base inexistente ou uma consulta com aspas ou parênteses sem fechar fazem o programa parar antes de começar, com a mensagem do erro.

### 4. Executar

Com o ambiente ativado (`source .venv/bin/activate`), na pasta do projeto:

```bash
python -m coletor --config minha_pesquisa.yaml
```

Sem `--config`, é usado o `config.yaml` da pasta atual. Também dá para passar um arquivo em qualquer lugar: `python -m coletor --config /caminho/para/outra.yaml`.

Argumentos de linha de comando sobrescrevem o arquivo, sem editá-lo:

```bash
python -m coletor --config minha_pesquisa.yaml --query "deep learning" --max 50 --bases openalex,arxiv
python -m coletor --config minha_pesquisa.yaml --sem-raw-json     # CSVs sem a coluna raw_json (bem menores)
python -m coletor --listar-bases --config minha_pesquisa.yaml     # bases ativas e credenciais detectadas
```

O progresso aparece no terminal. Ao final, é impressa a pasta criada, por exemplo `saida/2026-10-31_143252_machine-learning-and-agriculture/`, com:

| Arquivo | Conteúdo |
|---|---|
| `<base>.csv` | um por base ativa (só o cabeçalho se a base falhou ou foi pulada) |
| `consolidado.csv` | todas as bases, uma linha por artigo, sem duplicatas (seção abaixo) |
| `relatorio.md` / `relatorio.json` | resumo da execução: status de cada base, artigos gravados, filtros aplicados, limites de taxa, duplicatas removidas |
| `execucao.log` | log completo |
| `config_usada.yaml` | configuração efetiva da execução (já com as sobrescritas da linha de comando) |

Código de saída: `0` se ao menos uma base trouxe resultados; `1` se todas falharam ou foram puladas; `2` erro de configuração. Uma base que falha não interrompe as outras. As respostas das APIs ficam em cache por 24 h em `.cache/http/`, então repetir a mesma consulta no mesmo dia é rápido e não gasta cota.

## CSV consolidado (`consolidado.csv`)

Cada execução grava, na pasta `saida/AAAA-MM-DD_HHMMSS_<consulta>/`, um CSV por base e o `consolidado.csv`, que junta todas as bases:

- **Uma linha por artigo.** Registros do mesmo artigo vindos de bases diferentes (ou repetidos dentro de uma base) são fundidos numa só linha. São considerados o mesmo artigo quando compartilham DOI, PMID, PMCID ou ID arXiv, ou quando têm o mesmo título (com 5 palavras ou mais, ignorando maiúsculas, acentos e pontuação) e o mesmo ano.
- **Só artigos com DOI e resumo.** O filtro é aplicado depois da fusão: basta o DOI vir de uma base e o resumo de outra.
- **Valor único** (título, autores, ano…): vem da primeira base que o tiver, na ordem Crossref > OpenAlex > PubMed > Europe PMC > Semantic Scholar > DOAJ > CORE > arXiv. O resumo segue outra ordem: PubMed > Europe PMC > OpenAlex > Semantic Scholar > DOAJ > CORE > arXiv > Crossref.
- **Formato:** UTF-8 com BOM, separador vírgula e todos os campos entre aspas. Listas ficam numa célula, com os itens separados por ` | `; célula vazia significa que nenhuma base informou o dado.

| Coluna | Descrição | Exemplo |
|---|---|---|
| `doi` | DOI do artigo, em minúsculas e sem o prefixo `https://doi.org/`. Identifica a linha: não há dois artigos com o mesmo DOI. | `10.1111/pbi.13521` |
| `bases` | Bases em que o artigo foi encontrado, na ordem de `bases_ativas` do `config.yaml`. | `openalex \| pubmed` |
| `ids_por_base` | Identificador do artigo em cada base, no formato `base:id`. Permite localizar a linha correspondente no CSV de cada base (coluna `id_na_base`). | `openalex:W3108234955 \| pubmed:33289294` |
| `titulo` | Título do artigo. | `Machine learning in agriculture: from silos to marketplaces` |
| `autores` | Nomes dos autores, na ordem da publicação, conforme a base escolhida pela prioridade (o formato do nome varia entre bases). | `Philipp E. Bayer \| David Edwards` |
| `ano` | Ano de publicação. | `2020` |
| `data_publicacao` | Data de publicação em formato ISO, com a precisão que a base informa: `AAAA-MM-DD`, `AAAA-MM` ou `AAAA`. | `2020-12-02` |
| `tipo` | Tipo do documento. Quando reconhecido, vem num dos valores padronizados `artigo`, `revisao`, `preprint`, `conferencia` ou `livro_capitulo`; senão, o valor original da base (ex.: `dissertation`, `editorial`). | `artigo` |
| `idioma` | Idioma do artigo, em código ISO 639-1 (duas letras). | `en` |
| `resumo` | Resumo (*abstract*) em texto plano, sem marcação HTML/XML. Resumos estruturados do PubMed mantêm os rótulos (`BACKGROUND: …`), um por linha. | `The increasing global population combined with climate change present a major challenge for agriculture. …` |
| `palavras_chave` | Palavras-chave informadas pelos autores ou pela base, reunidas de todas as bases, sem repetição (sem diferenciar maiúsculas). | `machine learning \| agriculture \| data markets \| precision agriculture` |
| `assuntos` | Áreas e categorias atribuídas pelas bases (tópicos do OpenAlex, descritores MeSH do PubMed/Europe PMC, categorias do arXiv, áreas do Semantic Scholar, assuntos do DOAJ), reunidas sem repetição. | `Smart Agriculture and AI \| Agriculture` |
| `url_pdf` | Link para o PDF em acesso aberto, quando alguma base o informa. | `https://onlinelibrary.wiley.com/doi/pdfdirect/10.1111/pbi.13521` |
| `n_citacoes` | Número de citações recebidas: o maior valor entre as bases (cada base conta citações de um jeito; o OpenCitations é usado nas que não informam). | `35` |
| `n_referencias` | Quantidade de referências (obras citadas pelo artigo) informada pelas bases: o maior valor entre elas. Pode ser diferente do número de itens em `referencias` (ver abaixo). | `10` |
| `referencias` | Obras citadas pelo artigo, reunidas de todas as bases. Cada item é um DOI ou, sem DOI, um identificador com prefixo: `pmid:` (PubMed), `pmcid:` (PubMed Central), `s2:` (Semantic Scholar), `openalex:` (OpenAlex) ou `omid:` (OpenCitations). | `10.1111/pbi.12467 \| 10.1111/nph.14702 \| pmid:26360509` |

Os exemplos são da linha `10.1111/pbi.13521` de uma execução real com a consulta `"machine learning" AND agriculture`.

**Limitação de `referencias`:** a lista é a união das listas de cada base, e as bases identificam a mesma obra de formas diferentes (o OpenAlex por DOI, o PubMed por PMID). Uma mesma obra citada pode, portanto, aparecer duas vezes: uma como DOI e outra como `pmid:…`. No exemplo acima, as duas bases informam 10 referências cada: o OpenAlex lista as 10 como DOI e o PubMed lista 8 identificadores (como `pmid:…`); a união tem 17 itens, embora o artigo tenha 10 referências. Por isso `n_referencias` (10) é a contagem mais confiável.

Os demais dados de cada artigo (afiliações, ORCID, periódico, ISSN, editora, volume, páginas, TLDR, FWCI, licença, acesso aberto, texto completo, financiadores, colunas exclusivas de cada base, resposta original da API etc.) continuam nos CSVs por base.
