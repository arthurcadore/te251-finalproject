# Engenharia de requisitos assistida por LLM

Este documento descreve como os requisitos do Coletor multibase de artigos científicos foram refinados com um agente de LLM, com revisão humana. Toda afirmação aponta para um arquivo do repositório. O que o repositório não comprova está marcado na seção 6.

## 1. Artefatos envolvidos

| Artefato | Papel |
|---|---|
| [`ESCOPO.md`](../ESCOPO.md) | Especificação fechada: bases, colunas do CSV, filtros, limites de taxa, critérios de aceite (seção 12). É o documento de requisitos. |
| [`CLAUDE.md`](../CLAUDE.md) | Instruções para o agente de código (Claude Code): como trabalhar, em que ordem e quando parar e perguntar. Faz o papel de um `AGENTS.md`. |
| [`scripts/teste_pratico.py`](../scripts/teste_pratico.py) | Script que chama cada API de verdade, com o limitador de taxa, e grava as respostas. |
| [`tests/fixtures/`](../tests/fixtures/) | Respostas reais das APIs, sem segredos. São a evidência usada para escrever o mapeamento de cada base. |
| [`docs/relatorio_teste_pratico.md`](relatorio_teste_pratico.md) | Relatório do teste prático: campos retornados, filtros que funcionaram, limites observados. |
| `ESCOPO.md`, seção 15 | Registro das mudanças nos requisitos feitas depois do teste prático, separando decisões automáticas e decisões do usuário. |

## 2. Regras dadas ao LLM

O `CLAUDE.md` restringe o que o agente pode fazer com os requisitos:

- **Escopo fechado.** Nada de bases, funcionalidades, dependências pesadas ou banco de dados fora do `ESCOPO.md`.
- **Nada inventado.** "Nunca invente campos de API: o mapeamento de cada base deve ser escrito a partir das respostas reais gravadas em `tests/fixtures/`."
- **Mudança só com regra ou com o usuário.** Se algo no escopo estiver errado na prática, o agente aplica as regras de decisão da seção 11 do `ESCOPO.md`. Para qualquer caso não coberto, ele para e pergunta, explicando o problema e propondo opções.
- **Lista explícita de quando parar** (seção "Quando parar e perguntar"): API que mudou, filtro sem suporte, credencial obrigatória inesperada, ou qualquer decisão que altere colunas, filtros ou a lista de bases.
- **Fases com aprovação.** Ao fim de cada fase, o agente mostra um resumo do que mudou em relação ao escopo e espera confirmação.

## 3. Ciclo de refinamento

```
ESCOPO.md (requisito inicial)
      │
      ▼
Teste prático: chamadas reais às 8 APIs ─────► tests/fixtures/ + relatorio_teste_pratico.md
      │
      ▼
LLM compara requisito × evidência
      │
      ├── caso coberto pela seção 11 ──► decisão automática (ESCOPO 15.1)
      └── caso não coberto ────────────► pergunta ao usuário ──► decisão do usuário (ESCOPO 15.2)
      │
      ▼
ESCOPO.md atualizado ──► código + testes offline ──► critérios de aceite (ESCOPO 12)
```

## 4. Requisitos alterados, com evidência e decisão

| Requisito original | Evidência do teste prático | Decisão | Quem decidiu | Onde ficou |
|---|---|---|---|---|
| SciELO é uma das bases | Sem busca por palavra-chave (`q=` → 404); `robots.txt` com `Disallow: /` e 403 com desafio anti-robô | Base desabilitada, adaptador marcado como `desabilitado` | Regra automática (seção 11) | ESCOPO 15.1 |
| CORE poderia exigir chave | 0 respostas 429 em 7 chamadas anônimas | `CORE_API_KEY` continua opcional | Regra automática | ESCOPO 15.1 |
| Europe PMC a 2 req/s | 0 respostas 429 em 34 chamadas, incluindo rajada de 20 | Mantém 2 req/s | Regra automática | ESCOPO 15.1 |
| PubMed filtra conferência nativamente | `Congress[pt]` não reconhecido; a forma aceita retorna 0 resultados | Filtro passa a ser local | Regra automática | ESCOPO 15.1 |
| Europe PMC filtra idioma com ISO 639-1 | `LANG:"pt"` mistura idiomas; `LANG:"por"` retorna 5/5 | Sintaxe corrigida para ISO 639-2 | Regra automática | ESCOPO 15.1 |
| CORE fornece texto completo | Sem chave, `fullText` = "Not available for public API users." | Chave segue opcional; sem chave, coluna vazia + aviso | Usuário | ESCOPO 15.2 |
| Semantic Scholar sem chave é utilizável | 57 de 63 chamadas com 429 | Chave segue opcional; base pode terminar `parcial` | Usuário | ESCOPO 15.2 |
| PubMed ordena por relevância | Ordem padrão do `esearch` = mais recentes | Enviar `sort=relevance` | Usuário | ESCOPO 15.2 |
| CSV consolidado só na Etapa 2 | — (mudança de prioridade) | Consolidado entra nesta versão, depois reduzido de 19 para 16 colunas | Usuário | ESCOPO 15.4 |
| Score 70/15/15 (aderência, ano, citações) | — (revisão de requisito) | 70/10/10/10, com citações por ano e tipo de publicação; pesos configuráveis | Usuário | ESCOPO 16 |

Note a separação: o LLM só decide sozinho quando existe uma regra escrita **e** uma evidência gravada. Mudanças de prioridade, de colunas ou de pesos foram decisões do usuário.

## 5. Como verificar

- **Evidência bruta:** `tests/fixtures/<base>/` e `docs/relatorio_teste_pratico.md`.
- **Requisitos versus implementação:** os 220 testes offline (`.venv/bin/python -m pytest -q`, executados em 13/11/2026: 220 aprovados) usam essas fixtures. Exemplos são `tests/test_pubmed.py` e `tests/test_europepmc.py` para os filtros, e `tests/test_ranking.py` para as regras da seção 16.

## 6. Limites deste registro

- O histórico do git foi agrupado em poucos commits. Os commits por fase (`fase N: ...`) previstos no `CLAUDE.md` não aparecem, e só um commit traz `Co-Authored-By: Claude`. A atribuição de cada decisão vem do próprio `ESCOPO.md` (seções 15.1 e 15.2), não do git.
- As conversas com o agente não foram guardadas, então os prompts exatos de cada decisão não estão disponíveis.
- O repositório não registra se a **primeira versão** do `ESCOPO.md` foi escrita com apoio de LLM. **O grupo deve confirmar antes de citar isso no artigo.**
- Este documento também foi redigido com apoio de LLM em 13/11/2026, a partir dos arquivos citados, e deve ser revisado pelo grupo.
