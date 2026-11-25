# Plano de refatoração arquitetural

| Item | Valor |
|---|---|
| Versão do plano | 1.0 (planejamento inicial, Passo 06) |
| Data | 2026-11-25 |
| Estado de partida | tag `v1-coupled` (commit `8028305`) |
| Estado de chegada desta fase | tag `v2-decoupled` (Passo 09) |
| Status | **proposto**: hipótese a validar no gateway (Passo 07) e no piloto (Passo 08) |

> Convenções deste documento. **Medido** é o que saiu da ferramenta de métricas sobre a `v1-coupled` ou de execuções reais nos Passos 02 a 05. **Projetado** é o que esperamos para a arquitetura proposta; nunca é medição da v2. **Decisão** é algo que adotamos; **requisito** é algo que o enunciado impõe; **hipótese** é algo que o piloto pode derrubar.

---

## 1. Contexto

### 1.1 Recuperação do contexto (entradas do plano)

| Artefato | Informação | Utilização neste plano |
|---|---|---|
| `docs/diagnostico/` e README, seção "Diagnóstico da v1" (Passo 02) | 4 dores comprovadas: F3 do mês dá 504 em 30,03 s; F2 sem streaming (15,96 s até o 1º byte); provider fora derruba metade das features; troca de modelo exige editar `config.py:10` e rebuild | problemas da seção 5; distinguir o que a v2 resolve do que fica para depois |
| `docs/model-comparison.md` (Passo 03) | GPT large ≡ Claude large em 100% dos casos; mini degrada F2 e F4; contexto de 8.000 tokens; preços | mapeamento capacidade → modelo (seção 11); manter `large` na v2 |
| `tests/characterization/` (Passo 04) | 32 testes pela borda (F1 13, F2 4, F3 6, F4 9), goldens reais; ~60 s | fitness function comportamental; critério de rejeição |
| tag `v1-coupled` | código original congelado + suíte | baseline e rollback |
| `metrics/` + `metrics/results/v1-coupled.csv` (Passo 05) | Ca, Ce, I, A, D dos 9 componentes; 20 arestas; zona de dor: `config`, `llm`, `schemas` | baseline quantitativa e metas (seções 4, 14, 15) |
| `docs/adr/0001-metrics-and-architectural-stability.md` | régua, exceções candidatas (`schemas` sim, `config` não, `llm`/gateway/features proibidos) | critérios quantitativos compatíveis com a régua |
| Código real de `app/helpdesk/` (v1) | 9 módulos, ~200 linhas; detalhes abaixo | toda proposta é ancorada nele |
| `compose.yaml`, `.env.example` | `app` recebe `env_file: .env` com `FAKE_OPENAI_KEY`/`FAKE_ANTHROPIC_KEY` | separação de credenciais (seção 12.4) |

### 1.2 O código que vamos evoluir (fatos)

```text
main.py            rotas síncronas (def) das 4 features; importa as 4 features + schemas
classification.py  llm.call_openai(config.CLASSIFICATION_MODEL, "classify", text) -> parse_json -> valida -> 502
extraction.py      llm.call_openai(config.EXTRACTION_MODEL, "extract", text) -> parse_json -> regex #\d{6} -> 502
suggestion.py      llm.call_anthropic(config.SUGGESTION_MODEL, "suggest", text)
report.py          lotes de config.TICKETS_PER_CALL (150), em série, llm.call_anthropic(config.REPORT_MODEL, "topics", ...)
llm.py             OpenAI(...) e Anthropic(...) instanciados no import; call_openai, call_anthropic(max_tokens=2000), parse_json
config.py          os.environ["FAKE_*_KEY"], URLs do provider-fake, 4 nomes de modelo físico, MAX_OUTPUT_TOKENS, TICKETS_*
schemas.py         7 BaseModel (contrato HTTP)
tickets.py         lê /data/tickets.jsonl inteiro a cada chamada
```

Ambas as funções de `llm.py` enviam a mesma mensagem: `f"TASK: {task}\n{content}"`. O provider-fake usa a linha `TASK:` para decidir o que responder; portanto, **o texto do prompt faz parte do comportamento caracterizado**.

### 1.3 Restrições que valem para toda a refatoração

Não alterar `provider-fake/`, `edge/`, `data/` nem `tests/characterization/`; não mudar o `proxy_read_timeout`; não usar providers reais; nenhum serviço novo no compose sem ADR; não alterar a régua da métrica; não mover a tag `v1-coupled`. Na v2: mesmas rotas, mesmos contratos HTTP, mesmos modos de execução (síncronos) e modelos `large`.

---

## 2. Objetivos

### 2.1 O que é cada marco

| Marco | Escopo | Fora do escopo |
|---|---|---|
| `v2-decoupled` (este plano) | todas as chamadas via gateway; features dependem de um contrato; capacidades lógicas; credenciais e modelos físicos fora da `app`; comportamento idêntico | timeout, retry, backoff, fallback, governança, streaming, assíncrono, modelos `mini` |
| `main` final (Passos 10 a 16) | resiliência, governança, streaming na F2, F3 assíncrona, eventual uso de `mini`; zero componentes na zona de dor fora das exceções do ADR 0001 | — |

**Por que refatorar e não reescrever:** a aplicação tem ~200 linhas, comportamento caracterizado por 32 testes e um problema localizado (como as features chegam aos modelos). Reescrever jogaria fora o que funciona e o que está protegido; a refatoração muda a estrutura preservando o comportamento, em passos pequenos e verificáveis (Fowler; Feathers).

### 2.2 Objetivos verificáveis

| # | Objetivo | Situação atual (medida) | Estado desejado | Evidência de conclusão |
|---|---|---|---|---|
| O1 | Features independentes de SDK e de provider | 4 features importam `llm` e escolhem o provider pelo nome da função | features importam só o contrato (`ports`) e `schemas` (e `tickets`/`config` no caso do relatório) | FF5, FF6 (seção 16); arestas no CSV |
| O2 | Comunicação com a IA em um único componente | `llm.py` (2 SDKs) | `adapters/gateway.py`, único que fala HTTP com o gateway | FF5 |
| O3 | Só o ponto de composição conhece o concreto | não existe composição | apenas `main` importa `adapters.gateway` | Ca(`adapters.gateway`) = 1 e o importador é `main` |
| O4 | A aplicação não conhece modelos físicos | 4 literais em `config.py:10-13` | capacidades lógicas; modelos só no gateway | FF7 |
| O5 | Credenciais dos providers fora da aplicação | `FAKE_*_KEY` no código e no ambiente do `app` | só a credencial do gateway no `app` | FF8, FF9 |
| O6 | Todas as chamadas passam pelo gateway | chamadas diretas ao `provider-fake` | `app` → `gateway` → `provider-fake` | FF10 |
| O7 | Comportamento preservado | 32 verdes na v1 | 32 verdes, suíte idêntica | FF1, FF2 |
| O8 | Estrutura melhor e explicável | zona de dor: `config`, `llm`, `schemas` | `llm` eliminado; nenhum componente novo na zona de dor | CSV `v2-decoupled` (seção 14) |

---

## 3. Diagnóstico da arquitetura atual

### 3.1 Arquitetura original

```mermaid
flowchart LR
    C[Cliente HTTP] --> E[edge nginx 30s]
    E --> M[main FastAPI rotas def]
    M --> F1[classification]
    M --> F2[suggestion]
    M --> F3[report]
    M --> F4[extraction]
    F3 --> T[tickets]
    F1 --> L[llm]
    F2 --> L
    F3 --> L
    F4 --> L
    L --> SO[SDK openai]
    L --> SA[SDK anthropic]
    SO --> PO[provider-fake openai]
    SA --> PA[provider-fake anthropic]
    CFG[(config: chaves, URLs, modelos físicos)] -.lido por.-> L
    CFG -.lido por.-> F1
    style L fill:#f8d7da,stroke:#c0392b
    style CFG fill:#f8d7da,stroke:#c0392b
```

### 3.2 Grafo de dependências original (medido, 20 arestas, sem ciclos)

```mermaid
flowchart TD
    main --> classification
    main --> extraction
    main --> report
    main --> suggestion
    main --> schemas
    classification --> config
    classification --> llm
    classification --> schemas
    extraction --> config
    extraction --> llm
    extraction --> schemas
    suggestion --> config
    suggestion --> llm
    suggestion --> schemas
    report --> config
    report --> llm
    report --> tickets
    report --> schemas
    llm --> config
    tickets --> config
    style llm fill:#f8d7da,stroke:#c0392b
    style config fill:#f8d7da,stroke:#c0392b
    style schemas fill:#fff3cd,stroke:#b7950b
```

**Fluxo de execução × direção das dependências.** Em execução, a requisição desce `main → feature → llm → SDK → provider`. No código, as setas de import apontam na mesma direção: quem tem a regra de negócio (a feature) depende de quem tem o detalhe tecnológico (`llm`, `config`). É exatamente isso que o DIP pede para inverter: o fluxo continua descendo, mas a dependência de código da feature deve apontar para uma abstração que ela mesma define.

### 3.3 Sequência de uma chamada (F1, v1)

```mermaid
sequenceDiagram
    participant Cli as Cliente
    participant Edge as edge
    participant Main as main
    participant F1 as classification
    participant LLM as llm
    participant SDK as SDK openai
    participant P as provider-fake
    Cli->>Edge: POST /tickets/classification
    Edge->>Main: proxy (30 s)
    Main->>F1: classify(ticket)
    F1->>LLM: call_openai("gpt-fake-large", "classify", text)
    LLM->>SDK: chat.completions.create
    SDK->>P: HTTP com FAKE_OPENAI_KEY
    P-->>SDK: JSON
    SDK-->>LLM: response
    LLM-->>F1: texto
    F1->>F1: parse_json + validação (502)
    F1-->>Main: Classification
    Main-->>Cli: 200
```

