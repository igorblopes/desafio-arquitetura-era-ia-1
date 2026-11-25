# Checkpoint de continuidade: fim do Passo 06

## Estado
- Aplicação inalterada: `app/`, `provider-fake/`, `edge/`, `data/` e `tests/characterization/` são idênticos à `v1-coupled`.
- Arquivos novos desta etapa, sem commit:
  - `docs/refactoring-plan.md` (v1.0)
  - `docs/adr/0002`, `0003` e `0004` (propostas)
  - seção "Revisão no Passo 06" no `docs/adr/0001`
  - `docs/refatoracao/` (este checkpoint e o glossário)
- Pendências herdadas:
  - Igor ainda precisa fazer `git push origin v1-coupled`.
  - O commit do Passo 05 é feito pelo Igor.

## Evidências usadas
- Diagnóstico do Passo 02 (4 dores).
- Comparação de modelos do Passo 03.
- 32 testes de caracterização do Passo 04.
- `metrics/results/v1-coupled.csv` do Passo 05.
- Código real da v1.
- `compose.yaml` e `.env.example`.

## Problemas priorizados
1. `llm`: concreto, com dois SDKs (Ca=4, D=0,80).
2. `config`: modelos físicos, URLs e chaves de provider (Ca=6, D=1,00).
3. Credenciais no ambiente do `app`.
4. Features escolhendo o provider.

Fora da v2: F3 assíncrona, streaming, resiliência e governança.

## Arquitetura proposta (hipótese)
- Alt 2: contrato `ports.LanguageModel` (Protocol) com `complete(capability: str, prompt: str) -> str`.
- Adapter único: `adapters/gateway.py`, que usa o SDK openai apontado para o gateway.
- Composição em `main.py`.
- DI por parâmetro.
- `llm.py` substituído progressivamente e removido no fim.
- O prompt `TASK: ...` fica em cada feature.
- Sem erros próprios, sem tokens, sem async e sem streaming no contrato da v2.

## Capacidades lógicas
| Capacidade | Modelo físico |
|---|---|
| `ticket-classification` | `gpt-fake-large` |
| `reply-suggestion` | `claude-fake-large` |
| `topics-report` | `claude-fake-large` |
| `order-extraction` | `gpt-fake-large` |

Mapeamento só no gateway.

## Gateway candidato (para o Passo 07)
- **Candidato:** LiteLLM Proxy, serviço `gateway` no compose, com imagem de versão fixada e `config.yaml` montado.
- **Posição:** entre `adapters/gateway.py` e `provider-fake`, só na rede interna.
- **Responsabilidades:** credenciais `FAKE_*`, mapeamento das capacidades, tradução para a API Anthropic e autenticação por `GATEWAY_API_KEY` (master key).
- **Provisório:** `max_tokens` 2000 nas capacidades Anthropic.
- **Comunicação com o fake:**
  - `api_base` `http://provider-fake:8090/openai/v1` (openai)
  - `api_base` `http://provider-fake:8090/anthropic` (anthropic)
- **Dependências a evitar:** Postgres e Redis (budget, virtual keys e rate limit ficam para a `main`).
- **Questões a investigar:**
  - tradução para o fake Anthropic;
  - texto da F2 byte a byte;
  - `max_tokens` padrão;
  - retries padrão do proxy;
  - latência frente aos 30 s;
  - prova de que tudo passa pelo gateway;
  - master key sem banco;
  - isolamento de rede.
- **Validar a configuração inicial:**
  - as 4 capacidades respondem direto no gateway com os textos dos goldens;
  - a chamada sem chave é recusada;
  - os 32 testes continuam verdes, com o `app` ainda direto.

## Projeção de métricas (não medida; calculada com a ferramenta sobre um esqueleto de imports)
- **v2 completa:**
  - `ports`: 5/0/0,00/1,00/0,00
  - `adapters.gateway`: 1/2/0,67/0,00/0,33
  - F1, F2 e F4: D 0,33
  - `report`: D 0,20
  - `config`: Ca=3, D=1,00 (continua na zona de dor; decisão no Passo 16)
  - `schemas`: inalterado
  - `llm`: removido
- **Pós-piloto:**
  - `llm`: Ca=3, D=0,75
  - `ports`: Ca=2
  - 22 arestas
- **Adapter sem imports internos:** D=1,00, na zona de dor. Isso é um alerta para o piloto.

## Critérios de aceite da v2
- **Comportamentais:**
  - 32 testes verdes;
  - suíte idêntica à `v1-coupled`;
  - rotas, contratos e modo síncrono preservados;
  - modelos `large`.
- **Estruturais:**
  - features sem SDK, sem `llm` e sem `adapters`;
  - um único adapter;
  - só `main` importa o adapter;
  - sem ciclos.
- **Infraestrutura:**
  - serviço `gateway`;
  - todas as chamadas por ele;
  - nenhum nome físico em `app/`;
  - `app` só com `GATEWAY_*`.
- **Quantitativos:**
  - `llm` ausente;
  - `ports` com A=1 e Ca≥5;
  - adapter com Ca=1, fora da zona de dor;
  - zona de dor ⊆ {config, schemas}.

## Piloto
- **Componente:** F1 `classification.py`.
- **Escopo:**
  - pode criar `ports.py` e `adapters/`;
  - pode ajustar `main.py`;
  - a infraestrutura mínima (`config` +2 constantes, `compose` +2 variáveis) vai em commit separado.
- **Proibido:** as outras features, `llm.py`, `tests/` e `metrics/`.
- **Medições:** `pre-piloto` e `piloto-f1`.
- **Handoff:** template no plano, §19.1.

## Riscos principais
- R5/R6: gateway × fake Anthropic e texto byte a byte.
- R16: retries somados.
- R17: latência.
- R2/R3: abstrações a mais ou métrica manipulada.
- R10: credenciais até o incremento 9.

## Decisões
- **Aprovadas no plano:**
  - Alt 2;
  - contrato;
  - DI por parâmetro;
  - 4 capacidades com `large`;
  - LiteLLM como candidato;
  - F1 como piloto;
  - estrutura `ports.py` + `adapters/gateway.py`.
- **Provisórias:**
  - `max_tokens` no gateway;
  - adapter herdando do Protocol e lendo `config`;
  - isolamento de rede;
  - destino de `config` na `main`.

## Questões em aberto
- As 8 do plano, §12.5.
- Método objetivo para FF10.
- O ADR 0001 deve declarar `config` como exceção ou dissolvê-lo? (Passo 16)

## Conhecimentos adquiridos
- Refatorar não é reescrever.
- DIP ≠ DI ≠ IoC.
- O contrato pertence a quem usa.
- A composição fica num único lugar.
- Capacidade não é modelo.
- A métrica pode piorar quando a arquitetura melhora.
- Uma projeção não é medição.
- Revisar o plano depois do piloto é o objetivo do piloto.

## Próximas atividades
- **Passo 07:** subir o gateway e responder às questões da §12.5. Depois, aceitar ou ajustar os ADRs 0003 e 0004.
- **Passo 08:** fazer o piloto F1 com o handoff, preencher as §§23–25 do plano e criar a revisão 1.1.
- **Passo 09:** migrar F4, F2 e F3; remover `llm.py`; isolar credenciais; medir `v2-decoupled`; criar a tag (com aprovação).
