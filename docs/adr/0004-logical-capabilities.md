# 0004. A aplicação pede capacidades lógicas; o gateway mapeia para modelos físicos

- Status: proposta (validar nos Passos 07 e 08)
- Data: 2026-11-25
- Nível: solução

## Contexto

Na `v1-coupled`, `config.py:10-13` fixa `gpt-fake-large` para a classificação e a extração e `claude-fake-large` para a sugestão e o relatório. Por isso:

- trocar um modelo é uma decisão operacional que vira mudança de código e deploy (Passo 02, Dor 4);
- a feature carrega o nome do fornecedor e do tamanho do modelo, que são detalhes que não lhe pertencem.

Fatos do Passo 03 que fundamentam o mapeamento:

- GPT large e Claude large respondem igual em 100% dos casos testados.
- O mini mantém F1 e F3 idênticas.
- Na F2, o mini reduz o texto para ~44% e reordena frases.
- Na F4, o mini devolve `product: null` em 6 de 6 casos, uma incorreção silenciosa.
- Contexto de 8.000 tokens em todos os modelos.

## Opções consideradas

1. Manter os nomes físicos na aplicação (v1).
2. Nomes lógicos por provider ou tamanho (`openai-large`, `fast`): continuam expondo infraestrutura e acoplam decisões futuras.
3. **Um nome lógico por capacidade de negócio**, mapeado no gateway.
4. Uma capacidade compartilhada entre features que hoje usam o mesmo modelo (por exemplo, F1 e F4): acoplaria decisões que o Passo 03 mostra serem diferentes (F4 não tolera mini).

## Decisão

Opção 3.

| Capacidade lógica | Feature | Modelo na v1 | Modelo primário na v2 |
|---|---|---|---|
| `ticket-classification` | F1 | `gpt-fake-large` | `gpt-fake-large` |
| `reply-suggestion` | F2 | `claude-fake-large` | `claude-fake-large` |
| `topics-report` | F3 | `claude-fake-large` | `claude-fake-large` |
| `order-extraction` | F4 | `gpt-fake-large` | `gpt-fake-large` |

- **Responsabilidade do nome:** declarar a intenção de negócio. O nome não contém provider, família, tamanho nem técnica, e permanece enquanto a feature existir.
- **Onde vive:**
  - como constante na própria feature (`CAPABILITY = "ticket-classification"`);
  - como `model_name` na configuração do gateway.
  - Não existe `Enum` central, porque ele acoplaria as features entre si.
- **Mapeamento:** apenas no gateway. Na v2, cada capacidade tem um único destino, o mesmo modelo `large` da v1, para preservar os resultados caracterizados.
- **Evolução:** destinos equivalentes (fallback) e uso de `mini` onde o Passo 03 permitir (F1, F2, F3 com ressalva; nunca F4) serão decididos em ADRs da `main`, sem alterar a aplicação.

## Consequências

- (+) Trocar ou acrescentar modelo é configuração do gateway.
- (+) A aplicação não contém nomes físicos (`grep -rnE "gpt-fake|claude-fake" app/` vazio).
- (+) Cada feature pode evoluir a política de modelo de forma independente.
- (−) O nome existe em dois lugares (feature e gateway). Um nome errado só falha em execução; a falha é alta (erro do gateway) e é coberta pelos testes de cada rota.
- (−) Quatro entradas no gateway para dois modelos físicos. A duplicação é intencional.

## Evidência

Pendente.

- No Passo 07: cada capacidade responde no gateway com o modelo esperado.
- Ao fim do Passo 09:
  - a busca por nomes físicos em `app/` vem vazia;
  - os 32 testes de caracterização estão verdes;
  - o log do gateway mostra as 4 capacidades resolvidas para os modelos da tabela.