### 3.4 Problemas comprovados

| # | Problema | Evidência | Causa no código | Impacto (atributo de qualidade) | Resolvido na v2? |
|---|---|---|---|---|---|
| P1 | Features acopladas ao provider | F1/F4 chamam `call_openai`, F2/F3 `call_anthropic` | escolha do provider pelo nome da função | modificabilidade, disponibilidade | **sim** (capacidade + contrato) |
| P2 | Componente concreto e tecnológico no centro | `llm`: Ca=4, I=0,20, A=0, D=0,80 (zona de dor) | SDKs instanciados no import; um método por provider | modificabilidade, testabilidade | **sim** (inversão + adapter) |
| P3 | Modelo físico no código | `config.py:10-13`; troca exige edição + rebuild (6–7 s, 502 na borda) | literais em `config` | modificabilidade, operabilidade | **sim** (nomes lógicos; mapeamento no gateway) |
| P4 | Credenciais de provider na aplicação | `config.py:3-4`; `env_file: .env` no `app` | aplicação autentica direto nos providers | segurança | **sim** |
| P5 | `config` muito importado e concreto | Ca=6, D=1,00 | todas as decisões voláteis num só módulo | modificabilidade | **parcial**: o conteúdo volátil sai; o D projetado continua 1,00 (seção 14.3) |
| P6 | Provider fora derruba metade das features | Passo 02: openai fora → F1/F4 500/504 | sem fallback | disponibilidade | **não** (fallback na `main`); a v2 apenas cria o ponto onde ele será configurado |
| P7 | F3 do mês: 504 em 30,03 s | 34 chamadas em série | `report.py:15-18`, rota síncrona | desempenho, disponibilidade | **não** (assíncrono na `main`) |
| P8 | F2 sem streaming | 15,96 s até o 1º byte | `messages.create` sem `stream` | usabilidade | **não** (streaming na `main`) |
| P9 | Retries e timeouts implícitos dos SDKs | 3 tentativas; timeout de 600 s | padrões do SDK | disponibilidade, custo | **não** (resiliência na `main`); risco de somar retries com o gateway (seção 21) |
| P10 | `schemas` concreto e estável | Ca=5, D=1,00 | DTOs Pydantic | — | **não é problema**: exceção candidata (ADR 0001) |

---

## 4. Baseline de métricas (medida na `v1-coupled`)

| Componente | Ca | Ce | I | A | D | Zona de dor | Leitura |
|---|---|---|---|---|---|---|---|
| classification | 1 | 3 | 0.75 | 0.00 | 0.25 | | métrica boa, acoplamento semântico ao provider |
| config | 6 | 0 | 0.00 | 0.00 | 1.00 | **sim** | detalhes voláteis num módulo estável |
| extraction | 1 | 3 | 0.75 | 0.00 | 0.25 | | idem F1 |
| llm | 4 | 1 | 0.20 | 0.00 | 0.80 | **sim** | detalhe tecnológico no lugar de uma abstração |
| main | 0 | 5 | 1.00 | 0.00 | 0.00 | | entrada; instável como deve ser |
| report | 1 | 4 | 0.80 | 0.00 | 0.20 | | métrica boa; problema de execução (P7) invisível à régua |
| schemas | 5 | 0 | 0.00 | 0.00 | 1.00 | **sim** | DTOs; exceção candidata |
| suggestion | 1 | 3 | 0.75 | 0.00 | 0.25 | | idem F1 |
| tickets | 1 | 1 | 0.50 | 0.00 | 0.50 | no limite | acesso a arquivo; não é alvo da v2 |

**Limitações consideradas** (ADR 0001): a régua não vê SDKs, acoplamento semântico, runtime, HTTP, coesão nem frequência de mudança. Por isso nenhum critério deste plano usa a métrica sozinha: ela é sempre combinada com testes e inspeção do código.

---

## 5. Problemas arquiteturais priorizados

| Componente | Problema | Impacto | Complexidade | Risco | Prioridade |
|---|---|---|---|---|---|
| `llm` | detalhe concreto do qual todas as features dependem (P1, P2) | alto | baixa (30 linhas) | médio (toca as 4 features) | **1** |
| `config` | modelos físicos, URLs e chaves de provider (P3, P4, P5) | alto | baixa | baixo | **2** (acompanha a 1) |
| `compose.yaml` (serviço `app`) | credenciais dos providers no ambiente do container (P4) | alto (segurança) | baixa | baixo | **3** |
| features (4) | escolhem o provider (P1) | médio | baixa cada | baixo cada, protegido pela caracterização | **4** (uma por vez, piloto primeiro) |
| `report` | execução síncrona em lotes (P7) | alto | alta | alto | **fora da v2** |
| `suggestion` | sem streaming (P8) | médio | média | médio | **fora da v2** |
| `tickets` | no limite da régua | baixo | baixa | baixo | **não refatorar** (sem dor comprovada) |
| `schemas` | DTO estável | nenhum | — | — | **não refatorar** |

Prioridade = impacto do problema na meta da v2, ponderado pelo risco de mexer. Os problemas de execução (P6–P9) são reais, mas pertencem a passos posteriores; atacá-los agora misturaria duas mudanças e impediria saber qual delas quebrou um teste.

---

## 6. Componentes-alvo (matriz de referência para a implementação)

| Componente | Problema | Evidência | Estratégia | Resultado esperado | Critério de conclusão |
|---|---|---|---|---|---|
| `llm.py` | concreto, 2 SDKs, Ca=4 | D=0,80, zona de dor | **substituição progressiva**: cada feature migra para o contrato; ao fim, o arquivo é removido | não existe mais | `llm` ausente do CSV; `git ls-files app/helpdesk/llm.py` vazio |
| `ports.py` (novo) | — (introduz a abstração) | — | **inversão de dependência**: `Protocol` com uma operação | contrato estável usado pelas 4 features e pelo adapter | A=1,00; Ca = 5 (4 features + adapter); Ce = 0 |
| `adapters/gateway.py` (novo) | — (absorve a comunicação) | — | **encapsulamento** do único cliente HTTP do gateway | único componente que fala com a IA | único import de SDK em `app/helpdesk`; Ca = 1 (`main`); fora da zona de dor |
| `classification.py` | escolhe provider e modelo | `call_openai(config.CLASSIFICATION_MODEL, ...)` | **composição + DIP**: recebe o contrato por parâmetro; pede a capacidade `ticket-classification` | Ce = {ports, schemas} | 13 testes F1 verdes; sem import de `llm`/`config` |
| `extraction.py` | idem | `call_openai(config.EXTRACTION_MODEL, ...)` | idem; capacidade `order-extraction` | Ce = {ports, schemas} | 9 testes F4 verdes |
| `suggestion.py` | idem | `call_anthropic(config.SUGGESTION_MODEL, ...)` | idem; capacidade `reply-suggestion` | Ce = {ports, schemas} | 4 testes F2 verdes |
| `report.py` | idem | `call_anthropic(config.REPORT_MODEL, ...)` | idem; capacidade `topics-report`; lotes e ordem inalterados | Ce = {ports, schemas, tickets, config} | 6 testes F3 verdes |
| `config.py` | modelos, URLs, chaves de provider | `config.py:3-13` | **redução de responsabilidades**: sai o que é do gateway; entram URL e chave do gateway | só parâmetros da aplicação | FF7, FF8; Ca ≤ 3 |
| `main.py` | não compõe nada | — | **ponto de composição** (Composition Root) | instancia o adapter e o entrega às features | único importador de `adapters.gateway` |
| `compose.yaml` (`app`) | `env_file: .env` com chaves dos providers | `compose.yaml` | **isolamento de credenciais** | `app` recebe só `GATEWAY_URL` e `GATEWAY_API_KEY` | FF9 |

Não são alvos: `schemas`, `tickets`, `provider-fake/`, `edge/`, `data/`, `tests/characterization/`.

---

## 7. Alternativas arquiteturais consideradas

### 7.1 Estratégias por componente

| Componente | Problema | Estratégias consideradas | Escolhida | Justificativa |
|---|---|---|---|---|
| `llm` | concreto no centro | A (abstração), B (reduzir Ca), D (inverter), E (composição) | **D + E** | só a inversão tira o concreto do caminho das features; reduzir Ca sem inverter só move o problema |
| `config` | detalhes voláteis | B, C (reduzir dependências) | **C** | os dados voláteis saem para o gateway; não se cria abstração sobre constantes |
| features | dependem do provider | A, D, E | **E** (recebem o contrato) | é a menor mudança que faz a dependência apontar para a abstração |
| `schemas` | D=1 | A | **nenhuma** | interface sobre DTO seria artificial (Goodhart) |
| `tickets` | no limite | A, D | **nenhuma** | não há dor comprovada; abstrair só para a métrica é proibido |

Legenda: A = introduzir abstração; B = reduzir acoplamento aferente; C = reduzir dependências; D = inverter dependências; E = composição em vez de herança/acesso global.

### 7.2 Alternativas de arquitetura-alvo

- **Alt 1, encapsulamento centralizado.** `llm.py` vira um cliente do gateway com `complete(capability, prompt)`; as features continuam importando esse módulo concreto.
- **Alt 2, contrato abstrato + adapter do gateway.** Um `Protocol` define a operação de que as features precisam; um adapter concreto o implementa; `main` compõe.
- **Alt 3, contratos por capacidade.** Um `Protocol` por feature (`Classifier`, `ReplySuggester`, ...), cada um com seu adapter ou com um adapter que implementa todos.

