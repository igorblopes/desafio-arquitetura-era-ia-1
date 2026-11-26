# Handoff: piloto de refatoração da F1 (classificação de tickets)

Você é o agente de desenvolvimento desta tarefa. O arquiteto define a estratégia, o escopo e os critérios; você implementa dentro desses limites, roda as verificações e apresenta as evidências. A aprovação não é sua: o arquiteto vai conferir o diff, os testes e as métricas por conta própria.

O trabalho tem duas fases. **Fase 1: só a proposta, sem alterar nenhum arquivo.** A fase 2 (implementação) só começa quando o arquiteto mandar uma mensagem autorizando.

## 1. Contexto do projeto

- **Desafio:** helpdesk FastAPI (Full Cycle, "Arquitetura na Era da IA") com 4 features de IA: F1 classificação, F2 sugestão de resposta, F3 relatório de temas, F4 extração de pedido. O objetivo da fase atual é a `v2-decoupled`: as features dependem de um contrato, e só um adapter fala com o AI Gateway.
- **Arquitetura atual (tag `v1-coupled`):** `classification.py` chama `llm.call_openai(config.CLASSIFICATION_MODEL, "classify", ticket.text)`. `llm.py` cria os clientes dos SDKs `openai` e `anthropic` apontados para o `provider-fake`, com as chaves dos providers, e monta o prompt `f"TASK: {task}\n{content}"`. `config.py` guarda chaves, URLs e nomes físicos de modelo.
- **Problemas comprovados (Passo 02 e métricas do Passo 05):**
  - a feature escolhe o provider pelo nome da função;
  - o modelo físico está no código, então trocar o modelo exige rebuild;
  - `llm` é concreto, usa dois SDKs e está na zona de dor (Ca=4, I=0,20, A=0, D=0,80).
- **Arquitetura proposta:** `docs/refactoring-plan.md`, seções 8, 10 e 13 (decisões já aprovadas, não reabra).
- **Gateway (validado no Passo 07):**
  - serviço `gateway` (LiteLLM Proxy `v1.102.1`) em `http://gateway:4000`, API compatível com OpenAI em `POST /v1/chat/completions`;
  - autenticação `Authorization: Bearer CHAVE_DO_GATEWAY`;
  - a capacidade lógica `ticket-classification` aponta hoje para `openai/gpt-fake-large`;
  - a resposta traz o nome lógico no campo `model`;
  - erros chegam como status HTTP com mensagem reescrita pelo LiteLLM: não interprete a mensagem;
  - o gateway já faz 2 retentativas por padrão em 5xx.
- **Infraestrutura já preparada pelo arquiteto (não altere):**
  - `app/helpdesk/config.py` ganhou `GATEWAY_URL` (valor `http://gateway:4000`, sem `/v1`) e `GATEWAY_API_KEY`, lidos do ambiente;
  - `compose.yaml` entrega as duas variáveis ao serviço `app`, e o `app` passou a depender do `gateway` saudável.
- **Capacidade lógica do piloto:** `ticket-classification`.

## 2. Artefatos de referência

| Artefato | Caminho |
|---|---|
| Plano de refatoração | `docs/refactoring-plan.md` (seções 8, 10, 13, 14.2, 17 e 19) |
| ADRs | `docs/adr/0001` a `0004` |
| Testes de caracterização | `tests/characterization/` (32 testes; 13 da F1 em `test_classification.py`) |
| Baseline de métricas | `metrics/results/v1-coupled.csv` |
| Ferramenta de métricas | `metrics/measure.py` |
| Configuração do gateway | `gateway/config.yaml`; relatório em `docs/gateway/relatorio-gateway.md`, seção 13 |
| Código do componente | `app/helpdesk/classification.py`, `app/helpdesk/main.py`, `app/helpdesk/llm.py`, `app/helpdesk/config.py` |

Leia só o necessário. Não é preciso ler o plano inteiro.

## 3. Tarefa

