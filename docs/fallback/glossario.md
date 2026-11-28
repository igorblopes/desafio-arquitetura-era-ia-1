# Glossário do Passo 11 (fallback)

| Conceito | O que é | Situação concreta no projeto |
|---|---|---|
| Fallback | Alternativa usada quando o destino original falha | `claude-fake-large` atende a F1 quando o `gpt-fake-large` dá `500` |
| Failover | Transferir a operação para outro destino equivalente disponível | o fallback técnico: mesma saída, outro provider |
| Retry | Repetir no **mesmo** destino | `500` no primário é repetido uma vez, com backoff |
| Graceful Degradation | Entregar algo inferior, mas útil e honesto | sugestão do mini na F2, ~44% do tamanho, que o atendente completa |
| Fail-open | Na dúvida, entregar um resultado | F1 e F2 aceitam o mini |
| Fail-closed | Na dúvida, recusar | F3 e F4 respondem `503` em vez de usar o mini |
| Redundância | Ter mais de um destino capaz | dois large de providers diferentes por capacidade |
| Fault Tolerance | Continuar funcionando com um componente falho | queda da OpenAI simulada não derruba a F1 nem a F4 |
| Failure Domain | Conjunto de coisas que caem juntas | os dois providers estão no mesmo container `provider-fake`: domínio compartilhado |
| Single Point of Failure | Componente cuja queda derruba tudo | o `gateway`: sem ele, as quatro features caem |
| Equivalência funcional | Mesma saída para a mesma entrada | GPT L × Claude L: 1.000/1.000 em classify e extract |
| Equivalência semântica | Mesmo significado, não só mesmo formato | o mini da F4 tem o formato certo e o pedido errado: não é equivalente |
| Confiabilidade funcional | O resultado serve ao negócio | `200` com `#927477` (nota fiscal) no lugar de `#389511` não é sucesso |
| Disponibilidade | A operação responde | subiu com o fallback; sozinha, não prova correção |
| Human-in-the-loop | Uma pessoa revisa antes do efeito | atendente na F2; ninguém na F4 |
| Model Routing | Escolher o destino físico de uma capacidade | `gateway/config.yaml`, fora da app |
| Model Group | Nome no gateway que agrupa destinos | `ticket-classification`, `ticket-classification-equivalent` |
| Primary Destination | Destino usado em condições normais | GPT L na F1/F4, Claude L na F2/F3 |
| Fallback Chain | Sequência finita de destinos | F1: GPT L → Claude L → GPT mini; F4: GPT L → Claude L |
| Modelo inferior | Modelo mais barato e rápido, com limitações conhecidas | `*-fake-mini` |
| Deadline | Prazo total da operação, que não reinicia ao trocar de destino | 14 s (F1/F4), 25 s (F2, F3 por lote), na app |
| Latency Budget | Divisão do deadline entre destinos | F1: 6 + 3 + 2 = 11 s de 14 s |
| Retry Budget | Teto de tentativas | F1/F2: 4 chamadas; F3/F4: 3 |
| Retry Amplification | Camadas repetindo umas sobre as outras | evitada: só o router do gateway repete; SDKs com 0 |
| Failure Isolation | Impedir que a falha de um destino contamine os outros | fallback por lote na F3: o 1º lote não é refeito |
| Cadeia órfã | Cadeia que segue no gateway depois que o cliente desistiu | F2 travada chamou o mini ~40 s depois do `503` |
| FinOps | Gestão de custo de nuvem/IA | fallback técnico custa de −33% (F2) a +44% (F4); geração cortada ainda é paga |
| Risco de negócio | Consequência de errar ou de não responder | F4: troca no pedido errado custa mais que esperar |