| Critério | Alt 1 | Alt 2 | Alt 3 |
|---|---|---|---|
| Simplicidade | **alta** (1 arquivo) | alta (2 arquivos novos, 1 removido) | baixa (4 contratos, tipos próprios) |
| Acoplamento | features → concreto | features → abstração | features → abstrações |
| Testabilidade | exige monkeypatch do módulo | qualquer objeto com `complete` serve | idem, com mais dublês |
| Modificabilidade | trocar o cliente afeta as 4 features | troca restrita ao adapter e a `main` | idem Alt 2, mais arquivos a manter |
| Extensibilidade | baixa | média (novo método ou novo `Protocol` quando houver necessidade real, como streaming) | alta, mas especulativa |
| Compatibilidade com o desafio | **não atende** ("nenhuma feature pode importar o componente do gateway") | **atende** | atende |
| Complexidade de implementação | mínima | baixa | média |
| Impacto projetado nas métricas | o cliente fica com Ca=4, I=0,20, D=0,80: **continua na zona de dor** | `ports` A=1, D=0; adapter fora da zona de dor (seção 14) | igual à Alt 2 se os contratos ficarem num módulo; mais componentes se separados |
| Riscos | nenhum novo, mas não resolve P2 | `Protocol` com uma só implementação parecer cerimônia | abstrações sem consumidor distinto; fragmentação |

**Selecionada: Alt 2.** A Alt 1 é a mais simples, mas viola o requisito obrigatório e mantém o problema P2 (o concreto continua no centro). A Alt 3 resolveria, mas as quatro features precisam da mesma operação ("dada uma capacidade e um prompt, devolva texto"): separar contratos não segrega nada que hoje seja diferente. O ISP é atendido pela Alt 2 porque o contrato tem **uma** operação, e todas as features a usam.

---

## 8. Arquitetura proposta (hipótese a validar no piloto)

### 8.1 Visão geral e fluxo de execução

```mermaid
flowchart TD
    C[Cliente HTTP] --> E[edge nginx 30s]
    E --> M[FastAPI main]
    M --> F[features: classification, suggestion, report, extraction]
    F -->|chama complete| P{{Contrato LanguageModel em ports}}
    P -.implementado por.-> A[adapters.gateway]
    A -->|HTTP, chave do gateway| G[gateway LiteLLM Proxy]
    G -->|FAKE_OPENAI_KEY| PO[provider-fake openai]
    G -->|FAKE_ANTHROPIC_KEY| PA[provider-fake anthropic]
    style P fill:#d4edda,stroke:#1e8449
    style A fill:#d6eaf8,stroke:#2471a3
    style G fill:#d6eaf8,stroke:#2471a3
```

### 8.2 Direção das dependências de código, contratos e infraestrutura

```mermaid
flowchart BT
    subgraph Nucleo[Política: features e contrato]
        F1[classification]
        F2[suggestion]
        F3[report]
        F4[extraction]
        PORT[ports.LanguageModel Protocol]
        S[schemas]
        T[tickets]
    end
    subgraph Infra[Detalhe: infraestrutura]
        AD[adapters.gateway]
        CFG[config: URL e chave do gateway, parâmetros]
    end
    subgraph Comp[Composição]
        MAIN[main]
    end
    F1 --> PORT
    F2 --> PORT
    F3 --> PORT
    F4 --> PORT
    AD --> PORT
    AD --> CFG
    MAIN --> AD
    MAIN --> F1
    MAIN --> F2
    MAIN --> F3
    MAIN --> F4
    style PORT fill:#d4edda,stroke:#1e8449
    style MAIN fill:#fdebd0,stroke:#ca6f1e
```

- **Contrato** (`ports.py`): definido do lado de quem usa, no vocabulário das features (capacidade, prompt, texto). Não menciona HTTP, SDK, provider ou modelo.
- **Detalhes de infraestrutura** (`adapters/gateway.py`, `config.py`, serviço `gateway`): sabem que existe um gateway OpenAI-compatível, URL e chave.
- **Ponto de composição** (`main.py`): o único lugar que conhece contrato **e** implementação; cria o adapter uma vez e o entrega às features.
- **Execução × dependência:** em execução, a chamada vai da feature ao adapter; no código, ambos apontam para `ports`. A seta da feature para a infraestrutura deixou de existir.

### 8.3 Inversão de dependência (antes × depois)

```mermaid
flowchart LR
    subgraph Antes
        A1[classification] -->|import| A2[llm concreto]
        A2 -->|import| A3[SDK openai]
    end
    subgraph Depois
        B1[classification] -->|import| B2[ports.LanguageModel]
        B3[adapters.gateway] -->|import e implementa| B2
        B3 -->|import| B4[SDK openai]
        B5[main] -->|cria e injeta| B3
    end
```

### 8.4 Composição da aplicação

```mermaid
sequenceDiagram
    participant U as uvicorn
    participant Main as main (Composition Root)
    participant Ad as GatewayLanguageModel
    participant F1 as classification
    U->>Main: importa helpdesk.main
    Main->>Ad: cria uma instância (lê config.GATEWAY_URL e GATEWAY_API_KEY)
    Note over Main: guarda a instância em uma variável do módulo
    U->>Main: POST /tickets/classification
    Main->>F1: classify(ticket, model=instância)
    F1->>Ad: complete("ticket-classification", prompt)
    Ad-->>F1: texto
```

Injeção por **parâmetro de função** (DI manual). Alternativas descartadas: `Depends` do FastAPI (funcionaria, mas acrescenta um mecanismo para resolver um único objeto), contêiner de DI (complexidade sem necessidade) e variável global lida pelas features (esconde a dependência).

### 8.5 Comunicação com o gateway

```mermaid
sequenceDiagram
    participant F1 as classification
    participant Ad as adapters.gateway
    participant G as gateway
    participant P as provider-fake
    F1->>Ad: complete("ticket-classification", "TASK: classify ...")
    Ad->>G: POST /v1/chat/completions model=ticket-classification (chave do gateway)
    G->>G: resolve a capacidade para gpt-fake-large no provider openai
    G->>P: POST /openai/v1/chat/completions (FAKE_OPENAI_KEY)
    P-->>G: resposta
    G-->>Ad: resposta no formato OpenAI
    Ad-->>F1: choices[0].message.content
```

Para `reply-suggestion` e `topics-report`, o gateway traduz para a API Anthropic do provider-fake. Essa tradução é a principal incerteza técnica e será validada no Passo 07 (seção 12.5).

---

## 9. Estratégias de refatoração por componente

| Componente | Responsabilidade hoje | Responsabilidade na v2 | Como chegar lá |
|---|---|---|---|
| `classification`, `extraction` | montar a chamada, escolher provider/modelo, validar | montar o prompt, pedir a capacidade, validar e mapear para 502 | trocar `llm.call_openai(config.X_MODEL, task, text)` por `model.complete(CAPABILITY, f"TASK: {task}\n{text}")`; `llm.parse_json` por `json.loads` |
| `suggestion` | idem, via Anthropic | montar o prompt e pedir a capacidade | idem |
| `report` | lotes, chamada, agregação, ordenação | idem, sem saber de provider/modelo | só a linha da chamada muda; laço, tamanho de lote e ordenação ficam idênticos |
| `llm` | clientes de SDK, `parse_json` | — | removido no fim (incremento 8); `parse_json` era `json.loads` e volta a ser chamado diretamente |
| `config` | chaves, URLs, modelos, limites, arquivo de tickets | `GATEWAY_URL`, `GATEWAY_API_KEY` (do ambiente), `TICKETS_FILE`, `TICKETS_PER_CALL` | remover em etapas o que perde o último consumidor |
| `main` | rotas | rotas + composição | criar o adapter e passá-lo às features |

**Destino de `llm.py`.** Ele é **substituído progressivamente**, não transformado. Transformar `llm.py` no contrato misturaria nomes e responsabilidades (o arquivo hoje é concreto, com SDKs) e quebraria as features ainda não migradas. Reorganizá-lo como adapter também misturaria as duas fases. Na substituição, o código novo nasce ao lado, cada feature migra em um incremento protegido pelos testes e o antigo morre quando não tem mais quem o importe (padrão Strangler Fig em pequena escala).

**Prompt fica na feature.** O texto `TASK: classify` é a instrução da feature para o modelo e faz parte do comportamento caracterizado. Deixá-lo no adapter faria a infraestrutura conhecer o vocabulário de cada feature. O custo é repetir um f-string de uma linha em quatro lugares, e qualquer desvio é detectado pela caracterização.

---

## 10. Contratos e abstrações

### 10.1 Contrato proposto (decisão provisória, confirmada no piloto)

```python
# app/helpdesk/ports.py  (será criado no Passo 08, não agora)
from typing import Protocol


class LanguageModel(Protocol):
    def complete(self, capability: str, prompt: str) -> str:
        """Executa a capacidade lógica sobre o prompt e devolve o texto gerado."""
        ...
```

| Questão | Decisão | Motivo |
|---|---|---|
| O que a feature fornece | capacidade lógica + prompt completo | é tudo o que as 4 features usam hoje (`task` e `content` viram o prompt) |
| O que volta | `str` | as 4 features consomem só o texto; F1/F3/F4 fazem `json.loads` |
| Capacidade como `str`, `Enum` ou objeto | `str`, como constante em cada feature (`CAPABILITY = "ticket-classification"`) | cada feature dona do seu nome; um `Enum` central reacoplaria as features num módulo concreto; erro de digitação é detectado pelo gateway (400) e pelos testes da rota |
| Objetos de requisição/resposta | não | nenhum consumidor precisa de mais que texto (YAGNI) |
| Uso de tokens | não | ninguém consome hoje; a contabilidade é responsabilidade do gateway (governança na `main`) |
| Erros próprios | não na v2 | na v1, nenhuma feature captura exceção de provider; elas viram 500 ou 504 na borda. Manter isso preserva o comportamento. Quando houver fallback ou mensagem de erro específica (na `main`), introduzir um `ModelUnavailable` no `ports` |
| `Protocol` ou `ABC` | `Protocol` | tipagem estrutural: qualquer dublê com `complete` serve em teste, sem herança obrigatória. O adapter herda explicitamente do `Protocol` (PEP 544 permite) para declarar a intenção e permitir checagem estática |
| Síncrono ou assíncrono | síncrono | as rotas são `def` e a v2 preserva os modos de execução |
| Genérico ou específico | uma operação genérica orientada a capacidade | as 4 features têm a mesma forma de chamada; ver Alt 3 |
| Orientado a capacidade ou a provider | capacidade | é o que tira o provider do vocabulário da feature (P1) |
| Streaming | não agora | quando a F2 precisar (na `main`), criar uma operação ou `Protocol` separado usado só por ela (ISP), sem alterar o `complete` |

