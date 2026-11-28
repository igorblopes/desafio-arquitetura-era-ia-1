# Checkpoint do Passo 10 (entrada do Passo 11)

| Item | Estado |
|---|---|
| Aplicação | `main`, desacoplada como a `v2-decoupled`, agora com limite de espera, retry limitado e backoff; síncrona; modelos `large` |
| Gateway | LiteLLM Proxy `v1.102.1` |
| Configuração | `gateway/config.yaml`: `timeout` por destino (F1 3 s, F4 3 s, F2 20 s, F3 12 s); `num_retries: 1`; `model_group_retry_policy`; `disable_cooldowns: true` |
| App | `config.GATEWAY_DEADLINE_SECONDS` (14/14/14/25 s), connect 2 s; adapter com `max_retries=0` |
| Erros | `ports.LanguageModelError(capability, reason)`; `main.py` traduz: `503` (`timeout`, `rate_limited`, `unavailable`), `502` (`rejected`) |
| Backoff | nativo: 0,5 s × 2ⁿ + jitter 0–0,75 s; `Retry-After` até 60 s; pausa também após a última tentativa |
| Após esgotar | erro explícito; sem fallback |
| Experimentos | `500`/`429`: 2 chamadas, 2,2–5,3 s; travado: F1 8,6 s, F4 7,6 s, F3 12,1 s, F2 20,0 s; recuperação 4/4 |
| Amplificação | máximo declarado 2, observado 2 |
| Custo | `slow` em F1/F4 gera 2 respostas descartadas; chamada abandonada de F2/F3 pode custar US$ 0,009 / 0,024 |
| Testes | `tests/resilience` 34 passed; `tests/characterization` 32 passed |
| Métricas | `docs/resiliencia/metricas/resilience-step-10.csv`: 20 arestas; `ports` D 0,50 |
| ADR | `docs/adr/0005-resilience-policy.md` |
| Commit de partida | `a8e1fda`; tags `v1-coupled` (`8028305`) e `v2-decoupled` (`b637c5a`) intactas |
| Orçamento para fallback | F1 e F4: ~5 s dentro dos 14 s; F2: ~2–5 s (insuficiente); F3: nenhum |

## Pendências e limitações

1. F2 travada não atende os 15 s no modo síncrono (Passo 14).
2. F3 sem limite para o relatório inteiro; trabalho órfão no mês (Passo 15).
3. Timeout não cancela a geração no provider.
4. `Retry-After` alto permite tentativa depois do limite da app (não testado).
5. Gateway parado: `503` em 7,9 s, acima do connect timeout de 2 s (causa não verificada).
6. Passo 11: conferir se o fallback do LiteLLM multiplica retries e respeita o timeout por destino.
7. Passo 12: recusa por orçamento ou limite do gateway não deve ser repetida; rever `RateLimitErrorRetries`.
8. `verificacao_v2.py` (Passo 09) espera `500` em 4 cenários que agora respondem `503`.

## Conhecimentos

Ver [glossário](glossario.md) e [relatório](relatorio-resiliencia.md). As perguntas de fixação das subetapas 4.1 e 4.2 ficaram sem resposta, porque a execução passou a ser contínua.
