# 0004. A aplicação pede capacidades lógicas; o gateway mapeia para modelos físicos

- Status: aceita no gateway (mapeamento validado no Passo 07); o uso pela aplicação está pendente (Passos 08 e 09)
- Data: 2026-11-25 (proposta no Passo 06, revisada no Passo 07)
- Nível: solução

## Contexto

Na `v1-coupled`, `config.py:10-13` fixa `gpt-fake-large` para a classificação e a extração, e `claude-fake-large` para a sugestão e o relatório. Isso tem dois efeitos:

- trocar um modelo vira mudança de código e deploy (Passo 02, Dor 4);
- a feature carrega o nome do fornecedor e o tamanho do modelo.

Fatos do Passo 03 que fundamentam o mapeamento:

- GPT large ≡ Claude large em 100% dos casos testados.
- Mini idêntico na F1 e na F3.
- Na F2, o mini produz cerca de 44% do texto e reordena frases.
- Na F4, o mini devolve `product: null` em 6 de 6 casos.
- Contexto de 8.000 tokens.

## Opções consideradas

1. Manter os nomes físicos na aplicação, como na v1.
2. Nomes lógicos por provider ou tamanho (`openai-large`, `fast`). Expõem infraestrutura e acoplam decisões futuras.
3. **Um nome por capacidade de negócio**, mapeado no gateway.
4. Uma capacidade compartilhada entre F1 e F4 por usarem hoje o mesmo modelo. Acoplaria políticas que o Passo 03 mostra serem diferentes: a F4 não tolera mini.

## Decisão

Opção 3.

| Capacidade lógica | Feature | Modelo inicial | Provider | Justificativa |
|---|---|---|---|---|
| `ticket-classification` | F1 | `gpt-fake-large` | openai | mesmo modelo da v1; resultado caracterizado preservado |
| `reply-suggestion` | F2 | `claude-fake-large` | anthropic | mesmo modelo da v1; golden byte a byte; `max_tokens: 2000`, como na v1 |
| `topics-report` | F3 | `claude-fake-large` | anthropic | mesmo modelo da v1; lote de 150 cabe no contexto |
| `order-extraction` | F4 | `gpt-fake-large` | openai | mesmo modelo da v1; mini é inaceitável aqui |

Diferenças entre os termos usados nesta decisão:

- **Nome lógico** (`model_name`) é o que o consumidor pede.
- **Nome físico** (`litellm_params.model`, como `openai/gpt-fake-large`) é o que o provider executa.
- **Capacidade de negócio** é a intenção da feature.
- **Deployment** é a entrada da `model_list` que liga as duas coisas.
- **Roteamento** é a escolha do deployment em tempo de requisição.
- **Configuração operacional** é o arquivo `gateway/config.yaml`, alterável sem tocar a app.

Regras da decisão:

- **Critério da v2:** só modelos `large`, o mesmo provider da v1 e um destino por capacidade.
- **Alteração por configuração:** muda-se só o bloco `litellm_params` da capacidade e reinicia-se apenas o gateway.
- **Onde o nome vive:** como constante em cada feature (Passo 08) e como `model_name` no gateway.

## Consequências

- (+) Validado no Passo 07: as 4 capacidades respondem pelo gateway com o provider e o modelo esperados (`/admin/calls`). A saída é igual à caracterizada.
- (+) Validado no Passo 07: a troca `ticket-classification` de `gpt-fake-large` para `claude-fake-large` foi feita só com configuração e restart do gateway. A resposta foi idêntica, e o container da app não mudou.
- (+) O consumidor recebe o **nome lógico** no campo `model` da resposta, e não o físico.
- (−) O nome existe em dois lugares. Um nome errado é recusado em execução com 400 (`Invalid model name`), sem chegar ao provider.
- (−) Há quatro entradas para dois modelos físicos. Isso é intencional.

## Limitações e decisões futuras

- A troca foi demonstrada com um cliente de teste. A prova pelo helpdesk vem depois da migração (Passo 09).
- Fallback técnico (o `large` do outro provider) e fallback com `mini` (F1, F2; F3 com ressalva; **nunca** F4) serão decididos com as evidências do Passo 03 no Passo 11.
- A equivalência entre GPT large e Claude large é uma propriedade do simulador (Passo 03), não do gateway.

## Evidência

- `docs/gateway/relatorio-gateway.md`, §6 e §7.5.
- `docs/gateway/evidencias/10-capacidades.json`, `17-troca.txt`, `18-troca-antes.json`, `19-troca-depois.json` e `20-troca-restaurado.json`.