### 10.2 Negócio × infraestrutura

| Pertence às features (negócio) | Pertence à infraestrutura |
|---|---|
| texto do prompt (`TASK: ...`) | URL e chave do gateway |
| nome da capacidade | modelo físico, provider, URL e chave do provider |
| validação de categoria, prioridade e formato do pedido (502) | `max_tokens` por capacidade (ver 12.3) |
| tamanho do lote, agregação e ordenação da F3 | formato do protocolo (OpenAI-compatível), retries e timeouts do cliente |

### 10.3 SOLID aplicado

| Princípio | Violação na v1 | Como a v2 atende |
|---|---|---|
| SRP | `llm` mistura 2 clientes + parse; `config` mistura segredos, URLs, modelos e regra de lote | adapter só transporta; `config` só parâmetros da aplicação |
| OCP | trocar provider de uma feature exige editar a feature | trocar modelo ou provider é configuração do gateway |
| LSP | — | qualquer implementação de `complete` precisa devolver o texto do modelo sem alterá-lo (o golden da F2 é byte a byte) |
| ISP | features veem `call_openai`, `call_anthropic` e `parse_json` | contrato com uma operação |
| DIP | features dependem de `llm` concreto | features e adapter dependem de `ports` |

### 10.4 Ports and Adapters, sem cerimônia

O contrato é uma **porta de saída** (driven port) no sentido de Cockburn; o adapter do gateway é o adaptador secundário; FastAPI em `main` faz o papel do adaptador primário. Não adotamos camadas (domain/application/infrastructure), entidades, casos de uso, repositórios ou factories: a aplicação tem quatro funções de ~10 linhas, e nenhum desses elementos resolveria um problema comprovado. A Clean Architecture contribui a regra da dependência; não a estrutura de pastas.

---

## 11. Capacidades lógicas

**Modelo físico × capacidade.** Pedir `gpt-fake-large` é escolher fornecedor, família e tamanho, uma decisão operacional. Pedir `ticket-classification` é declarar a intenção de negócio; quem decide qual modelo atende é o gateway. Assim, trocar o modelo (P3) passa a ser configuração do gateway, sem rebuild da `app`.

| Capacidade lógica | Feature | Modelo atual (v1) | Modelo primário na v2 | Justificativa (Passo 03) |
|---|---|---|---|---|
| `ticket-classification` | F1 | `gpt-fake-large` | `gpt-fake-large` | mantém o modelo caracterizado; GPT L ≡ Claude L na F1 |
| `reply-suggestion` | F2 | `claude-fake-large` | `claude-fake-large` | o texto do golden é byte a byte; mini reduz ~44% e reordena frases |
| `topics-report` | F3 | `claude-fake-large` | `claude-fake-large` | mantém o caracterizado; 150 tickets cabem nos 8.000 tokens |
| `order-extraction` | F4 | `gpt-fake-large` | `gpt-fake-large` | mini devolve `product: null` em 6/6 (incorreção silenciosa) |

- **Nomes:** os quatro sugeridos são mantidos. Descrevem o resultado de negócio (substantivo + objeto), não o provider, o tamanho ou a técnica (`gpt-`, `-large`, `-fast` ficam proibidos nos nomes). São estáveis enquanto a feature existir; mudar o modelo não muda o nome.
- **Relação com a regra de negócio:** uma capacidade por feature, porque cada feature tem requisitos de qualidade diferentes (F4 não tolera mini, F1 tolera). Compartilhar uma capacidade entre F1 e F4 só porque usam o mesmo modelo hoje acoplaria decisões futuras.
- **Destinos equivalentes futuros:** o gateway pode listar mais de um destino sob o mesmo nome lógico (fallback, `mini` onde o Passo 03 permitir). Isso é da `main`; a v2 configura um destino por capacidade.
- **Duplicação aceitável:** o nome existe em dois lugares (feature e configuração do gateway). Um nome inexistente falha alto (erro do gateway) e é pego pelos testes de rota.

---

## 12. Introdução do AI Gateway

### 12.1 Conceitos

| Elemento | O que é | No projeto |
|---|---|---|
| Reverse proxy | repassa HTTP sem entender o conteúdo | `edge` (nginx) |
| API Gateway | entrada de APIs: roteamento, autenticação, limites por rota | não há (o `edge` faz o papel mínimo) |
| AI Gateway | proxy que entende chamadas a modelos: API padronizada, roteamento por nome lógico, credenciais centralizadas, retry/fallback, custo e limites por chave | serviço `gateway` proposto |
| SDK de provider | biblioteca cliente de um fornecedor | `openai`, `anthropic` em `llm.py` |
| Biblioteca de abstração | padroniza providers dentro do processo da aplicação (ex.: LiteLLM SDK) | descartada: credenciais e modelos continuariam na `app` |

### 12.2 Alternativas

| Alternativa | Característica | Avaliação |
|---|---|---|
| SDKs diretos | integração específica por provider | é a v1; não resolve P1–P4 |
| Biblioteca de abstração na aplicação | padronização dentro do código | resolve P1, mas não P3/P4 (credenciais e modelos ficam na `app`) e não atende "todas as chamadas passam pelo gateway" |
| **AI Gateway self-hosted** | serviço separado no compose | **escolhida**: resolve P1–P4, roda local, sem custo |
| AI Gateway SaaS | serviço gerenciado externo | proibido (providers reais/serviços pagos) |

**Candidato: LiteLLM Proxy** (sugerido pelo enunciado), imagem oficial com versão fixada no Passo 07.

| Requisito | Expectativa | Validar no Passo 07? |
|---|---|---|
| Docker Compose local | serviço `gateway` com `config.yaml` montado | sim |
| Providers simulados | `api_base` por modelo apontando para `provider-fake:8090/openai/v1` e `provider-fake:8090/anthropic` | **sim, crítico** (sobretudo Anthropic) |
| Nomes lógicos | `model_name` = capacidade; `litellm_params.model` = físico | sim |
| Autenticação própria | master key do proxy como `GATEWAY_API_KEY` | sim |
| Isolamento de credenciais | chaves `FAKE_*` só no ambiente do `gateway` (`os.environ/...` no config) | sim |
| Streaming | suportado pela API OpenAI-compatível | apenas registrar; uso na `main` |
| Roteamento, retry, fallback | existem na configuração do proxy | registrar os **padrões** (retries do proxy somados aos do SDK); não configurar políticas agora |
| Budget, rate limiting, virtual keys | dependem de banco (Postgres) | **não** na v2; evitar dependência adicional |
| Dependências adicionais | nenhuma além da imagem, se usarmos só master key e config em arquivo | sim |

### 12.3 Responsabilidades do gateway na v2

Centralizar credenciais dos providers; resolver capacidade → modelo físico e provider; expor uma API única OpenAI-compatível; traduzir para a API Anthropic quando necessário; manter `max_tokens = 2000` nas capacidades que hoje o usam (`reply-suggestion`, `topics-report`) para preservar a semântica da v1 (**provisório**: validar se o proxy aceita o parâmetro por modelo; se não, o adapter envia `max_tokens` e o limite volta a ser parâmetro da `app`).

Não fazem parte da v2: fallback, retry configurado, timeouts por capacidade, budget, rate limiting, logs de custo.

### 12.4 Separação de configurações e credenciais

| Informação | Localização atual | Localização proposta |
|---|---|---|
| Nome físico do modelo | `config.py:10-13` | configuração do gateway |
| Credencial do provider | `.env` → `app` (`config.py:3-4`) e `provider-fake` | `.env` → `gateway` e `provider-fake` |
| URL do provider | `config.py:6-7` | configuração do gateway |
| Nome da capacidade lógica | inexistente | feature (constante) e configuração do gateway |
| URL do gateway | inexistente | ambiente do `app` → `config.GATEWAY_URL` |
| Credencial do gateway | inexistente | `.env` (`GATEWAY_API_KEY`) → `app` e `gateway` |
| Parâmetros de negócio (`TICKETS_PER_CALL`, `TICKETS_FILE`) | `config.py` | `config.py` |
| `MAX_OUTPUT_TOKENS` | `config.py:15` | gateway (provisório, ver 12.3) |

**Princípio:** a implementação não deve mudar quando muda o ambiente (12-factor, "config"). O que varia por ambiente ou por decisão operacional (modelo, chave, URL) fica fora do código; o que é regra da aplicação (lote de 150) fica nele.

**Como garantir:**
- serviço `app` deixa de usar `env_file: .env` (que injeta **todas** as variáveis, inclusive as `FAKE_*`) e passa a declarar `environment:` só com `GATEWAY_URL` e `GATEWAY_API_KEY` (interpolação `${GATEWAY_API_KEY}` lida do `.env` pelo compose, sem levar as demais variáveis ao container);
- nenhum volume monta `.env` ou a configuração do gateway no `app`;
- `.env.example` ganha `GATEWAY_API_KEY` (valor fictício);
- verificação por FF7, FF8 e FF9 (seção 16).

### 12.5 Questões para o Passo 07

