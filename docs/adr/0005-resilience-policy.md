# 0005. Limitar a espera e repetir uma única vez, no gateway

- Status: aceita; tentativas por destino e prazo da F3 revisados pelo [ADR 0006](0006-fallback-policy.md) (Passo 11)
- Data: 2026-11-27
- Nível: solução

## Contexto

Na `v2-decoupled` nenhuma política de resiliência tinha sido decidida. Medido antes da mudança (`docs/resiliencia/evidencias/antes-*`):

| Fato | Número |
|---|---|
| Timeout efetivo | só o da borda (30 s). App: SDK com 600 s. Gateway: padrão do LiteLLM (6000 s) |
| Provider travado | F1 e F2: `504` do nginx aos 30 s, com a chamada ainda aberta no provider |
| Falha imediata (`500`/`429`) | 3 tentativas no provider, `500` genérico em 4,5 a 4,9 s (`500`) e 6,4 a 7,3 s (`429`) |
| Latência normal | F1 1,1 s; F4 1,25 s; F3 9,85 s por lote; F2 16 s (máximo calculado nos 5.000 tickets: 16,2 s) |
| Custo | `claude-fake-large` US$ 3/15 e `gpt-fake-large` US$ 2,50/10 por milhão de tokens |
| Cancelamento | o provider continua gerando depois que o gateway desiste (chamada de 10,75 s concluída após corte em 3 s) |

## Opções consideradas

1. **Tudo na aplicação.** Timeout, retry e backoff no adapter. A app conhece o negócio, mas o fallback do Passo 11 vive no gateway: haveria duas camadas decidindo tentativas.
2. **Tudo no gateway.** Um só lugar, mas se o gateway travar a app volta a esperar 600 s.
3. **Distribuída.** Gateway: timeout por tentativa, classificação para retry, backoff e limite de tentativas. App: limite externo de espera por chamada e tradução do erro.

## Decisão

Opção 3.

| Capacidade | Timeout por tentativa | Retries adicionais | Tentativas totais | Retry em timeout? | Pior caso no gateway | Limite da app |
|---|---|---|---|---|---|---|
| `ticket-classification` (F1) | 3 s | 1 | 2 | sim | 9,0 s | 14 s |
| `order-extraction` (F4) | 3 s | 1 | 2 | sim | 9,0 s | 14 s |
| `topics-report` (F3, por lote) | 12 s | 1 | 2 | não | 12 s (timeout); 15 s no caso `500` seguido de travamento | 14 s |
| `reply-suggestion` (F2) | 20 s | 1 | 2 | não | 20 s (timeout); 23 s no caso `500` seguido de travamento | 25 s |

**Conta da F1/F4:** 3 s + pausa (0,5 a 1,25 s) + 3 s + pausa final (1,0 a 1,75 s) = 7,5 a 9,0 s. Sobram 5 s até o limite de 14 s para o fallback do Passo 11.

**Por que os timeouts diferem:** a latência do modelo é `0,8 s + tokens_de_saída / 40`. Um valor único ou cortaria a F2 (16 s) ou deixaria a F1 esperar 18 vezes o normal.

| Erro | Repete? | Motivo | Resposta final |
|---|---|---|---|
| timeout da tentativa | só F1 e F4 | em F2 e F3 uma segunda geração longa não cabe no prazo e dobra o custo | `503 model_timeout` |
| `429` | 1 vez, após `Retry-After` + jitter | recusa temporária | `503 model_rate_limited` |
| `500`, `503` | 1 vez | possivelmente transitório | `503 model_unavailable` |
| conexão, `502` | 1 vez (`num_retries`) | possivelmente transitório | `503 model_unavailable` |
| `400`, contexto excedido, política de conteúdo | não | o mesmo pedido falha de novo | `502 model_rejected` |
| `401`, `403`, `404` | não | configuração ou credencial | `502 model_rejected` |
| limite da app esgotado | não | sem orçamento | `503 model_timeout` |