- **Componente-alvo:** `app/helpdesk/classification.py` (F1).
- **Dependência a inverter:** hoje a F1 depende de `llm` (concreto) e de `config` (modelo físico). Depois, deve depender só de um contrato abstrato e de `schemas`.
- **Contrato a introduzir:** `app/helpdesk/ports.py` com o `Protocol` `LanguageModel`, uma operação `complete(self, capability: str, prompt: str) -> str` (executa a capacidade lógica sobre o prompt e devolve o texto gerado). Nada além disso: sem objetos de requisição ou resposta, uso de tokens, erros próprios, streaming ou async.
- **Adapter a implementar:** `app/helpdesk/adapters/__init__.py` (vazio) e `app/helpdesk/adapters/gateway.py` com `GatewayLanguageModel(LanguageModel)`.
  - Herda explicitamente do `Protocol` (PEP 544) para declarar a conformidade.
  - Cria **uma vez**, no construtor, o cliente do SDK `openai` com `base_url=f"{config.GATEWAY_URL}/v1"`, `api_key=config.GATEWAY_API_KEY` e `max_retries=0`. O gateway já retenta 2 vezes; com as 2 do SDK, uma falha viraria 9 chamadas, contra 3 na v1.
  - `complete` chama `chat.completions.create(model=capability, messages=[{"role": "user", "content": prompt}])` e devolve `choices[0].message.content`.
  - Não trata nem traduz erros: na v1, exceções do SDK viram 500, e isso deve continuar igual.
  - Sem timeout, retry ou fallback próprios.
- **Refatoração da F1:**
  - `classify(ticket: TicketInput, model: LanguageModel) -> Classification`;
  - constante `CAPABILITY = "ticket-classification"` no próprio módulo;
  - prompt exatamente `f"TASK: classify\n{ticket.text}"`;
  - `json.loads` no lugar de `llm.parse_json`, que é o mesmo `json.loads`;
  - `CATEGORIES`, `PRIORITIES`, a validação, o `HTTPException(status_code=502, detail="Classificação fora dos valores permitidos")` e a construção de `Classification` ficam inalterados.
- **Composição:** `app/helpdesk/main.py` é o Composition Root.
  - Importa `GatewayLanguageModel` e cria uma única instância no carregamento do módulo.
  - A rota `/tickets/classification` passa essa instância a `classification.classify(ticket, instancia)`.
  - Rotas, assinaturas HTTP, tipos de resposta e as outras três rotas não mudam.
- **Responsabilidades a preservar na feature:**
  - o prompt (`TASK: classify`);
  - o nome da capacidade;
  - a interpretação do JSON;
  - a validação de categoria e prioridade e o 502.

## 4. Escopo autorizado

- **Modificar:** `app/helpdesk/classification.py`, `app/helpdesk/main.py`.
- **Criar:** `app/helpdesk/ports.py`, `app/helpdesk/adapters/__init__.py`, `app/helpdesk/adapters/gateway.py`.
- **Nada além disso.**

## 5. Restrições

Você não pode:

- alterar testes (`tests/`), em especial `tests/characterization/`;
- alterar contratos externos: rotas, métodos, corpos de requisição e resposta, status e mensagens de erro;
- refatorar F2, F3 ou F4, nem alterar `suggestion.py`, `extraction.py`, `report.py`, `llm.py`, `schemas.py`, `tickets.py` ou `config.py`;
- alterar `provider-fake/`, `edge/`, `data/`, `gateway/`, `metrics/`, `docs/`, `compose.yaml`, `.env.example`, `.env` ou `app/requirements.txt`;
- manipular as métricas: imports sem uso, módulos ou classes criados para mudar Ca, Ce, A ou D, ou mudanças na ferramenta ou nos resultados versionados;
- introduzir dependências artificiais ou abstrações sem consumidor;
- implementar funcionalidades adicionais, streaming, fallback, retry, timeout, budget ou processamento assíncrono (as rotas continuam `def`);
- usar modelos `mini`, ou escrever nomes de modelo físico ou de provider em código novo;
- fazer commit, push, criar branch ou mexer em tags (inclusive criar `v2-decoupled`);
- apagar volumes ou dados do Docker.

Se algo no escopo parecer impossível ou errado, pare e explique, em vez de contornar.

## 6. Critérios de aceite (o arquiteto vai conferir todos)

**Comportamentais**
- Os 32 testes de caracterização passam.
- `git diff v1-coupled -- tests/characterization/` vazio, sem arquivos novos na pasta.
- Mesma rota, mesmo contrato de entrada e saída, execução síncrona.
- Modelo `large`: o mapeamento do gateway não muda.
- F2, F3 e F4 continuam iguais e seguem chamando o provider diretamente.

**Estruturais**
- `classification.py` não importa `llm`, `config`, `openai`, `anthropic` nem `adapters`.
- `classification.py` depende de `ports` e `schemas` (e `fastapi` e `json`, externos).
- Só `main.py` importa `adapters.gateway`.
- O adapter é o único código novo que usa o SDK.
- `ports.py` não importa nada do pacote `helpdesk`.
- Regras de negócio continuam na feature.
- Sem imports sem uso.