1. O LiteLLM aceita `api_base` customizado para Anthropic e chega ao endpoint do fake (`/anthropic/v1/messages`)?
2. O texto devolvido para `reply-suggestion` é **byte a byte** igual ao golden `expected/reply_suggestion_TK-00042.json`?
3. Qual `max_tokens` o proxy envia ao Anthropic quando o cliente não informa? Dá para fixar por modelo?
4. Quantas tentativas o proxy faz por padrão em erro? (Somadas às 2 do SDK `openai` no adapter, podem multiplicar chamadas; em modo `normal` não afeta os testes.)
5. O proxy adiciona latência relevante à F2 (~16 s) ou à F3 (~10 s), perto dos 30 s da borda?
6. O `/admin/calls` do fake identifica a origem da chamada? Se não, que log do gateway prova que todas as chamadas passaram por ele?
7. O proxy precisa de banco para a master key? (Esperado: não.)
8. Vale isolar a rede do `app` do `provider-fake` (o `app` não alcança o fake), como prova física de O6? Decisão no ADR 0003, se for adotado.

---

## 13. Organização dos componentes

| Critério | Opção 1: `ports.py` + `adapters/gateway.py` | Opção 2: `ports/llm.py` + `adapters/gateway.py` | Opção 3 (plana): `ports.py` + `gateway.py` |
|---|---|---|---|
| Responsabilidades | claras | claras | claras, papel do adapter só pelo nome |
| Clareza | o caminho diz o papel | idem | menor |
| Complexidade | 1 pacote | 2 pacotes | nenhum pacote novo |
| Componentes | +2 | +2 | +2 |
| Métricas | idênticas (o pacote não conta) | idênticas | idênticas |
| Evolução | outro adapter cabe em `adapters/` | um contrato por arquivo | mistura adapters e features no mesmo nível |
| Adequação ao tamanho | boa | excessiva para 1 contrato | boa |

**Decisão:** Opção 1.

```text
app/helpdesk/
├── __init__.py
├── main.py            rotas + ponto de composição
├── schemas.py         inalterado
├── config.py          GATEWAY_URL, GATEWAY_API_KEY, TICKETS_FILE, TICKETS_PER_CALL
├── classification.py  CAPABILITY = "ticket-classification"; recebe LanguageModel
├── suggestion.py      CAPABILITY = "reply-suggestion"
├── extraction.py      CAPABILITY = "order-extraction"
├── report.py          CAPABILITY = "topics-report"
├── tickets.py         inalterado
├── ports.py           LanguageModel (Protocol)
└── adapters/
    ├── __init__.py
    └── gateway.py     GatewayLanguageModel: SDK openai apontado para o gateway
```

`llm.py` sai. `app/requirements.txt` perde `anthropic` no incremento 8. O adapter usa o SDK `openai` (já dependência; o gateway expõe API OpenAI-compatível) em vez de escrever um cliente HTTP à mão. Os padrões do SDK (timeout de 600 s, 2 retries) ficam iguais aos da v1 de propósito: mudá-los é política de resiliência, assunto da `main`.

---

## 14. Impacto esperado nas métricas

### 14.1 Grafo projetado (v2 completa, 19 arestas)

```mermaid
flowchart TD
    main --> classification
    main --> extraction
    main --> report
    main --> suggestion
    main --> schemas
    main --> AG[adapters.gateway]
    classification --> ports
    classification --> schemas
    extraction --> ports
    extraction --> schemas
    suggestion --> ports
    suggestion --> schemas
    report --> ports
    report --> schemas
    report --> tickets
    report --> config
    tickets --> config
    AG --> ports
    AG --> config
    style ports fill:#d4edda,stroke:#1e8449
    style config fill:#f8d7da,stroke:#c0392b
    style schemas fill:#fff3cd,stroke:#b7950b
```

### 14.2 Projeção

**Método:** os valores abaixo foram calculados com a própria ferramenta (`metrics/measure.py`), sem alterá-la, sobre um **esqueleto descartável** que contém só os imports e as classes previstos (fora do repositório, não versionado). São **projeções**: confirmam a aritmética do desenho, não o código que o agente vai escrever.

| Componente | D atual medido | Ca proj. | Ce proj. | I proj. | A proj. | D proj. | Zona de dor proj. | Justificativa |
|---|---|---|---|---|---|---|---|---|
| `adapters.gateway` | — (novo) | 1 | 2 | 0.67 | 0.00 | 0.33 | não | só `main` o importa; depende de `ports` e `config` |
| `classification` | 0.25 | 1 | 2 | 0.67 | 0.00 | 0.33 | não | perde `config` e `llm`, ganha `ports` |
| `config` | 1.00 | 3 | 0 | 0.00 | 0.00 | 1.00 | **sim** | Ca cai de 6 para 3; continua concreto e estável |
| `extraction` | 0.25 | 1 | 2 | 0.67 | 0.00 | 0.33 | não | idem F1 |
| `llm` | 0.80 | — | — | — | — | — | — | removido |
| `main` | 0.00 | 0 | 6 | 1.00 | 0.00 | 0.00 | não | ganha `adapters.gateway` |
| `ports` | — (novo) | 5 | 0 | 0.00 | 1.00 | 0.00 | não | abstrato e estável: está **na** Main Sequence |
| `report` | 0.20 | 1 | 4 | 0.80 | 0.00 | 0.20 | não | troca `llm` por `ports`, mantém `config` e `tickets` |
| `schemas` | 1.00 | 5 | 0 | 0.00 | 0.00 | 1.00 | **sim** | inalterado; exceção candidata |
| `suggestion` | 0.25 | 1 | 2 | 0.67 | 0.00 | 0.33 | não | idem F1 |
| `tickets` | 0.50 | 1 | 1 | 0.50 | 0.00 | 0.50 | não (no limite) | inalterado |

Projeção do **estado pós-piloto** (só F1 migrada): `llm` Ca=3, I=0,25, D=0,75 (ainda na zona de dor); `config` Ca=6, D=1,00; `ports` Ca=2, A=1, D=0,00; `adapters.gateway` e `classification` como acima; demais iguais à v1. São 22 arestas.

### 14.3 O que a simulação revelou

1. **D das features piora (0,25 → 0,33) enquanto a arquitetura melhora.** Elas passam a ter menos dependências (Ce 3 → 2), e isso as aproxima do centro. É um caso concreto de por que melhorar a métrica não é o objetivo. Não adicionaremos dependências para "consertar" isso.
2. **O adapter depende de como é escrito.** Se só usasse tipagem estrutural e recebesse URL e chave de `main`, teria Ca=1, Ce=0, D=1,00: entraria na **zona de dor**, e a regra do desafio proíbe declará-lo exceção. Lendo `config` sozinho (como `llm.py` faz hoje), fica com I=0,50, D=0,50 (no limite). Com herança explícita de `LanguageModel` e leitura de `config`, fica com D=0,33. Escolhemos esta última **por razões de código**: a herança explícita declara a conformidade e permite checagem estática; ler a própria configuração mantém `main` simples. O ganho métrico é consequência, não motivo, e deve ser revisado no piloto (risco R3).
3. **`config` continua na zona de dor na v2.** Perde tudo o que era volátil (modelos, URLs, chaves de provider), mas segue concreto, com Ca=3. O ADR 0001 o recusou como exceção **pelo conteúdo volátil**, e essa razão desaparece na v2. Para a `main` final há duas saídas legítimas, a decidir no Passo 16 com a medição real: (a) revisar o ADR 0001 e declará-lo naturalmente estável; (b) dissolvê-lo, levando cada constante ao seu único consumidor, se isso aumentar a coesão. Não é requisito da v2.
4. **`ports` com A=1 e Ca=5 é a evidência estrutural da inversão.** Se o agente criar o `Protocol` e as features não o importarem, Ca cai e o critério reprova.

---

## 15. Critérios de conclusão da `v2-decoupled`

### 15.1 Comportamentais
- B1. Os 32 testes de caracterização passam (FF1).
- B2. `tests/characterization/` idêntico à `v1-coupled` (FF2).
- B3. As 4 rotas e o `/health` existem com os mesmos métodos e caminhos.
- B4. Contratos de entrada e saída iguais (garantido por B1 e por `schemas.py` sem diff).
- B5. Rotas continuam `def` (síncronas); nenhuma resposta em stream.
- B6. Capacidades mapeadas para os mesmos modelos `large` da v1.

### 15.2 Estruturais
- S1. Nenhuma feature importa `openai`, `anthropic`, `llm` ou `adapters` (FF5, FF6).
- S2. Um único componente fala com o gateway: `adapters.gateway`, único import de SDK em `app/helpdesk` (FF5).
- S3. Só `main` importa `adapters.gateway` (FF6; Ca = 1 no CSV).
- S4. Sem ciclos (a ferramenta reporta).
- S5. Metas quantitativas da 15.4 atendidas.

### 15.3 De infraestrutura
- I1. Serviço `gateway` no `compose.yaml`, com ADR 0003 aceito.
- I2. Todas as chamadas aos modelos passam pelo gateway (FF10).
- I3. A aplicação usa capacidades lógicas e não conhece modelos físicos (FF7).
- I4. Credenciais dos providers só no `gateway` e no `provider-fake` (FF8, FF9).
- I5. A aplicação usa uma credencial própria do gateway (`GATEWAY_API_KEY`).

### 15.4 Quantitativos (fundamentados na v1)

| Componente | Situação atual (medida) | Meta arquitetural | Meta da métrica (v2) | Evidência necessária |
|---|---|---|---|---|
| `llm` | Ca=4, D=0,80, zona de dor | responsabilidade absorvida pelo adapter | componente inexistente | CSV sem `llm` |
| `ports` | não existe | contrato estável usado por todas as features | A = 1,00; Ce = 0; Ca ≥ 5 (4 features + adapter) | CSV + arestas |
| `adapters.gateway` | não existe | único concreto da IA, composto só em `main` | Ca = 1 (`main`); fora da zona de dor | CSV + FF6 |
| features (4) | D 0,20–0,25; dependem de `llm` e `config` (F1, F2, F4) | dependem do contrato | Ce ⊆ {ports, schemas} para F1, F2, F4; {ports, schemas, tickets, config} para F3; fora da zona de dor | arestas no relatório |
| `config` | Ca=6, D=1,00 | só parâmetros da aplicação | Ca ≤ 3; zona de dor **aceita na v2** com justificativa (14.3) | CSV + FF7/FF8 |
| `schemas` | D=1,00 | inalterado | inalterado | `git diff` vazio |
| `main` | Ce=5 | ponto de composição | I = 1,00 | CSV |
| Global | 3 componentes na zona de dor | nenhum componente **novo** na zona de dor | zona de dor ⊆ {config, schemas} | CSV |

