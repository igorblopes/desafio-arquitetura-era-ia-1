# Checkpoint do Passo 11 (entrada do Passo 12)

| Item | Estado |
|---|---|
| Aplicação | `main`, desacoplada, síncrona; app pede só capacidades lógicas, limita o prazo e loga quando foi atendida por fallback |
| Gateway | LiteLLM Proxy `v1.102.1`; `gateway/config.yaml` com 10 grupos (4 capacidades, 4 `-equivalent`, 2 `-degraded`) |
| Primários | F1 e F4 `gpt-fake-large`; F2 e F3 `claude-fake-large` |
| Equivalentes | F1 e F4 `claude-fake-large`; F2 e F3 `gpt-fake-large` |
| Mini autorizado | F1 `gpt-fake-mini` (1.000/1.000 iguais, cliente esperando); F2 `claude-fake-mini` (revisão humana) |
| Mini rejeitado | F3 (agregado para decisão, pode reprocessar); F4 (pedido errado em 150/1.000, `product` nulo em 192/1.000, automação sem revisão) |
| Ordem | primário → equivalente → mini (se aceito); `max_fallbacks: 2`; sem ciclo |
| Tentativas por destino | primário 2 em `500`/`503`, 1 em `429`/timeout/4xx; equivalente 1; mini 1. Máximo: F1/F2 4, F3/F4 3 |
| Timeouts por tentativa | F1 3/3/2 s; F4 3/3 s; F2 20/20/5 s; F3 12/12 s |
| Backoff | nativo, 0,5 s × 2ⁿ + jitter 0–0,75 s, pausa também depois da última tentativa; só no primário |
| Deadlines da app | F1 14 s, F4 14 s, F2 25 s, F3 25 s por lote (era 14) |
| Erros | `503` timeout, rate limit, indisponível; `502` recusado; fallback em qualquer erro do provider (inclusive `400` na F1/F4, limitação) |
| Experimentos | `docs/fallback/evidencias/00`–`16`; nenhum `504` da borda |
| Destaques | técnico `500`: F1 2,8 s, F4 3,6 s, F2 18,1 s, F3 12,4 s; F1 travada 4,1 s; dois large fora: F1/F2 `200` pelo mini, F3/F4 `503` sem mini; tudo fora: `503` em ~2 s com 4/3 chamadas |
| Amplificação | declarado = observado em todos os destinos |
| Custo | técnico −33% (F2) a +44% (F4); mini da F2 US$ 0,0011 contra 0,0091; órfão da F2 lenta US$ 0,0061 pago sem entregar |
| Testes | `tests/fallback` 40, `tests/resilience` 34 (revisados), `tests/characterization` 32 (intacta), `tests/metrics` 64 |
| Métricas | `docs/fallback/metricas/fallback-step-11.csv`, igual ao Passo 10 |
| ADRs | [0006](../adr/0006-fallback-policy.md) novo; [0005](../adr/0005-resilience-policy.md) com seção de revisão |
| Commits | partida `062b25f` (Passo 10); tags `v1-coupled` `8028305` e `v2-decoupled` `b637c5a` intactas |

## Para o Passo 12 (governança)
1. Declarar preço dos 4 modelos no gateway: hoje `x-litellm-response-cost` é 0 e nenhum orçamento estoura.
2. Chaves virtuais com só as 4 capacidades; grupos internos deixam de ser chamáveis diretamente. Manter `enforce_fallback_model_access` falso, senão o fallback interno é bloqueado.
3. Provar que recusa por orçamento e `429` do gateway acontecem antes do router e não disparam fallback nem retry.
4. Contabilizar cada tentativa e cada salto por chave (headers `x-litellm-attempted-*`, `x-litellm-model-group`).

## Limitações e pendências
1. Sem deadline por requisição no LiteLLM: cadeias órfãs (F2 travada chega ao mini ~40 s depois).
2. F2 travada: `503` aos 25 s, fallback não cabe no síncrono (Passo 14: timeout de primeiro token).
3. F3 mês continua passando da borda (Passo 15: job com deadline de 60 s, `failed` visível).
4. Fallback em `400` na F1/F4; timeout não cancela geração; degradação não aparece no JSON.
5. Mesmo container para os dois providers; gateway é SPOF.
6. `docs/v2/verificacao_v2.py` desatualizado (espera `500`, não sabe de fallback).

## Conhecimentos
Ver [relatório](relatorio-fallback.md) e [glossário](glossario.md). As perguntas de fixação foram enviadas ao final da execução contínua.