**Quantitativos** (mesma ferramenta, mesma régua; projeção do plano, seção 14.2, estado pós-piloto)

| Componente | Antes (medido) | Esperado depois |
|---|---|---|
| `classification` | Ca=1, Ce=3, I=0,75, A=0, D=0,25 | Ca=1, Ce=2 (`ports`, `schemas`), I=0,67, D=0,33 (a piora de D é esperada: menos dependências) |
| `ports` | não existe | Ca=2 (`classification`, `adapters.gateway`), Ce=0, A=1,00, D=0,00 |
| `adapters.gateway` | não existe | Ca=1 (só `main`), Ce=2 (`ports`, `config`), D=0,33, fora da zona de dor |
| `llm` | Ca=4, D=0,80 | Ca=3 (ainda na zona de dor: F2, F3 e F4 não migraram) |
| `main` | Ce=5 | Ce=6 |
| demais | — | iguais à `v1-coupled` |

**De infraestrutura**
- A F1 pede a capacidade lógica `ticket-classification` ao gateway, com a chave do gateway.
- A F1 não acessa o `provider-fake` diretamente nem conhece o nome físico do modelo.

## 7. Comandos de validação (raiz do repositório; Git Bash ou container, o PowerShell estraga UTF-8)

```bash
# subir ou reconstruir
docker compose up -d --build --wait

# testes de caracterização (32 esperados)
docker run --rm -v "${PWD}:/w" -w /w -e PYTHONDONTWRITEBYTECODE=1 \
  -e HELPDESK_BASE_URL=http://host.docker.internal:8000 \
  -e PROVIDER_ADMIN_URL=http://host.docker.internal:8090 \
  python:3.12-slim sh -c "pip install -q -r tests/requirements.txt && python -m pytest tests/characterization -v -p no:cacheprovider"

# métricas (grava fora do repositório; não use metrics/results nem docs/)
docker run --rm -v "${PWD}:/w" -w /w -e PYTHONDONTWRITEBYTECODE=1 python:3.12-slim \
  sh -c "pip install -q -r metrics/requirements.txt && python metrics/measure.py --source app/helpdesk --name pilot-agente --output-dir /tmp/m --no-plot"

# inspeção
git status --short
git diff --stat
git diff v1-coupled -- tests/characterization/ provider-fake/ edge/ data/
grep -nE "llm|config|openai|anthropic|adapters" app/helpdesk/classification.py   # esperado: vazio
grep -rlE "adapters" app/helpdesk --include=*.py                                 # esperado: main.py e adapters/
grep -rnE "^\s*(from|import) (openai|anthropic)" app/helpdesk                    # esperado: llm.py e adapters/gateway.py

# gateway e provider
docker run --rm -v "${PWD}:/w" -w /w -e PYTHONDONTWRITEBYTECODE=1 \
  -e HELPDESK_BASE_URL=http://host.docker.internal:8000 \
  -e PROVIDER_ADMIN_URL=http://host.docker.internal:8090 \
  python:3.12-slim python docs/piloto/sondas.py f1          # F1 pela borda + /admin/calls
docker compose logs gateway --since 5m | grep chat/completions
curl -s "localhost:8090/admin/calls?last=5"
```

## 8. Formato da entrega

**Fase 1 (agora), proposta sem alterar arquivos:**
- entendimento do problema;
- arquivos que pretende modificar e criar;
- novos componentes;
- estratégia de inversão de dependências;
- contrato proposto;
- integração com o gateway;
- ponto de composição;
- impacto esperado nas métricas;
- riscos;
- plano de validação.

Inclua também qualquer ponto em que discorde deste handoff, com o motivo. Depois, pare e aguarde.

**Fase 2 (após autorização):**
1. resumo da estratégia implementada;
2. arquivos modificados e criados;
3. responsabilidades introduzidas;
4. dependências removidas;
5. dependências adicionadas;
6. justificativa das abstrações;
7. testes executados;
8. resultados dos testes (cole a linha final do pytest);
9. métricas anteriores e posteriores (tabela);
10. evidências de comunicação pelo gateway;
11. limitações;
12. riscos;
13. questões que exigem revisão humana.

Anexe também a saída de `git diff` dos arquivos alterados e o conteúdo integral dos arquivos novos.
