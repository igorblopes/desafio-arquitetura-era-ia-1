# 0004. A aplicação pede capacidades lógicas; o gateway mapeia para modelos físicos

- Status: aceita no gateway (Passo 07) e no uso pela aplicação para as quatro capacidades (Passos 08 e 09)
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

## Revisão no Passo 08 (troca de modelo pelo helpdesk)

A limitação "a troca foi demonstrada com um cliente de teste" foi resolvida para a F1. A F1 declara `CAPABILITY = "ticket-classification"` e o adapter envia esse nome no campo `model`. O teste a seguir foi feito pela borda, como um cliente real:

| Etapa | Resultado |
|---|---|
| Antes | `POST /tickets/classification` (TK-00042) → 200, `delivery`/`high`; `/admin/calls`: `openai`/`gpt-fake-large` |
| Troca | só o bloco `litellm_params` de `ticket-classification` em `gateway/config.yaml`; `docker compose restart gateway` (7,7 s até ficar saudável) |
| Depois | mesma requisição → mesma resposta (1,28 s); `/admin/calls`: `anthropic`/`claude-fake-large`/`classify` |
| App | container com o mesmo Id e o mesmo horário de início; hashes dos arquivos da app e `git diff --stat -- app/` iguais |
| Restauração | arquivo restaurado (igual ao `HEAD`), gateway reiniciado; a F1 voltou a `openai`/`gpt-fake-large` |

Evidências: `docs/piloto/evidencias/20` a `23`.

**Confirmado:** a escolha do modelo da F1 deixou de ser decisão de código e virou configuração operacional. No Passo 02, a mesma troca exigia editar `config.py`, reconstruir a app e passar por 502 na borda.

**Limitações:**
- A capacidade continua existindo em dois lugares (constante na feature e `model_name` no gateway). Um nome errado falharia em execução com 400; a verificação própria do piloto confere o nome enviado.
- A prova vale para uma capacidade. A validação final repete a troca depois da migração completa (Passo 09).
- `config.CLASSIFICATION_MODEL` não tem mais consumidor, mas fica até o incremento 8 do plano, que remove juntos todos os modelos físicos da app.

**A decisão continua válida, sem mudança.**

## Revisão no Passo 09 (quatro capacidades pela aplicação)

**Capacidades implementadas e mapeamento inicial.**

| Capacidade | Feature (constante `CAPABILITY`) | Modelo físico (`gateway/config.yaml`) | Modelo na v1 (`config.py`) |
|---|---|---|---|
| `ticket-classification` | F1 `classification.py` | `openai/gpt-fake-large` | `CLASSIFICATION_MODEL = "gpt-fake-large"` |
| `reply-suggestion` | F2 `suggestion.py` | `anthropic/claude-fake-large`, `max_tokens: 2000` | `SUGGESTION_MODEL = "claude-fake-large"` |
| `topics-report` | F3 `report.py` | `anthropic/claude-fake-large`, `max_tokens: 2000` | `REPORT_MODEL = "claude-fake-large"` |
| `order-extraction` | F4 `extraction.py` | `openai/gpt-fake-large` | `EXTRACTION_MODEL = "gpt-fake-large"` |

Todas usam o modelo `large` que a v1 usava; nenhum `mini` aparece no código nem na configuração.

**Separação entre capacidades e implementações físicas.** `grep -rnE "gpt-fake|claude-fake|mini" app/` sem saída; as 4 constantes de modelo saíram de `config.py` (`docs/v2/evidencias/10`). A sonda pela borda mostra cada feature atendida pelo modelo do gateway (`15`).

**Troca de modelo pela borda, depois da migração completa** (`20`):

| Etapa | Resultado |
|---|---|
| Antes | `POST /tickets/reply-suggestion` (TK-00042) → 200, 2424 caracteres; `/admin/calls`: `anthropic`/`claude-fake-large`/`suggest` |
| Troca | 3 linhas de `litellm_params` de `reply-suggestion` (`model`, `api_base`, `api_key`); `docker compose restart gateway && docker compose up -d --wait` (8,6 s) |
| Depois | mesma resposta (`cmp` sem diferença, mesmo sha256); `/admin/calls`: `openai`/`gpt-fake-large`/`suggest`; F1, F3 e F4 inalteradas |
| App | mesmo Id de container, mesma imagem (`sha256:f55a1d46…`), mesmo horário de início; hashes de `app/` iguais |
| Restauração | `git restore gateway/config.yaml`, diff vazio; F2 de volta a `anthropic` |

A F2 foi escolhida por ser a capacidade mais sensível (texto longo e mudança de formato de API entre providers). A resposta idêntica é propriedade do provider-fake (respostas determinísticas por tarefa); com providers reais, a troca de modelo muda o texto, e é por isso que ela é decisão operacional, não de código.

**Limitações.** A capacidade continua em dois lugares (constante na feature e `model_name` no gateway); um nome errado falharia com 400 em execução, e a verificação própria confere os quatro nomes. Fallback e modelo fraco por capacidade ficam para o Passo 11.

**A decisão continua válida, sem mudança.**
