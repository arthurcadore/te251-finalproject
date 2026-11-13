# Análise de perigos (STPA) assistida por LLM

**Data:** 13/11/2026. **Forma:** rascunho gerado com apoio de LLM (Claude Code) a partir do código e da documentação do repositório. **Revisão humana:** pendente (ver seção 8).

STPA (*System-Theoretic Process Analysis*) trata perigos como falhas de controle: alguém, humano ou software, emite uma ação de controle insegura, ou deixa de emitir uma necessária. A análise segue os quatro passos do método: (1) perdas e perigos, (2) estrutura de controle, (3) ações de controle inseguras e (4) cenários causais.

## 1. Escopo do sistema

O sistema é o coletor com triagem LLM, como roda pela interface web: a consulta é enviada a até 8 APIs acadêmicas, os resultados são consolidados em `consolidado.csv`, cada artigo é classificado por um LLM local (Ollama) e o resultado é gravado em `ranking.csv`, que o pesquisador usa para escolher o que ler.

Ficam fora do escopo a disponibilidade das APIs externas e a correção do conteúdo dos artigos.

## 2. Perdas e perigos

### Perdas (o que não pode acontecer)

| ID | Perda |
|---|---|
| L1 | A revisão bibliográfica chega a conclusões erradas: inclui artigos fora do tema ou deixa de fora artigos relevantes. |
| L2 | Vazamento de credenciais (chaves de API, e-mail de contato, token da interface). |
| L3 | Violação dos termos de uso ou bloqueio pelas APIs acadêmicas. |
| L4 | Perda de resultados de uma execução longa (busca + triagem pode levar mais de 30 min). |
| L5 | Uso do servidor por pessoa não autorizada. |

### Perigos (estados do sistema que levam às perdas)

| ID | Perigo | Perdas |
|---|---|---|
| H1 | Artigo fora do tema aparece no topo do ranking com justificativa que parece válida. | L1 |
| H2 | Artigo relevante fica fora do `consolidado.csv` ou no fim do ranking sem que o pesquisador perceba. | L1 |
| H3 | Um segredo aparece em CSV, log, relatório ou URL registrada. | L2 |
| H4 | O coletor envia requisições acima da taxa permitida por uma API. | L3 |
| H5 | A execução termina sem saída utilizável, ou com saída parcial apresentada como completa. | L4, L1 |
| H6 | A interface aceita acesso remoto sem autenticação. | L5, L2 |

## 3. Estrutura de controle

```
                ┌───────────────────────────┐
                │  Pesquisador (humano)     │
                └──┬─────────────────▲──────┘
   consulta, critérios,              │ ranking.csv, justificativas,
   pesos, temperatura                │ relatorio.md, tempos, grafo
                ┌──▼─────────────────┴──────┐
                │  Interface web            │◄── login com COLETOR_WEB_TOKEN
                └──┬─────────────────▲──────┘
                   │                 │ status, progresso
                ┌──▼─────────────────┴──────┐
                │  Orquestrador             │
                └──┬──────────────┬─────────┘
       requisições │              │ consolidado.csv
          ┌────────▼────────┐  ┌──▼──────────────────────┐
          │ Limitador (por  │  │ Ranking (ranking.py)    │
          │ base)           │  │  ├─ monta o prompt      │
          └────────┬────────┘  │  ├─ valida a resposta   │
                   │           │  └─ calcula o score     │
          ┌────────▼────────┐  └──┬───────────────▲─────┘
          │ 8 APIs externas │     │ prompt        │ JSON
          └─────────────────┘  ┌──▼───────────────┴─────┐
                               │ LLM local (Ollama)     │
                               └────────────────────────┘
```

Os controladores relevantes são o pesquisador, a interface, o limitador, o consolidador, o validador de respostas do ranking e o próprio LLM, que "controla" a classificação de cada artigo.

## 4. Ações de controle inseguras (UCA)

