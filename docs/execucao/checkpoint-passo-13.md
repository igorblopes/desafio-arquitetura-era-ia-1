# Checkpoint do Passo 13 (entrada do Passo 14)

| Item | Estado |
|---|---|
| Aplicação | `main`, desacoplada, resiliente, governada; F1 e F4 síncronas **por decisão** (ADR 0011); F2 e F3 ainda síncronas, sem mudança neste passo |
| Arquitetura | borda nginx (30 s) → FastAPI → feature → `ports.LanguageModel` → `adapters.gateway` → LiteLLM `v1.102.1` (chave virtual, orçamento, RPM, retry, fallback) → provider-fake |
| Padrões estudados | Request-Response, Streaming (SSE), Asynchronous Request-Reply, Event-driven; acoplamento temporal × espacial × de código; I/O bloqueante × Async I/O |
| Decisão F1 | síncrono: cliente esperando na tela; saída de ~11 tokens (2 enums), ~1,1 s; não é útil fragmentar; assíncrono adicionaria estado sem ganho |
| Decisão F4 | síncrono: automação bloqueada precisa do par pedido + produto completo; ~1,1 s; pior caso 6,05 s; falha explícita é melhor que dado errado; sem meta de 3 s (não existe no enunciado) |
| F2 e F3 | hipóteses registradas no ADR 0011: F2 streaming (Passo 14), F3 Asynchronous Request-Reply (Passo 15) |
| Contratos | rotas, entradas e saídas de sucesso idênticos à v1; erros `422`, `502`, `503` com corpo JSON |
| Execução interna | rotas `def` no thread pool do AnyIO (40 threads); SDK `openai` 3.19.0 síncrono (`httpx2`, pool 1.000), `max_retries=0`; **sem** `async def` (o exemplo mostra que `async def` com cliente síncrono congelaria o loop) |
| Timeouts | por tentativa no gateway: F1 3/3/2 s, F4 3/3 s; conexão app → gateway 2 s |
| Deadline | 14 s na app para F1 e F4 (uma chamada HTTP; retry e fallback não reiniciam); medido 14,02 s com o gateway congelado |
| Tentativas | F1 até 4 (primário 2 só em `500`/`503`, equivalente 1, mini 1); F4 até 3; declarado = observado |
| Fallback | F1: `gpt-fake-large` → `claude-fake-large` → `gpt-fake-mini`; F4: → `claude-fake-large` → `503` (mini nunca chamado, mesmo no ar) |
| Governança | chave `helpdesk-app`; recusa de orçamento/RPM em 7–29 ms, `503` com `code`, 0 chamadas ao provider; credencial inválida `502 model_rejected` |
| Correção de código | `classification.py` e `extraction.py`: saída fora do contrato vira `502` (antes `500` ou `200` fictício); F4 exige as duas chaves e `fullmatch(#[0-9]{6})`; F1 monta a resposta com campos explícitos |
| Latências (borda) | F1 normal 1,062–1,163 s (75 execuções, 0 > 3 s); F4 normal 1,062–1,237 s; primário travado F1 4,10 s, F4 4,25 s; `500` 2,7–3,8 s; `429` 1,10/1,25 s; tudo travado F1 8,05 s, F4 6,05 s; nenhum `504` |
| `/admin/calls` | normal 1 chamada no primário; `500` 3; timeout 2; dois large F1 4 (mini `200`), F4 3 (sem mini); tudo fora F1 4, F4 3; governança 0 |
| Concorrência | 1–40 simultâneas: máx. 1,28 s; 60: bimodal, máx. 2,42 s (limite de 40 threads); nenhuma falha; não é requisito |
| Testes | `tests/execution` 57 (borda, contrato de saída, prazo, governança); caracterização 32, resiliência 34, fallback 40, governança 33 (ver `evidencias/21-todas-as-suites.txt`) |
| Métricas | `docs/execucao/metricas/sync-execution-step-13.csv`, idêntica ao Passo 12 (20 arestas); não é a medição definitiva da `main` |
| ADR | [0011](../adr/0011-execution-modes.md) (unificado, nível solução, uma seção por feature) |
| Integridade | tags `v1-coupled` `8028305` e `v2-decoupled` `b637c5a` intactas; `provider-fake/`, `edge/`, `data/`, `tests/characterization/` sem diff; `grep` de modelos e chaves em `app/` vazio |
| Commits | partida `8227f5a` (Passo 12); alterações deste passo **na árvore de trabalho, sem commit** (a pedido) |

## Para o Passo 14 (streaming na F2)

1. Métrica principal passa a ser o tempo até o 1º trecho pela borda; o tempo total continua (~16 s) e precisa ficar abaixo dos 30 s **entre bytes** do nginx.
2. Erro e fallback só podem mudar o status antes do 1º byte; depois, evento de erro no fluxo (`midstream_error` do simulador).
3. Hoje a F2 travada responde `503` aos 25 s e deixa cadeia órfã; com streaming, o prazo relevante vira o do 1º token.
4. A conexão fica aberta ~16 s: no modelo `def` atual são 16 s de thread ocupada por atendente; com 40 threads, 40 atendentes simultâneos. Avaliar `async def` + cliente assíncrono **só** se medir problema.
5. Orçamento reservado durante toda a geração; custo contabilizado no fim do fluxo; fluxo abortado pode ser cobrado.
6. Completar a seção F2 do ADR 0011 (não criar ADR novo).

## Limitações

1. Sem validação semântica: número bem formado pode ser o pedido errado.
2. Trabalho órfão quando a app desiste (gateway congelado processou 2 requisições abandonadas; `slow` segue gerando).
3. Margem de 1 s entre o prazo da app (14 s) e o requisito (15 s).
4. Máximo de 40 esperas simultâneas por processo.
5. `502` de saída inválida só com `detail` (sem `code`), por compatibilidade com a v1.
6. Sucesso após retry e pior caso misto do gateway não provocados pela borda (simulador com modo fixo).

## Conhecimentos

Ver [relatório](relatorio-execucao.md) (31 seções, 15 perguntas de fixação), [glossário](glossario.md) e [handoff](handoff-execucao.md).