Não usamos metas percentuais uniformes ("reduzir D em 50%"): cada meta deriva do problema daquele componente.

**Critério da `main` final** (registrado aqui para não ser esquecido, não exigido na v2): nenhum componente na zona de dor, exceto os declarados naturalmente estáveis no ADR 0001 com justificativa; features e o componente do gateway nunca são exceção. A arquitetura proposta é compatível: os únicos candidatos são `schemas` e `config` (14.3).

---

## 16. Fitness Functions arquiteturais

Uma fitness function é uma verificação objetiva, preferencialmente automatizada, de uma característica arquitetural (Ford, Parsons, Kua, *Building Evolutionary Architectures*). Aqui elas são os comandos que já temos, mais buscas simples. Não construiremos plataforma.

| ID | Característica | Mecanismo | Evidência esperada | Quando |
|---|---|---|---|---|
| FF1 | Comportamento | testes de caracterização (README, "Como rodar", opção B) | `32 passed` | antes e depois de cada incremento |
| FF2 | Integridade da suíte | diff Git contra a `v1-coupled` | sem saída, código 0 | sempre |
| FF3 | Diretórios protegidos | diff Git contra a `v1-coupled` | sem saída | sempre |
| FF4 | Acoplamento estrutural | ferramenta de métricas | tabela comparada com a 15.4 | após cada incremento de código |
| FF4b | Régua intacta | diff Git contra o commit do Passo 05 | sem saída | sempre |
| FF5 | Isolamento tecnológico | busca de imports de SDK | só `adapters/gateway.py` (e `llm.py` enquanto existir) | após cada incremento |
| FF6 | Fronteira do concreto | busca nas features migradas | sem saída | idem |
| FF7 | Sem modelos físicos | busca no código | sem saída | ao final (incremento 8) |
| FF8 | Sem credenciais e URLs de provider no código | busca no código | sem saída | ao final |
| FF9 | Sem credenciais no ambiente do `app` | ambiente do container e compose resolvido | nenhuma variável `FAKE_*`; `app` sem `env_file`, só `GATEWAY_*` | ao final (incremento 9) |
| FF10 | Tudo pelo gateway | `/admin/calls` × log do gateway | totais iguais (método exato definido no Passo 07, questão 12.5-6) | ao final |
| FF11 | Modo de execução | busca de rotas assíncronas | sem saída | ao final |

```bash
# FF1 (Docker, sem instalar nada no host)
docker run --rm -v "${PWD}:/w" -w /w -e PYTHONDONTWRITEBYTECODE=1 \
  -e HELPDESK_BASE_URL=http://host.docker.internal:8000 \
  -e PROVIDER_ADMIN_URL=http://host.docker.internal:8090 \
  python:3.12-slim sh -c "pip install -q -r tests/requirements.txt && python -m pytest tests/characterization -v -p no:cacheprovider"

# FF2 e FF3
git diff --exit-code v1-coupled -- tests/characterization/
git diff --exit-code v1-coupled -- provider-fake/ edge/ data/

# FF4 (NOME = pre-piloto, piloto-f1, v2-decoupled ...)
python metrics/measure.py --source app/helpdesk --name NOME --no-plot

# FF4b (COMMIT_PASSO_05 = hash do commit que versionou a ferramenta)
git diff --exit-code COMMIT_PASSO_05 -- metrics/*.py tests/metrics/

# FF5
grep -rnE "^\s*(from|import) (openai|anthropic)" app/helpdesk

# FF6 (listar só as features já migradas)
grep -nE "adapters|gateway|\bllm\b|\bconfig\b" app/helpdesk/classification.py
grep -rlE "adapters" app/helpdesk --include=*.py      # esperado: só main.py e o próprio adapters/

# FF7 e FF8
grep -rnE "gpt-fake|claude-fake" app/
grep -rnE "FAKE_OPENAI_KEY|FAKE_ANTHROPIC_KEY|sk-fake-openai|sk-ant-fake|provider-fake" app/

# FF9
docker compose exec app env | grep -E "FAKE_|sk-fake|sk-ant"
docker compose config                                  # conferir o bloco do serviço app

# FF10
curl -X POST http://localhost:8090/admin/reset
# rodar FF1, depois comparar:
curl http://localhost:8090/admin/calls
docker compose logs gateway

# FF11
grep -n "async def" app/helpdesk/main.py
```

Os comandos rodam na raiz do repositório, em Git Bash ou dentro de um container `python:3.12-slim` (o PowerShell não tem `grep`). No FF6, `config` some das features F1, F2 e F4; a F3 continua importando `config` (para `TICKETS_PER_CALL`) e deve ser verificada só quanto a `adapters`, `gateway` e `llm`.

FF5 a FF9 não rodam agora: dependem de uma implementação que ainda não existe. Na v1 elas falhariam, o que é esperado e documenta o ponto de partida.

---

## 17. Seleção e planejamento do piloto

### 17.1 Seleção

| Componente | Complexidade | Risco | Representatividade | Facilidade de validação | Adequação ao piloto |
|---|---|---|---|---|---|
| `classification` (F1) | baixa (15 linhas) | baixo; 13 testes, 1,1 s cada | alta: mesma forma de F4 e F2 (prompt → texto → validação) e caminho OpenAI | alta (~15 s de suíte) | **alta** |
| `extraction` (F4) | baixa | **médio**: regra mais sensível (incorreção silenciosa) | alta (igual à F1) | alta | média: melhor migrar depois que o padrão for provado |
| `suggestion` (F2) | mínima (7 linhas) | médio: texto byte a byte via tradução Anthropic | média (sem validação; não exercita o 502) | baixa (16 s por caso) | média |
| `report` (F3) | alta (lotes, `tickets`, agregação) | alto | baixa (forma única) | média (10 s por caso) | baixa |
| `llm` | baixa | alto (as 4 features dependem dele) | não valida a hipótese (refatorá-lo é a Alt 1) | — | **inadequado** |

**Selecionado: F1, `classification.py`.** Não pela simplicidade em si, mas porque:
- valida as três partes da hipótese de uma vez: contrato, adapter e composição em `main`;
- mantém a validação de negócio (o 502) na feature, o que mostra se a fronteira negócio × infraestrutura está certa;
- o resultado vale para F4 (idêntica) e F2 (a mesma chamada, sem validação).

Ressalva: a F1 não exercita o caminho Anthropic do gateway. Por isso o Passo 07 **precisa** validar `reply-suggestion` e `topics-report` diretamente no gateway antes do piloto. Se não validar, a seleção é revista.

### 17.2 Hipótese arquitetural
Se a F1 depender de um `Protocol` `LanguageModel` injetado por `main`, e o único concreto for um adapter do gateway, então a F1 deixa de conhecer provider, modelo e SDK **sem mudar comportamento**, e o padrão pode ser repetido nas outras três features sem alterar o contrato.

### 17.3 Estado anterior (registrar no Passo 08 antes de qualquer mudança)
- Responsabilidades: chamar `llm.call_openai(config.CLASSIFICATION_MODEL, "classify", ticket.text)`, `parse_json`, validar `CATEGORIES`/`PRIORITIES` (502), montar `Classification`.
- Dependências: `config`, `llm`, `schemas` (+ `fastapi` externo). Métricas: Ca=1, Ce=3, I=0,75, A=0, D=0,25.
- Testes que protegem: `tests/characterization/test_classification.py` (13).
- Comando de medição: `python metrics/measure.py --source app/helpdesk --name pre-piloto` (deve reproduzir os valores da `v1-coupled`).

### 17.4 Escopo
| Item | Autorizado |
|---|---|
| Componente-alvo | `app/helpdesk/classification.py` |
| Novos arquivos | `app/helpdesk/ports.py`, `app/helpdesk/adapters/__init__.py`, `app/helpdesk/adapters/gateway.py` |
| Ajustes de composição | `app/helpdesk/main.py` (criar o adapter; passar à rota de F1) |
| Ajustes de infraestrutura mínimos (separados, commit próprio) | `app/helpdesk/config.py` (acrescentar `GATEWAY_URL` e `GATEWAY_API_KEY`, sem remover nada); `compose.yaml` (acrescentar `GATEWAY_URL`/`GATEWAY_API_KEY` ao `app` e `depends_on: gateway`); `.env.example` |
| Proibido | `suggestion.py`, `extraction.py`, `report.py`, `llm.py`, `schemas.py`, `tickets.py`, `app/requirements.txt`, `tests/`, `metrics/`, diretórios protegidos, remoção de `env_file` do `app` |
| Responsabilidades a preservar | prompt `TASK: classify\n{text}`; validação e 502; mensagem do 502; formato de `Classification` |

### 17.5 Estado esperado
- `classification.classify(ticket, model: LanguageModel)` chama `model.complete("ticket-classification", f"TASK: classify\n{ticket.text}")` e `json.loads`.
- `classification` importa só `ports` e `schemas`; `main` importa `adapters.gateway`.
- Métricas projetadas: seção 14.2, estado pós-piloto.

### 17.6 Protocolo de validação
1. Confirmar a baseline: `git status` limpo, tag `v1-coupled` intacta, gateway do Passo 07 no ar.
2. Rodar FF1 (32 verdes) e FF2/FF3.
3. Medir: `--name pre-piloto`.
4. Entregar o handoff da seção 19 ao agente.
5. Revisar o diff: escopo (17.4), FF5, FF6, legibilidade.
6. Rodar FF1, FF2, FF3.
7. Medir: `--name piloto-f1`.
8. Comparar com a 14.2 (pós-piloto) e preencher a 23.
9. Analisar trade-offs e divergências.
10. Decidir: aceitar, revisar ou rejeitar (seção 20); registrar a revisão 1.1 (seção 24).