| ID | Ação de controle | Tipo de falha | UCA | Perigo |
|---|---|---|---|---|
| UCA1 | LLM atribui `match` | Fornecida causando perigo | LLM atribui `match = 1` a artigo fora do tema. | H1 |
| UCA2 | LLM atribui `match` | Fornecida causando perigo | LLM atribui `match = 0` a artigo relevante. | H2 |
| UCA3 | LLM devolve justificativa e citação | Fornecida causando perigo | Citação existe no resumo, mas não sustenta o critério alegado. | H1 |
| UCA4 | Validador aceita a resposta | Fornecida causando perigo | Validador aceita resposta com valor fora de {0; 0,5; 1} ou citação inventada. | H1 |
| UCA5 | Consolidador descarta registro | Fornecida causando perigo | Artigo relevante sem DOI ou sem resumo é descartado. | H2 |
| UCA6 | Limitador envia requisição | Cedo demais / rápido demais | Requisições continuam no ritmo inicial depois de um HTTP 429. | H4 |
| UCA7 | Orquestrador grava saídas | Fornecida causando perigo | URL com `api_key` ou `mailto` gravada em log ou CSV. | H3 |
| UCA8 | Orquestrador encerra a busca | Interrompida cedo demais | Prazo global atinge as bases e o resultado parcial não é sinalizado. | H5 |
| UCA9 | Interface concede acesso | Fornecida causando perigo | Cliente remoto acessa sem token válido. | H6 |
| UCA10 | Pesquisador usa o ranking | Fornecida causando perigo | Pesquisador aceita o topo do ranking sem ler as justificativas. | H1 |

## 5. Cenários causais e controles existentes

| UCA | Cenário causal | Controle existente (onde) | Teste | Situação |
|---|---|---|---|---|
| UCA4 | Modelo devolve `match = 0.7` ou campo extra | JSON Schema com `enum [0, 0.5, 1]` em `format=` do Ollama; `field_validator` e `extra="forbid"` no Pydantic (`coletor/ranking.py`, classe `Screening`) | `test_match_aceita_apenas_as_tres_classes` | **Controlado** |
| UCA4 | Modelo inventa a citação | Comparação exata `quote in abstract`; citação vazia é rejeitada (`screen`) | `test_screen_rejeita_citacao_que_nao_existe_no_resumo` | **Controlado** |
| UCA4 | Resposta cortada no meio do JSON | `done_reason == "length"` → erro; teto de 1.024 tokens | `test_chat_rejeita_resposta_truncada` | **Controlado** |
| UCA1, UCA2 | Resumo contém instruções (*prompt injection*) | O prompt manda ignorar instruções no material; a saída é restrita pelo schema | — | **Parcial**: só instrução no prompt, sem detecção |
| UCA3 | Modelo escolhe um trecho real mas irrelevante e "racionaliza" a decisão | Nenhum: a citação prova que o trecho existe, não que sustenta a decisão | — | **Lacuna**, observada na prática (seção 6) |
| UCA1, UCA2 | Modelo pequeno ou critérios ambíguos | Critérios com procedimento de decisão em passos; temperatura limitada a [0, 1]; escolha do modelo pelo usuário | `test_gerar_ranking_rejeita_temperatura_invalida` | **Parcial**: sem medida de precisão |
| UCA5 | Artigo sem DOI ou resumo (ex.: preprint só no arXiv) | Descartes contados no relatório (`sem_doi_ou_resumo` em `consolidado.py`) | `test_filtro_doi_e_resumo_depois_da_fusao` | **Parcial**: contado, mas os artigos descartados não são listados |
| UCA2 | Falha do LLM num artigo | `llm_status = erro`, motivo em `llm_justification`, artigo vai para o fim do ranking e o lote continua | `test_falha_de_um_artigo_nao_interrompe_o_lote`, `test_falha_registra_motivo_na_justificativa` | **Controlado**, desde que o pesquisador olhe `llm_status` |
| UCA6 | API responde 429 | Taxa cai pela metade, respeita `Retry-After`, backoff com jitter, até 6 tentativas; sobe +25 % só após 20 sucessos e nunca acima da inicial (`coletor/limitador.py`) | `test_429_com_retry_after_reduz_taxa_e_repete`, `test_429_sem_retry_after_usa_backoff` | **Controlado** |
| UCA7 | Chave ou e-mail na URL registrada | `PARAMS_SENSIVEIS = {api_key, mailto, email}` removidos de URLs, textos e logs (`coletor/segredos.py`); segredos só no `.env` | `test_nenhum_segredo_nas_saidas`, `test_segredo_removido_do_raw_json`, `test_cliente_remove_segredos_da_url_e_usa_user_agent` | **Controlado** |
| UCA8 | Prazo global estoura | Base que ainda busca fica `parcial` ou `falhou` e mantém o que gravou; motivo no `relatorio.md`; checkpoint `.ranking-*.csv` na triagem | `test_base_que_falha_nao_derruba_as_outras` (não há teste específico do prazo global) | **Controlado** no relatório; a interface mostra só a contagem por base |
| UCA9 | Acesso remoto sem token | Token de 32+ caracteres, sessão HMAC em cookie HttpOnly, `compare_digest`, limite de tentativas, verificação de origem, revogação no logout (`coletor/web.py`) | `test_every_private_route_requires_remote_session`, `test_remote_login_session_logout_and_origin_validation` | **Controlado**; TLS depende do proxy reverso |
| UCA10 | Pesquisador confia no score | Justificativa com evidência visível em cada linha da interface | — | **Parcial**: depende de leitura humana |