- **Backoff:** o nativo do LiteLLM `v1.102.1`: `0,5 s × 2ⁿ` (teto 8 s) mais jitter aditivo de 0 a 0,75 s. Não há algoritmo próprio.
- **Jitter:** mantido porque é nativo. Não é *full jitter*.
- **Retry-After:** o gateway usa o valor se estiver entre 1 e 60 s; fora disso, usa o backoff exponencial.
- **Amplificação:** o SDK da app continua com `max_retries=0`; o router do LiteLLM zera o retry do SDK do provider; `num_retries: 1`.
- **Cooldown:** `disable_cooldowns: true`. Circuit breaker está fora do escopo.
- **Status HTTP:** `503` quando vale tentar depois, `502` quando precisa de correção. O `504` fica exclusivo da borda, o que torna as duas origens distinguíveis.
- **Contrato:** `ports.LanguageModelError(capability, reason)`, sem tipos do SDK. A tradução para HTTP fica em `main.py`.

## Consequências

**Melhora**
- Nenhum experimento produziu `504` da borda; a F1 travada responde em 8,6 s (antes: `504` aos 30 s).
- Falha imediata: 2 chamadas em vez de 3, resposta em 2,2 a 2,7 s (`500`) e 4,3 a 5,3 s (`429`).
- Falha que passa entre duas tentativas é recuperada (4 de 4 cenários).
- O consumidor recebe um erro estável (`detail`, `code`) sem detalhes internos.

**Piora ou custo**
- `slow` na F1 e F4 virou erro: antes `200` em 10,8 a 12,3 s, agora `503` em 8,0 a 8,4 s, com **duas** gerações concluídas no provider e descartadas. É a troca por prazo curto; o fallback do Passo 11 é quem deve devolver disponibilidade.
- Status de falha mudou de `500` para `503`/`502` (o contrato de sucesso e o OpenAPI não mudaram). O verificador do Passo 09 (`verificacao_v2.py`) agora reprova 4 cenários só por esperar `500`.
- `ports` ganhou uma classe concreta: A 1,00 → 0,50, D 0,00 → 0,50; aresta nova `main -> ports` (19 → 20).

**Limitações e riscos**
- A F2 travada leva 20 s para falhar: o critério de 15 s não é atendido por ela enquanto for síncrona, porque a resposta normal já leva 16 s. Revisitar com o streaming (Passo 14).
- A F3 não tem limite para o relatório inteiro, só por lote. O mês continua passando da borda e rodando órfão (Passo 15). Um lote que falha descarta os anteriores.
- Timeout não cancela a geração remota; o custo dessas chamadas é indeterminado.
- `Retry-After` alto (por exemplo 30 s) faria o gateway tentar de novo depois que a app já desistiu. O provider-fake envia 2 s; o caso não foi testado.
- O limite da app é o timeout de leitura do HTTPX. Vale como limite total porque a resposta não é transmitida em partes; com streaming deixa de valer.
- A política de retry é escolhida pelo **primeiro** erro (lido no código do router, não testado isoladamente).
- O LiteLLM dorme também depois da última tentativa (até 1,75 s, ou o `Retry-After`).
- Com o container do gateway parado, a app levou 7,9 s para responder `503`: o limite de conexão de 2 s não cobriu esse caso (causa provável, não verificada: resolução de nome).

**Para o Passo 11:** o fallback deve entrar no gateway, sem retry próprio acima de 1, e caber no que sobra de 14 s na F1/F4 (cerca de 5 s, uma tentativa de 3 s). F2 e F3 não têm folga no modo síncrono.

## Evidência

```bash
docker compose up -d --build --wait
python docs/resiliencia/sondas_resiliencia.py error_500        # 2 tentativas por feature
python docs/resiliencia/sondas_resiliencia.py timeout --espera 3
pytest tests/resilience -v                                     # 34 passed
```

Registros em `docs/resiliencia/evidencias/`; análise em [`docs/resiliencia/relatorio-resiliencia.md`](../resiliencia/relatorio-resiliencia.md).

