# 0002. Features dependem de um contrato de IA; só o ponto de composição conhece o adapter

- Status: proposta (validar no piloto, Passo 08)
- Data: 2026-11-25
- Nível: software

## Contexto

Na `v1-coupled`, as quatro features importam `llm.py` e escolhem o provider pelo nome da função (`call_openai` na F1 e na F4, `call_anthropic` na F2 e na F3) e o modelo por `config`. `llm.py` instancia os SDKs `openai` e `anthropic` no import.

Problemas comprovados (Passo 05, `metrics/results/v1-coupled.csv`):

- `llm`: Ca=4, Ce=1, I=0,20, A=0, D=0,80, na zona de dor. É um detalhe tecnológico concreto no centro do grafo.
- `config`: Ca=6, D=1,00, na zona de dor, com modelos físicos e URLs de provider.
- Nenhuma abstração em toda a aplicação (A=0 nos 9 componentes).
- Acoplamento semântico, invisível à régua: a feature sabe qual provider a atende.

Requisito do desafio para a versão final: a comunicação com o gateway fica concentrada em um único componente de `app/`; nenhuma feature o importa; só o ponto de composição depende dele.

## Opções consideradas

1. **Encapsulamento centralizado.** `llm.py` vira cliente do gateway (`complete(capability, prompt)`), e as features continuam importando-o. É o mais simples, mas viola o requisito, e a projeção mantém o cliente na zona de dor (Ca=4, D=0,80).
2. **Contrato abstrato + adapter do gateway + composição em `main`.**
3. **Um contrato por capacidade** (`Classifier`, `ReplySuggester`, ...). As quatro features fazem a mesma operação, então isso multiplica tipos sem segregar nada.

## Decisão

Opção 2.

- `app/helpdesk/ports.py` define `LanguageModel(Protocol)` com uma operação: `complete(capability: str, prompt: str) -> str`. É síncrona, devolve texto e não declara erros próprios, que só serão introduzidos quando houver quem os trate (fallback, na `main`).
- `app/helpdesk/adapters/gateway.py` define `GatewayLanguageModel(LanguageModel)`. Ele usa o SDK `openai` apontado para o gateway (`config.GATEWAY_URL`, `config.GATEWAY_API_KEY`), envia `model=capability` e devolve `choices[0].message.content`. É o **único** componente com SDK de IA. Os padrões do SDK (timeout e retries) não mudam nesta fase.
- Cada feature monta o próprio prompt (`TASK: ...`, que é comportamento caracterizado), declara sua capacidade como constante e recebe o contrato **por parâmetro**.
- `main.py` é o **Composition Root**: cria o adapter uma vez e o passa às features. Não usamos contêiner de DI nem `Depends`.
- `llm.py` é substituído progressivamente, feature por feature, e removido quando não tiver mais importadores. `llm.parse_json` vira `json.loads` nas features.
- Não criamos camadas, entidades, casos de uso, repositórios ou factories.

### Impacto projetado nas métricas (não medido)

Os valores foram calculados com a ferramenta sobre um esqueleto de imports, conforme `docs/refactoring-plan.md` §14:

| Componente | v1 (medido) D | v2 (projetado) Ca/Ce/I/A/D |
|---|---|---|
| `ports` | — | 5/0/0,00/1,00/0,00 |
| `adapters.gateway` | — | 1/2/0,67/0,00/0,33 |
| features F1, F2, F4 | 0,25 | 1/2/0,67/0,00/0,33 |
| `report` | 0,20 | 1/4/0,80/0,00/0,20 |
| `llm` | 0,80 | removido |
| `config` | 1,00 | 3/0/0,00/0,00/1,00 |

## Consequências

- (+) As features deixam de conhecer provider, modelo e SDK. A seta de dependência passa a apontar para a abstração.
- (+) Trocar o mecanismo de acesso à IA afeta só o adapter e `main`. As features ficam testáveis com qualquer objeto que tenha `complete`.
- (+) `ports` fica sobre a Main Sequence (A=1, I=0).
- (−) Um `Protocol` com uma só implementação. Ele é justificado pelo requisito e pela testabilidade, não por extensibilidade imaginada.
- (−) O prompt `TASK: ...` aparece em quatro features, uma linha cada.
- (−) O D das features piora de 0,25 para 0,33, porque elas passam a ter menos dependências. Isso é aceito e registrado como exemplo de Goodhart.
- Riscos:
  - herdar explicitamente do `Protocol` parecer manobra métrica (R3);
  - o agente criar abstrações a mais (R2).
  - Ambos são tratados pelos critérios de rejeição do plano.

## Evidência

Pendente (Passo 08). Será aceita se:

- os 32 testes de caracterização passarem com a suíte idêntica à `v1-coupled`;
- a F1 importar só `ports` e `schemas`;
- `adapters.gateway` tiver Ca=1 (`main`);
- `ports` tiver A=1,00;
- nenhum componente novo entrar na zona de dor.

Isso será verificado com `python metrics/measure.py --source app/helpdesk --name piloto-f1`.