## 6. Evidência de uma lacuna real (UCA3)

Na execução de 08/11/2026, consulta `("solar sail") AND ("asteroid system" OR "binary asteroid")`, modelo `qwen3.8:27b-mtp-bf16`, os cinco primeiros colocados tratavam de asteroides mas **não** de velas solares. Exemplos:

- "Soluble organic molecules in samples of the carbonaceous asteroid (162173) Ryugu", com score 0,975.
- "The variety and origin of materials accreted by Bennu's parent asteroid", com score 0,964.

As justificativas afirmavam *"The paper explicitly studies solar sail attitude control methods (I1)"*. As citações passaram na validação porque eram trechos reais dos resumos, mas não sustentavam a decisão.

Na execução de 07/11/2026 (`SAR AND Agriculture`), com critérios que trazem um procedimento de decisão explícito, os cinco primeiros colocados estavam dentro do tema. A comparação sugere que a qualidade dos critérios pesa muito, mas duas execuções não bastam para concluir.

## 7. Requisitos de segurança derivados

| ID | Requisito | Origem | Situação |
|---|---|---|---|
| SR1 | A aderência só pode assumir 0; 0,5 ou 1, com garantia no código. | UCA4 | Implementado |
| SR2 | Toda decisão do LLM traz um trecho que existe literalmente no resumo. | UCA4 | Implementado |
| SR3 | Resposta inválida nunca vira score; o artigo fica marcado como `erro` e o lote continua. | UCA2, UCA4 | Implementado |
| SR4 | A taxa de requisições cai após 429 e nunca excede a taxa inicial configurada. | UCA6 | Implementado |
| SR5 | Nenhum segredo em CSV, log, relatório ou URL registrada. | UCA7 | Implementado |
| SR6 | Acesso remoto exige token forte e sessão válida. | UCA9 | Implementado |
| SR7 | Resultado parcial é sempre sinalizado como `parcial` ou `falhou`, com motivo. | UCA8 | Implementado no relatório |
| SR8 | A justificativa precisa ser compatível com a citação e com o critério alegado (verificador semântico ou segundo modelo). | UCA3 | **Não implementado** |
| SR9 | A precisão da triagem deve ser medida contra rotulação manual antes de usar o ranking para excluir artigos. | UCA1, UCA2, UCA10 | **Não implementado** |
| SR10 | Os artigos descartados por falta de DOI ou resumo devem poder ser listados. | UCA5 | **Não implementado** (só a contagem) |
| SR11 | Detecção de instruções suspeitas no resumo antes da classificação. | UCA1, UCA2 | **Não implementado** |

**Conclusão:** os controles que restringem o *formato* da resposta do LLM (SR1 a SR3) e os controles de operação (SR4 a SR7) estão implementados e testados. O risco principal que resta é o de *conteúdo* (SR8 a SR11): uma resposta bem formatada e com citação real pode estar errada. Por isso o ranking deve ser tratado como triagem assistida, e não como decisão final.

## 8. Revisão humana

| Item | Revisor | Data | Aceito / ajustes |
|---|---|---|---|
| Perdas e perigos (seção 2) | | | |
| Estrutura de controle (seção 3) | | | |
| UCAs e cenários (seções 4 e 5) | | | |
| Requisitos derivados (seção 7) | | | |
