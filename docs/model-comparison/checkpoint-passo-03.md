# Checkpoint de continuidade: fim do Passo 03

## Estado atual
- Repositório em `ab53bae` (commit do Igor com o diagnóstico, sobre `a1aedd7`). `app/`, `provider-fake/`, `edge/` e `data/` estão idênticos ao `upstream/main`.
- Provider em `normal`, `/admin/calls` limpo e containers no ar.
- Ainda não existem: a tag `v1-coupled`, a caracterização, a métrica e o gateway.

## Experimentos realizados (direto no provider, 25/11/2026)
- 4 tarefas × 4 modelos: F1 com 21 casos, F4 com 12, F2 com 3 (+ streaming × 3 e `max_tokens` 50), F3 com 4 conjuntos (20, 137, 150 e 200 tickets). 188 chamadas em `/admin/calls`.

## Características dos modelos
- Contexto de 8.000 nos quatro. Large: TTFT 0,8 s, 40 tok/s. Mini: TTFT 0,3 s, 150 tok/s.
- Preços (US$/1M, entrada/saída): GPT L 2,50/10; GPT m 0,15/0,60; Claude L 3/15; Claude m 0,80/4.
- Latência = TTFT + saída ÷ velocidade (confirmado com erro de ms).

## Diferenças funcionais comprovadas
- GPT L ≡ Claude L e GPT m ≡ Claude m em 100% dos casos testados.
- Mini × large: **F1 e F3 idênticos**; **F2** com ~44% dos tokens e frases reordenadas; **F4** com `product: null` em 6/6 casos (pedido igual ao large).
- Também no large: com dois pedidos no texto, pega o primeiro (#112233 em vez de #445566); produto fora do catálogo vira null.

## Performance e custo
- F1: L 1,1 s / m 0,38 s. F2: L 15,95 s síncrono, 0,80 s de 1º trecho com stream / m 2,08 s, 0,30 s. F3 (150): L 9,83 s / m 2,71 s. F4: L 1,1 s / m 0,37 s.
- O stream não reduz o total (16,17 s contra 15,95 s); reduz a espera percebida.
- Relatório mensal: Claude L US$ 0,85 (medido) · GPT L 0,68 · Claude m 0,23 · GPT m 0,04 (projeções). Em série, o mini leva ~92 s, ainda acima de 30 s.
- O fallback Claude L custa de +20% a +50% em relação ao GPT L.

## Recomendações preliminares (para os ADRs)
| Feature | Mini como fallback |
|---|---|
| F1 | sim (sem degradação; cliente esperando) |
| F2 | sim (revisão humana) |
| F3 | sim com ressalva, ou reprocessar depois |
| F4 | **não**: falhar explicitamente (incorreção silenciosa) |

O fallback técnico é sempre o `large` do outro provider. A `v2-decoupled` mantém um `large` em cada capacidade.

## Questões em aberto
- O custo de uma troca errada na F4 não está no enunciado.
- As amostras são pequenas; a F3 com mini não foi testada no mês inteiro.
- Onde validar a F4 além do formato.
- O stream OpenAI não traz `usage`: considerar isso na contabilidade de custo do gateway.

## Conhecimentos adquiridos
Provider ≠ modelo ≠ capacidade; equivalência funcional ≠ de custo ≠ de interface; resposta válida ≠ correta; streaming reduz a espera percebida, não o total; o modelo mais rápido não substitui a escolha do modo de execução.