### 17.7 Aprovação e rejeição
Aprovar se: B1–B5 valem; FF2, FF3, FF4b sem diff; F1 sem `llm`/`config`; `ports` com A=1; Ca(`adapters.gateway`)=1; nenhum componente novo na zona de dor; o diff fica dentro de 17.4.
Rejeitar se: altera comportamento externo; modifica testes; cria dependências artificiais (import sem uso); extrapola o escopo; cria abstrações sem consumidor; a F1 continua sabendo de provider ou modelo; métricas incompatíveis com 14.2 sem explicação; toca diretórios protegidos.

### 17.8 Rollback
Ver seção 22. O piloto roda em branch própria; a `main` só recebe o merge após aprovação.

---

## 18. Estratégia de implementação incremental

Cada incremento termina com FF1 verde e um commit próprio, revisado antes do próximo. Nenhum incremento mistura mudança estrutural com mudança de comportamento.

| # | Passo | Objetivo | Arquivos | Pré-requisito | Alterações permitidas | Conclusão e validação | Recuperação |
|---|---|---|---|---|---|---|---|
| 0 | — | baseline | — | — | nenhuma | FF1 = 32; CSV `v1-coupled` reproduz | — |
| 1 | 07 | gateway no ar | `compose.yaml`, config do gateway, `.env.example`, ADR 0003 | plano aprovado | serviço `gateway`; `app` intocado | as 4 capacidades respondem direto no gateway com os mesmos textos do golden; FF1 verde (a `app` ainda vai direto) | remover o serviço (revert) |
| 2 | 08 | infraestrutura do piloto | `config.py` (+2 constantes), `compose.yaml` (`app` recebe `GATEWAY_*`) | 1 | só acréscimos | FF1 verde; `docker compose exec app env` mostra `GATEWAY_URL` | revert |
| 3 | 08 | **piloto F1** | `ports.py`, `adapters/`, `classification.py`, `main.py` | 2 | escopo 17.4 | 17.6 e 17.7; medição `piloto-f1` | revert do commit; seção 22 |
| 4 | 08 | revisão do plano | este documento | 3 medido | seções 23–25 | revisão 1.1 baseada em evidência | — |
| 5 | 09 | F4 `extraction` | `extraction.py`, `main.py` | 4 aprovado | igual ao piloto | 9 testes F4 + FF1; FF6 | revert |
| 6 | 09 | F2 `suggestion` | `suggestion.py`, `main.py` | 5 | idem | 4 testes F2 (byte a byte) + FF1 | revert |
| 7 | 09 | F3 `report` | `report.py`, `main.py` | 6 | só a linha da chamada e a assinatura | 6 testes F3 + FF1; laço e ordenação sem diff | revert |
| 8 | 09 | remover integrações antigas | `llm.py` (removido), `config.py` (sai chaves, URLs, modelos, `MAX_OUTPUT_TOKENS`), `app/requirements.txt` (sai `anthropic`) | 7 | só remoções | FF1, FF5, FF7, FF8; `llm` ausente do CSV | revert |
| 9 | 09 | isolar credenciais | `compose.yaml` (`app` sem `env_file`; `environment:` só `GATEWAY_*`) | 8 | só o bloco `app` | FF9; FF1 | revert |
| 10 | 09 | medir a v2 | `metrics/results/v2-decoupled.{csv,png}`, relatório | 9 | nenhuma no código | 15.4 atendida; FF10, FF11 | — |
| 11 | 09 | tag `v2-decoupled` | — | 10 e aprovação do Igor | criar a tag | todos os critérios da seção 15 | apagar a tag local antes do push |

O incremento 8 vem depois de todas as features porque `llm.py` e as constantes de provider só morrem quando o último consumidor sai. O 9 vem depois do 8 porque, enquanto `config.py` ler `FAKE_*`, tirar o `env_file` quebraria o import.

---

## 19. Handoff para o agente de IA

**Por que "refatore usando Clean Architecture" não basta:** não diz qual problema resolver, qual componente mexer, o que não pode mudar, nem como o resultado será julgado. O agente preencheria as lacunas com padrões genéricos (camadas, repositórios, factories) e não teria feedback determinístico para saber se acertou. Um bom handoff é Context Engineering: dá ao agente o contexto mínimo suficiente, um escopo fechado, restrições explícitas e critérios que **ele mesmo pode rodar**.

### 19.1 Template (usar no Passo 08, ajustando o que estiver entre colchetes)

````markdown
# Tarefa: piloto de refatoração da F1 (classificação de tickets)

## Contexto
- Projeto: helpdesk FastAPI com 4 features de IA. Objetivo desta fase: v2-decoupled,
  em que as features dependem de um contrato e só um adapter fala com o AI Gateway.
- Estado atual: v1 acoplada (tag v1-coupled). classification.py chama
  llm.call_openai(config.CLASSIFICATION_MODEL, "classify", ticket.text).
- Problemas comprovados: llm.py é concreto, usa dois SDKs e está na zona de dor
  (Ca=4, I=0.20, A=0, D=0.80); features escolhem provider pelo nome da função;
  modelo físico em config.py.
- Arquitetura proposta: docs/refactoring-plan.md, seções 8, 10 e 13.
- Gateway: serviço "gateway" (LiteLLM Proxy) em [URL], API OpenAI-compatível,
  capacidade "ticket-classification" já configurada e validada no Passo 07.

## Tarefa
- Componente: app/helpdesk/classification.py.
- Problema: a F1 conhece provider, modelo e SDK.
- Estratégia: inversão de dependência por composição.
  1. Criar app/helpdesk/ports.py com o Protocol LanguageModel
     (método complete(capability: str, prompt: str) -> str).
  2. Criar app/helpdesk/adapters/__init__.py (vazio) e adapters/gateway.py com
     GatewayLanguageModel(LanguageModel), usando o SDK openai com
     base_url=config.GATEWAY_URL e api_key=config.GATEWAY_API_KEY;
     model=capability; mensagem única de usuário com o prompt; retorna
     choices[0].message.content. Sem retries, timeouts ou fallback próprios.
  3. classification.classify(ticket, model: LanguageModel): prompt
     f"TASK: classify\n{ticket.text}", capacidade "ticket-classification",
     json.loads; validação e 502 inalterados.
  4. main.py cria uma instância do adapter e a passa a classification.classify.
- Resultado estrutural esperado: classification importa só ports e schemas;
  apenas main importa adapters.gateway.

## Entradas disponíveis
Código em app/helpdesk/; docs/refactoring-plan.md; README (Diagnóstico, Métrica);
metrics/results/v1-coupled.csv; tests/characterization/; docs/adr/0001 a 0004.

## Escopo autorizado
- Modificar: app/helpdesk/classification.py, app/helpdesk/main.py.
- Criar: app/helpdesk/ports.py, app/helpdesk/adapters/__init__.py,
  app/helpdesk/adapters/gateway.py.
- Nada além disso.

## Restrições
- Não alterar tests/, metrics/, provider-fake/, edge/, data/, compose.yaml.
- Não alterar suggestion.py, extraction.py, report.py, llm.py, schemas.py, tickets.py, config.py.
- Não mudar rotas, contratos HTTP, mensagens de erro nem o prompt.
- Rotas continuam def (síncronas). Sem streaming, retry, fallback, async.
- Não criar classes, módulos ou imports que não sejam usados.
- Não alterar a ferramenta de métricas nem seus resultados versionados.

## Critérios de conclusão (rode e cole a saída)
1. Testes de caracterização: [comando FF1] -> 32 passed.
2. git diff --exit-code v1-coupled -- tests/characterization/ provider-fake/ edge/ data/ -> vazio.
3. python metrics/measure.py --source app/helpdesk --name piloto-f1 --no-plot
   -> classification Ce=2 (ports, schemas); ports A=1.00; adapters.gateway Ca=1.
4. grep -nE "llm|config|openai|adapters" app/helpdesk/classification.py -> vazio.

## Formato da resposta
Resumo; arquivos modificados/criados; justificativa de cada mudança; dependências
introduzidas; testes executados e saída; métricas antes e depois (tabela);
riscos; limitações; decisões que exigem revisão humana.
````

### 19.2 Registro do handoff efetivamente realizado
Pendente (Passo 08): data, agente, prompt efetivamente enviado, iterações, diferenças em relação ao template.

---

## 20. Processo de avaliação e aceitação

```mermaid
flowchart TD
    PL[Plano de refatoração] --> HO[Handoff para o agente]
    HO --> IMP[Implementação incremental]
    IMP --> REV[Revisão das alterações: escopo e diff]
    REV --> TST[Testes de caracterização]
    TST --> MED[Medição arquitetural]
    MED --> AN[Análise crítica humana]
    AN -->|critérios atendidos| OK[Aceitar e commitar]
    AN -->|desvio explicável| RV[Revisar e repetir]
    AN -->|regressão ou fora do escopo| RJ[Rejeitar e restaurar]
    RV --> HO
    RJ --> PL
```

| Avaliação | Mecanismo | Pergunta |
|---|---|---|
| Comportamental | FF1, FF2 | o comportamento externo é o mesmo? |
| Quantitativa | FF4 + tabela 15.4 | a estrutura evoluiu na direção planejada? |
| Arquitetural | revisão humana | cada mudança tem justificativa e respeita responsabilidades? |
| De escopo | `git diff --stat` + FF3, FF4b | o agente mexeu só no autorizado? |

