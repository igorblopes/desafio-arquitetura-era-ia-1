# Handoff: fallback técnico e degradado (Passo 11)

Handoff entregue ao agente de implementação. As decisões de produto (quem aceita mini) foram tomadas antes, com evidência, e **não** são do agente.

## Contexto
- App desacoplada (`v2-decoupled` + Passo 10): features pedem capacidades lógicas por `ports.LanguageModel`; adapter único para o gateway; `max_retries=0` no SDK da app.
- Gateway: LiteLLM Proxy `v1.102.1`, `gateway/config.yaml`. Um destino large por capacidade, timeout por tentativa, 1 retry, backoff nativo, `disable_cooldowns`.
- Capacidades: `ticket-classification` (GPT L), `reply-suggestion` (Claude L), `topics-report` (Claude L, por lote), `order-extraction` (GPT L).
- Prazos da app: 14 / 25 / 14 / 14 s; borda 30 s.
- Evidência: large ≡ large em 100% dos casos; mini ≡ large na F1 (1.000/1.000) e na F3 (17/17); mini da F2 com ~44% do texto; mini da F4 com `product: null` (192/1.000) e pedido errado (150/1.000).
- Decisão de produto: mini aceito só na F1 (`gpt-fake-mini`) e na F2 (`claude-fake-mini`).

## Tarefa
1. Fallback técnico nas 4 capacidades: large de outro provider.
2. Mini só na F1 e na F2, depois do equivalente.
3. Respeitar o deadline global (a chamada única da app ao gateway) e os limites por destino; nenhum ciclo; nenhuma amplificação.
4. Falha explícita (`503`) quando a cadeia esgota.

## Escopo autorizado
`gateway/`, `app/helpdesk/adapters/gateway.py`, `app/helpdesk/config.py`, tratamento de erros, `tests/fallback/`, `tests/resilience/` (expectativas), ADRs, README.

## Restrições
Não alterar contratos de sucesso, tags, `provider-fake/`, `edge/`, `data/`, `tests/characterization/`; sem providers reais, integrações diretas, governança, streaming, assíncrono, circuit breaker ou cache; nenhum nome físico em `app/`.

## Plano apresentado e revisado
1. F1: grupo `ticket-classification-equivalent` (Claude L) + `fallbacks`; validar com `error_500` no GPT L.
2. Medir timeout e `429` com a política do Passo 10 (9,6 s e 6,1 s) e revisar: primário sem retry em timeout e `429`; destinos internos com 1 tentativa.
3. Replicar para F4, F2, F3; validar as quatro.
4. Grupos `-degraded` só para F1 e F2; validar os dois large fora.
5. Prazo da F3 por lote para 25 s, para caber primário travado + equivalente.
6. Log do destino servido no adapter (headers do gateway), sem mudar o contrato.

Pontos questionados na revisão: o mini da F3 empatou nas amostras, mas foi recusado por decisão de negócio (custo de esperar baixo, erro num agregado silencioso); `context_window_fallbacks` só funciona quando o LiteLLM reconhece a mensagem, o que foi testado e documentado em vez de assumido.
