# Glossário do Passo 13: execução síncrona

Cada termo com o significado e onde ele aparece no helpdesk. Evidências em [`evidencias/`](evidencias/); contexto no [relatório](relatorio-execucao.md).

| Termo | Significado | No projeto |
|---|---|---|
| Request-Response | uma requisição HTTP recebe uma resposta com o resultado completo | F1 e F4: `POST` → `200` com o JSON inteiro em ~1,09 s |
| Comunicação síncrona | quem pede espera o resultado antes de seguir | o cliente da F1 fica na tela da abertura até a classificação voltar |
| Comunicação assíncrona | pedido e resultado em momentos distintos | hipótese da F3 (Passo 15): `202` agora, relatório depois |
| Temporal Coupling | os dois lados precisam estar no ar ao mesmo tempo | F1 precisa de borda, app, gateway e um provider vivos no instante da requisição |
| Spatial Coupling | um lado precisa saber onde está o outro | a app conhece só `GATEWAY_URL`; o endereço dos providers ficou no gateway |
| Blocking I/O | a thread fica parada esperando o I/O | o SDK `openai` síncrono no adapter: uma thread por requisição em espera |
| Non-blocking I/O | a operação volta na hora e avisa quando o dado chega | base do event loop do uvicorn |
| Async I/O | esperar I/O suspendendo coroutines em vez de bloquear threads | não usado nas rotas; demonstrado em `exemplo_event_loop.py` (50 em 1,05 s) |
| Event Loop | laço que retoma a coroutine cujo I/O ficou pronto | `async def` + `time.sleep` congelou o loop: `/health` levou 49,9 s no exemplo |
| Coroutine | função suspensível com `await` | `async def` no exemplo didático |
| Task | coroutine agendada no loop | cada requisição `async def` vira uma task no uvicorn |
| Thread | linha de execução do SO dentro do processo | cada rota `def` roda numa thread do pool |
| Thread Pool | conjunto fixo de threads reaproveitadas | AnyIO, 40 threads: com 60 F1 simultâneas, 20 esperaram (máx. 2,42 s) |
| Concorrência | várias tarefas no mesmo período, intercaladas | 40 F1 esperando o gateway juntas, ~1,2 s cada |
| Paralelismo | várias tarefas no mesmo instante, em núcleos diferentes | a geração no provider; a app quase não usa CPU |
| I/O-bound | o tempo é gasto esperando rede ou disco | esperar o gateway: ~1.076 dos ~1.088 ms da F1 |
| CPU-bound | o tempo é gasto calculando | validar JSON e regex: menos de 1 ms |
| Context Switching | troca da thread ou coroutine em execução | troca entre as 40 threads em espera; mais cara que entre coroutines |
| Latency | tempo de uma etapa | 1.076 ms registrados pelo provider |
| Response Time | do envio ao fim da resposta, como o cliente vê | 1,088 s pela borda |
| TTFB | tempo até o 1º byte da resposta HTTP | igual ao tempo total na F1/F4 (sem streaming) |
| TTFT | tempo até o 1º token gerado | 800 ms no `large`; invisível ao cliente síncrono |
| End-to-end Latency | da ação do usuário ao resultado utilizável | response time + o que o cliente faz depois |
| Throughput | operações por unidade de tempo | ~35 F1/s com 40 simultâneas; não é requisito |
| Tail Latency | comportamento das piores requisições | máx. 1,163 s na F1 normal; p95 só com n ≥ 20 |
| Percentil | valor abaixo do qual está X% das amostras | p95 1,163 s com 27 amostras (indício, não prova) |
| Deadline | limite absoluto da operação inteira | 14 s na app (`config.GATEWAY_DEADLINE_SECONDS`): gateway congelado → `503` aos 14,02 s |
| Latency Budget | divisão do tempo disponível entre as etapas | F1: tentativas 3 s + backoff + equivalente 3 s + mini 2 s ≤ 14 s ≤ 15 s ≤ 30 s |
| Structured Output | saída do modelo num formato definido | JSON em texto: `{"category","priority"}`, `{"order_number","product"}` |
| Schema Validation | campos, tipos e obrigatoriedade | F4 exige as duas chaves e tipos texto ou `null` |
| Semantic Validation | se o valor está certo para o negócio | não há: `#123456` bem formado pode ser o pedido errado |
| Pydantic | biblioteca de validação por tipos | `TicketInput` dá `422`; `OrderData` e `Classification` montam a resposta |
| Enum | conjunto fechado de valores | `CATEGORIES` e `PRIORITIES` (conjuntos em `classification.py`) |
| Contrato HTTP | rota, entrada, saída e erros combinados com o consumidor | idênticos à v1 nas rotas; erros `{"detail","code"}` |
| Falha explícita | erro com status e motivo, nunca um sucesso falso | F4 com os dois `large` fora: `503 model_unavailable`, sem `null` |
| Streaming | uma resposta entregue em partes | hipótese da F2 (Passo 14) |
| Asynchronous Request-Reply | `202` + identificador; resultado consultado depois | hipótese da F3 (Passo 15) |
| Trabalho órfão | processamento que continua depois que ninguém espera | gateway descongelado processou 2 requisições já abandonadas |