## Revisão no Passo 11 (2026-11-27)

O texto acima é o registro da decisão do Passo 10 e fica como estava. Com o fallback do [ADR 0006](0006-fallback-policy.md), os valores abaixo mudaram. O dono das tentativas continua sendo o gateway, e a app continua com `max_retries=0`.

| Item | Passo 10 | Passo 11 | Motivo operacional |
|---|---|---|---|
| Retry em timeout, F1 e F4 | 1 | 0 no primário | com o primário travado, repetir custava 3 s + pausas (9,6 s medidos até o fallback); migrar leva 4,1 s e deixa prazo para o mini |
| Retry em `429` | 1, após `Retry-After` | 0 no primário | esperar o provider saturado custava 6,1 s; o equivalente responde na hora (1,1 s) |
| Retry em `500`/`503` | 1 | 1 no primário | falha imediata pode ser transitória; custa no máximo 3,0 s de pausas |
| Destinos de fallback | não existiam | 1 tentativa, qualquer erro (`DefaultRetries: 0`) | o primário já absorveu o transitório; cada salto troca de domínio |
| Prazo da app, F3 (por lote) | 14 s | 25 s | precisa caber "primário travado (12 s) + equivalente (~9,9 s)" = 21,9 s medidos; continua abaixo dos 30 s da borda |
| Prazo da app, F1/F4/F2 | 14 / 14 / 25 s | sem mudança | F1/F4: cadeia inteira no pior caso = 11 / 9 s |
| Máximo de chamadas por operação de modelo | 2 | F1/F2: 4; F3/F4: 3 | soma das tentativas por destino |
| Interação retry × fallback | — | o retry é escolhido pela política do **grupo** de cada destino; o fallback não reinicia o prazo da app (uma só chamada HTTP) | lido em `router.py` do LiteLLM 1.102.1 e confirmado no `/admin/calls` |

Consequências da revisão:
- O backoff com `Retry-After` deixou de ser exercitado: o teste correspondente virou "429 migra sem esperar" (`tests/resilience/test_backoff.py`).
- Os testes do Passo 10 que esperavam `503` com o primário em falha agora põem os dois providers inteiros em falha para isolar o mecanismo; a intenção (limite de tentativas, prazo, erro explícito) foi mantida.
- Limitação 4 (`Retry-After` alto) deixou de valer para o primário; os destinos de fallback não repetem.
- Nova limitação: o gateway não tem deadline por requisição, então uma cadeia continua depois que a app desiste (cadeia órfã, ADR 0006).

## Revisão no Passo 12 (2026-11-28)

Com a governança do [ADR 0010](0010-gateway-governance.md), a classificação de erros ganhou a origem **gateway**:

| Erro | Origem | Retry | Fallback | App |
|---|---|---|---|---|
| `500`/`503`, timeout, `429` do provider | provider | como na revisão do Passo 11 | sim (ADR 0006) | `503 model_unavailable` / `model_timeout` / `model_rate_limited` |
| `429 budget_exceeded` | gateway | não | não | `503 model_budget_exceeded` |
| `429 throttling_error` "Rate limit exceeded for…" | gateway | não | não | `503 model_throttled` + `Retry-After` |
| `401`/`403` | gateway | não | não | `502 model_rejected` |

- Ninguém repete recusa de governança: elas acontecem antes do router (onde moram retry e fallback) e a app continua com `max_retries=0`. Evidência: `/admin/calls` sem nenhuma chamada nova com o primário e a cadeia inteira em `500` (`docs/governanca/evidencias/04` e `07`).
- O status sozinho não basta: o `429` do limitador do gateway e o `429` de um provider ao fim da cadeia têm o mesmo status e o mesmo `type`. O adapter decide pelo `type` e pelo início da mensagem (`tests/governance/test_governance_resilience.py`).
- Contabilização das tentativas: tentativa que falhou sem `usage` custa 0 no gateway; o RPM conta a requisição lógica (1), não as tentativas físicas (até 4).
