# Checkpoint do Passo 12 (entrada do Passo 13)

| Item | Estado |
|---|---|
| Aplicação | `main`, desacoplada, resiliente e governada; síncrona nas 4 features; consome com a chave virtual `helpdesk-app` |
| Gateway | LiteLLM Proxy `v1.102.1` (`x-litellm-version`), `gateway/config.yaml` com 10 grupos e preço por destino |
| Arquitetura de governança | app → gateway (autenticação → autorização por `models` → orçamento com reserva → RPM → router com retry/fallback) → provider-fake; gasto e chaves no Postgres do gateway |
| Identidades | `helpdesk-app` (4 capacidades, US$ 20/30 d, soft 15, 600 RPM); `governance-budget-demo` (F1, US$ 0,0004 acumulado); `governance-rate-demo` (F1, US$ 1, 3 RPM); master key só no gateway e no bootstrap |
| Credenciais | valores fixos locais no `.env.example`; app recebe só `HELPDESK_GATEWAY_KEY` como `GATEWAY_API_KEY`; chaves de provider só no gateway e no provider-fake; senha do banco só no gateway e no banco |
| Preços (US$/1M in/out) | GPT L 2,50/10; Claude L 3/15; GPT m 0,15/0,60; Claude m 0,80/4 (por token no YAML); validados nos 4 modelos |
| Contabilização | custo do destino que respondeu; tentativa falha sem `usage` = 0; gasto em memória na hora, banco em lote a cada 10–15 s |
| Budget | `max_budget` por chave; recusa quando `gasto >= teto` (`429 budget_exceeded`) na autenticação; reserva o custo máximo estimado (até 16.384 tokens de saída) enquanto a requisição está em voo; ultrapassa no máximo uma chamada |
| Rate limiting | `rpm_limit` por chave; limitador v3, janela fixa de 60 s a partir da 1ª admitida, contador em memória; 1 por requisição lógica; `429 throttling_error`, `Retry-After: 60` (pessimista) |
| Infraestrutura adicional | `gateway-db` (`postgres:17.2-alpine`, volume `gateway-db-data`, sem porta no host, ADR 0007); `gateway-bootstrap` (imagem do gateway, roda e sai, ADR 0008). Sem Redis |
| Bootstrap | `gateway/scripts/bootstrap_keys.py`: readiness com `db: connected` → `key/info` → `generate` ou `update` só de política → confere → exit 0/1; app espera `service_completed_successfully`; reset só de demos: `docker compose run --rm gateway-bootstrap --reset-spend <alias>` |
| Inicialização | `cp .env.example .env && docker compose up -d --build --wait`: 28 s numa cópia limpa, 3 chaves `criada`, `/health` 200, F1/F2/F3/F4 `200` |
| Experimentos | `docs/governanca/evidencias/00`–`12`, `30`, `31` |
| `/admin/calls` | Budget 3 → 3; RPM 3 → 3; fallback × budget 0 chamadas em todos os modelos; fallback × RPM 12 → 12; autenticação 0 em todos os cenários de recusa |
| Recusas | budget `429 budget_exceeded`; RPM `429 throttling_error`; chave inválida/ausente/revogada `401`; capacidade ou grupo interno fora da chave `403 key_model_access_denied` |
| App | `503 model_budget_exceeded`, `503 model_throttled` (+ `Retry-After`), `502 model_rejected`; `429` do provider segue `503 model_rate_limited` |
| Testes | `tests/governance` 33 (duas execuções); caracterização 32 (intacta); resiliência 34; fallback 40 |
| Retry e fallback | recusas de governança antes do router: nenhum retry, nenhum fallback; falha elegível do provider continua recuperada |
| Custo de cadeia | F1 normal 0,0001575; primário 500 → 0,000222; dois large 500 → 0,00000945 |
| Latência | overhead mediano 1,35 ms (master) vs 1,41 ms (virtual); F1 pela borda 1,09 s |
| Métricas | `docs/governanca/metricas/governance-step-12.csv`, igual ao Passo 11 |
| ADRs | [0007](../adr/0007-gateway-governance-database.md), [0008](../adr/0008-key-bootstrap-service.md), [0009](../adr/0009-corporate-ai-governance.md) (corporativa), [0010](../adr/0010-gateway-governance.md); revisões em 0003, 0005, 0006 |
| Commits | partida `ce6c041` (Passo 11); alterações deste passo na árvore de trabalho da `main`, ainda sem commit (a pedido, para revisão); tags `v1-coupled` `8028305` e `v2-decoupled` `b637c5a` intactas |

## Para o Passo 13 (execução síncrona, F1 e F4)
1. F1 e F4 consomem 1 RPM e ~US$ 0,00016 por requisição (0,00022 em fallback); prazo da app 14 s, requisito de 3 s na F1.
2. Uma recusa de governança é imediata (sem chamada ao provider): o `503 model_throttled`/`model_budget_exceeded` já cabe em qualquer prazo síncrono.
3. A reserva de orçamento (~US$ 0,164 por requisição em voo) limita o helpdesk a ~120 requisições simultâneas: considerar `max_tokens` explícito por capacidade se a concorrência crescer.
4. Passo 14 (streaming F2): recusa vem antes do primeiro byte; custo só no fim do fluxo.
5. Passo 15 (F3 assíncrona): 34 requisições por relatório mensal, cada uma no RPM e no orçamento; recusa no meio precisa virar estado `failed` explícito.

## Limitações
1. Contadores em memória: réplicas do gateway exigiriam Redis.
2. Reserva conservadora recusa requisições que caberiam (simultâneas ou coladas na mesma conexão).
3. Gasto no banco atrasado até ~15 s; reinício do gateway perde o lote pendente; reset de demo espera o lote.
4. Timeout de provider custa 0 no gateway; provider real cobraria.
5. `401` expõe hash da chave e nome de tabela; `Retry-After` pessimista; distinção dos `429` depende do texto do LiteLLM.
6. `soft_budget` sem canal de alerta; rotação manual; gateway e banco são pontos únicos de falha.

## Conhecimentos
Ver [relatório](relatorio-governanca.md) (com 15 perguntas de fixação), [glossário](glossario.md) e [handoffs](handoff-governanca.md).
