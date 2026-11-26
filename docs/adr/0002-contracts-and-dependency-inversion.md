# 0002. Features dependem de um contrato de IA; só o ponto de composição conhece o adapter

- Status: aceita (validada na F1 pelo piloto do Passo 08; F2, F3 e F4 pendentes no Passo 09)
- Data: 2026-11-25 (proposta no Passo 06; aceita no Passo 08, 2026-11-26)
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
- `app/helpdesk/adapters/gateway.py` define `GatewayLanguageModel(LanguageModel)`. Ele usa o SDK `openai` apontado para o gateway (`config.GATEWAY_URL`, `config.GATEWAY_API_KEY`), envia `model=capability` e devolve `choices[0].message.content`. É o **único** componente com SDK de IA. O timeout padrão do SDK não muda nesta fase. O cliente usa `max_retries=0` (revisão do Passo 07): o gateway já retenta 2 vezes por padrão, e manter as 2 do SDK levaria uma falha a até 9 chamadas, contra 3 na v1.
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

Condições definidas no Passo 06 (o resultado está na revisão abaixo). Será aceita se:

- os 32 testes de caracterização passarem com a suíte idêntica à `v1-coupled`;
- a F1 importar só `ports` e `schemas`;
- `adapters.gateway` tiver Ca=1 (`main`);
- `ports` tiver A=1,00;
- nenhum componente novo entrar na zona de dor.

Isso será verificado com `python metrics/measure.py --source app/helpdesk --name piloto-f1`.

## Revisão no Passo 08 (piloto da F1)

**Resultado:** todas as condições de aceitação foram atendidas na F1. Status alterado de "proposta" para "aceita", com escopo explícito: a decisão está validada em **um** dos quatro consumidores. A generalização para F2, F3 e F4 é provável, mas só o Passo 09 a comprova.

| Condição | Evidência (`docs/piloto/`) |
|---|---|
| 32 testes com a suíte idêntica | `32 passed in 59.97s`; `git diff v1-coupled -- tests/characterization/` vazio (evidências 12 e 14) |
| F1 importa só `ports` e `schemas` | arestas do `pilot-after.csv`; `grep` de `llm`, `config`, `openai` e `adapters` vazio na F1 |
| `adapters.gateway` com Ca=1 (`main`) | `pilot-after.csv` |
| `ports` com A=1,00 | `pilot-after.csv`: 2/0/0/1/0 |
| Nada novo na zona de dor | `pilot-after.csv`; zona de dor = `config`, `llm` (transitório), `schemas` |

**Hipóteses confirmadas:**
- o contrato de uma operação bastou, sem nenhum parâmetro a mais;
- a DI por parâmetro e a instância única em `main` funcionaram sem `Depends` nem contêiner;
- a F1 não conhece provider, modelo nem SDK;
- trocar o modelo da F1 não tocou a app (ADR 0004);
- a herança explícita do `Protocol` se justificou fora da métrica: o `mypy` recusa um `complete` com assinatura errada. O risco R3 não se materializou.

**Limitações encontradas:**
- O SDK tipa `message.content` como `str | None`, e o contrato promete `str`. O comportamento é o mesmo da v1 (conteúdo nulo vira 500) e foi mantido. Tratar isso é decisão de erros de modelo (Passo 10), junto com a eventual introdução de erros próprios no contrato.
- Herdar do `Protocol` dá ao adapter um `complete` padrão que devolve `None` se não for sobrescrito (risco levantado pelo agente). Fica coberto pela checagem estática e pelos testes de sucesso.
- O adapter não trata erros. As exceções do SDK viram 500, como na v1; o efeito de o retry ser agora do gateway está no ADR 0003.

**Consequências para o Passo 09:** a decisão não muda. Cada feature migrada recebe o contrato por parâmetro e declara a própria capacidade, e `main` passa a mesma instância. A projeção para a v2 completa (tabela acima, `ports` com Ca=5) continua válida. `llm.py` deve desaparecer.
