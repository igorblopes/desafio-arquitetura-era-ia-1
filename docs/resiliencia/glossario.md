# Glossário do Passo 10

| Conceito | Definição | No helpdesk |
|---|---|---|
| Fault Tolerance | continuar cumprindo o contrato apesar de falhas | retry recupera um `500` passageiro |
| Resiliência | degradar de forma controlada e se recuperar | erro explícito em 8,6 s em vez de 504 |
| Falha transitória | passa sozinha | falha removida entre tentativas |
| Falha persistente | dura até alguém agir | `error_500` ligado |
| Falha parcial | só parte do sistema falha | `openai` fora: F1 e F4 |
| Falha em cascata | a falha consome recursos de quem chama | threads da app presas num provider travado |
| Blast Radius | alcance de uma falha | um provider: metade; gateway: tudo |
| Tail Latency | latência dos piores percentis | F3 do mês: 34 chamadas expõem a cauda |
| Connection Timeout | prazo para conectar | 2 s da app ao gateway |
| Read Timeout | prazo entre recebimentos | limite da app (vale como total sem streaming) |
| Request Timeout | prazo de uma requisição | 3, 12 ou 20 s por tentativa |
| Deadline | instante em que a operação precisa terminar | 14 s ou 25 s por chamada |
| Latency Budget | divisão do tempo disponível | primário ~9 s, fallback ~5 s |
| Timeout Budget | parte do orçamento gasta em esperas | 2 × 3 s + pausas |
| Cancelamento | interromper o trabalho em andamento | não acontece: o provider segue gerando |
| Retry | repetir no mesmo destino | 1 no gateway |
| Retry Budget | limite global de repetições | aqui, só o limite por requisição |
| Retry Exhaustion | acabaram as tentativas | `503` |
| Retry Amplification | camadas multiplicando tentativas | evitada: 2, não 6 |
| Retry Storm | muitas repetições simultâneas sobrecarregando | risco com várias F1 em falha |
| Idempotência | repetir não muda o resultado além da 1ª vez | nada é gravado, mas custa tokens |
| At-most-once | no máximo uma execução | F2 e F3 em timeout |
| At-least-once | uma ou mais | F1 e F4 com retry |
| Exactly-once | exatamente uma | não oferecido |
| Fixed Backoff | pausa constante | não usado |
| Linear Backoff | pausa cresce por soma | não usado |
| Exponential Backoff | pausa dobra | 0,5 s × 2ⁿ do LiteLLM |
| Capped Exponential Backoff | exponencial com teto | teto de 8 s |
| Jitter | aleatoriedade na pausa | 0 a 0,75 s |
| Thundering Herd | muitos clientes acordam juntos | mitigado pelo jitter |
| Retry-After | pausa sugerida pelo servidor | 2 s no `429` |
| Rate Limiting | limitar o volume de requisições | `error_429`; o do gateway é o Passo 12 |
| Resource Exhaustion | acabar threads, conexões, memória | pool de threads da app |
| Erro recuperável | repetir pode resolver | 429, 5xx, timeout |
| Erro não recuperável | repetir não resolve | 400, 401, 403, 404 |
| Fallback | trocar de destino ou estratégia | Passo 11 |