| Condição | Decisão |
|---|---|
| Testes falham | rejeitar ou corrigir a implementação (nunca o teste) |
| Testes passam, métricas pioram sem justificativa | revisar |
| Métricas melhoram artificialmente (import sem uso, `Protocol` sem consumidor, módulo fragmentado) | rejeitar |
| Testes passam, métricas melhoram e a arquitetura faz sentido | candidato à aprovação |
| Métricas pioram com explicação prevista (ex.: D das features 0,25 → 0,33) | aceitar, registrando |
| Agente extrapola o escopo | revisar ou rejeitar |
| Complexidade injustificada | revisar |

O agente não decide sozinho se o próprio trabalho está correto porque otimiza o que lhe foi pedido e pode satisfazer o critério sem resolver o problema (Goodhart): passar nos testes alterando um teste, ou melhorar D com um import. Testes e métricas são feedback determinístico; a revisão humana avalia intenção e justificativa, que nenhuma ferramenta mede.

---

## 21. Riscos e estratégias de mitigação

| # | Risco | Prob. | Impacto | Prevenção | Detecção |
|---|---|---|---|---|---|
| R1 | Alteração involuntária de comportamento | média | alto | incrementos pequenos; prompt preservado literalmente | FF1 |
| R2 | Abstrações excessivas | média (tendência de agentes) | médio | contrato fixado no handoff; escopo fechado | revisão; componentes novos no CSV |
| R3 | Métrica melhorada artificialmente | média | médio | critério de rejeição explícito; justificar cada import | revisão do diff; imports sem uso |
| R4 | Dependência cíclica (`ports` importando algo) | baixa | médio | `ports` sem imports internos | ferramenta (ciclos); Ce(`ports`)=0 |
| R5 | Incompatibilidade do gateway com o fake Anthropic | **média** | alto | validar no Passo 07 antes do piloto | testes diretos no gateway |
| R6 | Alteração do formato de resposta (espaços, quebras) via tradução | média | alto (golden byte a byte da F2) | comparar com o golden no Passo 07 | FF1 (F2) |
| R7 | Troca involuntária de modelo | baixa | alto | mapeamento revisado 1:1 com a v1 | FF1; log do gateway |
| R8 | Ordem dos resultados da F3 alterada | baixa | médio | laço e `sort` fora do escopo de mudança | FF1 (F3) |
| R9 | Agente modifica testes | média | alto | restrição explícita | FF2 |
| R10 | Vazamento de credenciais (no código, no ambiente ou no log) | média até o incremento 9 | alto | `.env` fora do Git; `environment:` explícito | FF8, FF9 |
| R11 | Serviços desnecessários (banco do LiteLLM, Redis) | média | médio | só master key e config em arquivo; ADR para qualquer serviço | `docker compose config` |
| R12 | Refatoração ampla demais | média | alto | um incremento por commit | `git diff --stat` |
| R13 | Rollback difícil | baixa | alto | branch e commit por incremento; tag intocada | — |
| R14 | Diferenças entre APIs dos providers (ex.: `max_tokens` obrigatório na Anthropic) | média | médio | gateway define `max_tokens` por capacidade | Passo 07; FF1 |
| R15 | Dependência de serviços externos (download da imagem do gateway) | baixa | baixo | imagem com versão fixada | `docker compose pull` |
| R16 | Retries somados (SDK 2 + gateway N) multiplicam chamadas sob falha | alta sob falha | médio (custo) | não configurar retry agora; registrar o padrão do proxy | `/admin/calls` com injeção de falha (Passo 07) |
| R17 | Latência extra do gateway aproxima F2/F3 dos 30 s da borda | baixa | alto | medir no Passo 07 | tempos de FF1 |

**Riscos que não podem ser eliminados agora** (validar nos Passos 07 e 08): R5, R6, R14, R16, R17 dependem do comportamento real do LiteLLM com o fake; R2 e R3 dependem do que o agente produzir.

---

## 22. Estratégia de rollback

- **Marcos:** `v1-coupled` (intocável); um commit por incremento numa branch de trabalho (`refactor/v2-decoupled`); merge na `main` só após aceitação.
- **Antes de restaurar, inspecionar:** `git status`, `git diff --stat`, `git log --oneline -5`. Nada é descartado sem olhar.
- **Mudança ainda não commitada e rejeitada:** `git restore --source=HEAD -- app/` e remover os arquivos novos listados por `git status` (após conferir que são só os criados pelo agente).
- **Incremento já commitado e rejeitado:** `git revert HASH` (preserva o histórico; não reescreve nada).
- **Comparação com a v1 a qualquer momento:** worktree `../helpdesk-v1` na `v1-coupled`.
- Não usamos `reset --hard`, `push --force` ou movimentação de tags.

---

## 23. Resultados do piloto — pendente (Passo 08)

| Componente | Antes (medido, `pre-piloto`) Ca/Ce/I/A/D | Projetado pós-piloto | Depois (medido, `piloto-f1`) | Divergência |
|---|---|---|---|---|
| classification | 1/3/0.75/0.00/0.25 | 1/2/0.67/0.00/0.33 | pendente | pendente |
| ports | — | 2/0/0.00/1.00/0.00 | pendente | pendente |
| adapters.gateway | — | 1/2/0.67/0.00/0.33 | pendente | pendente |
| llm | 4/1/0.20/0.00/0.80 | 3/1/0.25/0.00/0.75 | pendente | pendente |
| config | 6/0/0.00/0.00/1.00 | 6/0/0.00/0.00/1.00 | pendente | pendente |
| main | 0/5/1.00/0.00/0.00 | 0/6/1.00/0.00/0.00 | pendente | pendente |

Testes antes/depois: pendente. Decisão: pendente.

---

## 24. Registro de revisões

| Versão | Evento | Evidência | Alteração realizada | Justificativa |
|---|---|---|---|---|
| 1.0 | Planejamento inicial | diagnóstico (Passo 02), comparação de modelos (Passo 03), caracterização (Passo 04), métricas da `v1-coupled` (Passo 05), simulação da 14.2 | plano inicial | — |
| 1.1 | Resultado do piloto | a preencher | a preencher | a preencher |

Para cada revisão: hipótese original; resultado esperado; resultado observado; divergências; problemas; alternativas consideradas; mudança no plano; evidência que a motivou; consequências para os próximos incrementos.

Revisar o plano depois do piloto não é falha de planejamento: o piloto existe para confrontar hipóteses com o código real. Um plano que nunca muda diante de evidência é que estaria errado.

---

## 25. Registro da execução assistida por IA — pendente (Passos 08 e 09)

| Incremento | Agente / data | Handoff usado | Iterações | Resultado de FF1 | Métricas | Decisão | Observações |
|---|---|---|---|---|---|---|---|
| 3 (piloto) | pendente | 19.1 | | | | | |

---

## 26. Revisão crítica e questões em aberto

### 26.1 Melhores contra-argumentos
1. **"Um `Protocol` com uma só implementação é cerimônia."** Em parte, sim. O que o justifica é o requisito (nenhuma feature importa o concreto) e o fato de as features ficarem testáveis com qualquer objeto. Sem o requisito, a Alt 1 seria defensável para esta aplicação.
2. **"O gateway é um ponto único de falha e um salto a mais."** Verdade. Em troca, centraliza credenciais, modelos e, na `main`, fallback e governança. O risco é medido no Passo 07 (R17).
3. **"O prompt repetido nas features é duplicação."** É uma linha por feature, e cada prompt é da feature. Centralizá-lo faria o adapter conhecer o vocabulário de negócio.
4. **"Capacidade como `str` não tem segurança de tipo."** Aceito. Um nome errado falha alto e os testes de rota cobrem as 4 capacidades. Um `Enum` central acoplaria as features entre si.
5. **"As métricas das features pioram."** Pioram (0,25 → 0,33) e isso é esperado (14.3). Usamos isso como lembrete de que D é indicador, não objetivo.
6. **"Herdar explicitamente do `Protocol` serve à métrica."** É o risco R3. A justificativa independente é a declaração de conformidade e a checagem estática; o piloto deve confirmar se ela se sustenta na revisão.

### 26.2 Consolidação
| Tipo | Itens |
|---|---|
| Decisões aprovadas (neste plano) | Alt 2; contrato `LanguageModel.complete(capability, prompt) -> str`; DI por parâmetro com `main` como Composition Root; 4 capacidades com modelos `large`; LiteLLM Proxy self-hosted como candidato; F1 como piloto; substituição progressiva de `llm.py`; estrutura Opção 1 |
| Decisões provisórias | `max_tokens` no gateway; adapter herdando do `Protocol` e lendo `config`; isolamento de rede `app` × `provider-fake`; destino de `config` na `main` |
| Hipóteses a validar | LiteLLM traduz para o fake Anthropic sem alterar o texto; o padrão do piloto se repete sem mudar o contrato; latência do gateway desprezível frente aos 30 s |
| Riscos remanescentes | R5, R6, R14, R16, R17, R2, R3 |
| Questões em aberto | 12.5 (1 a 8); como provar FF10 de forma objetiva; se `config` vira exceção ou é dissolvido (Passo 16) |

---

## 27. Conclusão

A menor transformação que resolve os problemas comprovados da v1 é: um contrato de uma operação (`ports.LanguageModel`), um único adapter do gateway (`adapters.gateway`), composição em `main`, capacidades lógicas no lugar de modelos físicos e credenciais isoladas no gateway. Ela elimina `llm` da zona de dor, tira os detalhes voláteis de `config`, não cria camadas e mantém o comportamento sob a mesma suíte de 32 testes. O que ela não resolve (fallback, streaming, F3 assíncrona, governança) fica explicitamente para a `main`, com o gateway e o contrato como pontos de extensão.

Próximo passo: Passo 07, subir o gateway e responder às questões da seção 12.5. O checkpoint está em `docs/refatoracao/checkpoint-passo-06.md`; o glossário em `docs/refatoracao/glossario.md`; as decisões em `docs/adr/0002` a `0004`.
