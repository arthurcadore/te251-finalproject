# Orientações para o Claude Code

Você vai implementar o **Coletor multibase de artigos científicos**. A especificação completa e fechada está em `ESCOPO.md` — leia-a inteira antes de começar. Este arquivo diz **como** trabalhar; o `ESCOPO.md` diz **o quê** construir.

## Regras gerais

- **O escopo é fechado.** Não adicione bases, funcionalidades, dependências pesadas, interface web sem autenticação/TLS, Docker ou banco de dados que não estejam no `ESCOPO.md`. O bind web em `0.0.0.0`, protegido por token e destinado a proxy HTTPS, e o ranking local por Ollama foram autorizados pelo usuário e adicionados na seção 16. Itens da "Etapa 2" (ordenação das buscas por base, sobrescrita da consulta por base) **não** devem ser implementados. O CSV consolidado foi trazido para esta versão por decisão do usuário (ESCOPO 9.5 e 15.4).
- Se algo no escopo for impossível ou estiver errado na prática, **não improvise silenciosamente**: aplique as regras de decisão da seção 11 do `ESCOPO.md`; para qualquer caso não coberto, pare e pergunte ao usuário, explicando o problema e propondo opções.
- Ambiente-alvo: **Linux**, Python **3.11+**, ambiente virtual (`python -m venv .venv`). Sem Docker.
- Código (nomes de módulos, classes, funções) em inglês ou português, mas **consistente**; os **nomes das colunas do CSV, chaves do `config.yaml` e mensagens ao usuário seguem exatamente o `ESCOPO.md`** (português).
- Nunca invente campos de API: o mapeamento de cada base deve ser escrito a partir das respostas reais gravadas em `tests/fixtures/` no teste prático.
- Segredos só via `.env`. Nunca imprima, grave em log, CSV, `raw_json` ou relatório uma chave, token ou o e-mail em URLs (remova `api_key`, `mailto`, `email` das URLs registradas).
- Respeite os limites de cada API desde o primeiro teste: use o limitador também no script de teste prático. É uso acadêmico; identifique-se com `User-Agent: coletor-artigos/1.0 (mailto:CONTACT_EMAIL)`.

## Ordem de trabalho

Siga as fases da seção 13 do `ESCOPO.md`, **uma de cada vez**, com um commit ao final de cada fase (mensagem: `fase N: <resumo>`). Ao terminar cada fase, mostre ao usuário um resumo curto do que foi feito e do que mudou em relação ao escopo, e aguarde confirmação antes da próxima fase.

### Fase 1 — Teste prático (antes de qualquer outro código)
1. Crie `pyproject.toml`, `.venv`, `.env.example` e um limitador mínimo para o script.
2. Peça ao usuário para preencher `.env` (pelo menos `OPENALEX_API_KEY` e `CONTACT_EMAIL`) se ainda não estiver preenchido.
3. Escreva e rode `scripts/teste_pratico.py` conforme a seção 11 do `ESCOPO.md`.
4. Grave as respostas reais em `tests/fixtures/<base>/` (sem segredos).
5. Gere `docs/relatorio_teste_pratico.md` e **atualize o `ESCOPO.md`** (matriz de colunas, mapeamento de filtros e tipos, limites, colunas `x_<base>_*`, status do SciELO e do CORE) registrando as mudanças numa seção "Ajustes pós-teste prático".
6. Apresente ao usuário as decisões automáticas tomadas (SciELO, CORE, Europe PMC, filtros trocados para local) antes de seguir.

### Fase 2 — Núcleo + OpenAlex e arXiv
Config (pydantic), CLI, cliente HTTP com cache em disco, limitador adaptativo (seção 7), modelo de registro, parser/tradutor da consulta, filtros (nativo/local), gravador CSV (seção 9.2–9.3), relatório (9.4), orquestrador paralelo. Adaptadores OpenAlex e arXiv completos, com testes a partir das fixtures.

### Fase 3 — Demais bases
Semantic Scholar, Crossref, PubMed, Europe PMC, CORE, DOAJ, SciELO (ou adaptador marcado como desabilitado, conforme o teste prático). Um arquivo de teste por base.

### Fase 4 — Enriquecimento
Tabela da seção 8.1: referências nativas, conversão de IDs OpenAlex para DOI em lote, `POST /paper/batch` do Semantic Scholar, referências do Europe PMC, OpenCitations (referências e contagem de citações), texto completo (CORE e Europe PMC OA → texto plano).

### Fase 5 — Fechamento
`README.md` (instalação, `.env`, `config.yaml`, uso da CLI, descrição das colunas, limitações conhecidas, aviso do limite de 32.767 caracteres por célula no Excel). Rode uma execução real com a consulta de exemplo e verifique **cada item** dos critérios de aceite (seção 12), registrando o resultado em `docs/verificacao_aceite.md`.

### Fase 6 — Extensão autorizada: interface e ranking LLM
1. Interface HTTP vinculada a `0.0.0.0`, protegida com `COLETOR_WEB_TOKEN` para acessos remotos, para preencher parâmetros equivalentes ao YAML e critérios de triagem; formulário não carrega YAML/TXT e salva preferências no `localStorage`; credenciais continuam apenas no `.env`. TLS deve ser terminado em proxy reverso.
2. Após a busca, avaliar `consolidado.csv` com Ollama local e gerar `ranking.csv` preservando as colunas originais e acrescentando campos LLM.
3. Score: 70% aderência, 15% recência, 15% citações (com `log(1+n_citacoes)`); metadados ausentes recebem 0,5. Validar citação literal do resumo.
4. Testes offline para score, saída, falhas por artigo e endpoints da interface; atualizar README e ESCOPO seção 16.

## Padrões de implementação

- `httpx.AsyncClient` único por base (ou compartilhado com limites por host), timeouts explícitos.
- Limitador: token bucket + `asyncio.Semaphore`, taxa adaptativa (corta pela metade em 429, sobe 25% após 20 sucessos, nunca acima da inicial), retentativa com backoff exponencial + jitter, respeito a `Retry-After`. Testar com `respx` simulando 429 e 5xx.
- Escrita do CSV com `csv.writer(quoting=csv.QUOTE_ALL)`, arquivo aberto com `encoding="utf-8-sig", newline=""`. Testar ida e volta com resumos contendo vírgulas, aspas e quebras de linha.
- Uma base que falha nunca derruba o processo: capture a exceção na tarefa da base, registre status e motivo no relatório.
- Escreva o CSV por lotes conforme as páginas chegam; deduplicação dentro da base por `id_na_base` e `doi`.
- `pytest` deve rodar **offline** (fixtures + `respx`). Testes que tocam a internet ficam marcados `@pytest.mark.online` e fora da execução padrão.
- Logs com `logging`, um logger por base (`coletor.openalex` etc.), saída no console e em `execucao.log`.

## Quando parar e perguntar

- Uma API mudou e não oferece mais algo que o escopo exige.
- Um filtro escolhido pelo usuário não é suportado nem localmente por várias bases.
- Uma base exige credencial que o escopo trata como opcional.
- Qualquer decisão que altere colunas do CSV, comportamento dos filtros ou a lista de bases além das regras automáticas da seção 11.
