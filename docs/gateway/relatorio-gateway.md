# Passo 07: AI Gateway (LiteLLM Proxy) validado de forma isolada

| Item | Valor |
|---|---|
| Data | 2026-11-25 |
| Base | `b3fdeb2` (Passo 06), sobre a tag `v1-coupled` (`8028305`) |
| Ambiente | Windows, Docker Engine 29.9.2, Docker Compose v5.6.1 |
| Gateway | LiteLLM Proxy, `ghcr.io/berriai/litellm:v1.102.1` (digest `sha256:87f34979b9f8cb274fac90ca8a4fdda07d8480de22755562a26adeb95ce20d02`) |
| Estado da aplicação | **inalterada**: ainda chama o provider-fake diretamente. O gateway roda em paralelo |
| Evidências brutas | `docs/gateway/evidencias/` (geradas por `docs/gateway/experimentos.py`) |

> **Escopo.** O gateway foi configurado e validado sozinho. A aplicação **ainda não** usa o gateway. Portanto, nada aqui prova que o helpdesk está desacoplado: prova que a infraestrutura de que o piloto (Passo 08) precisa existe e se comporta como o plano supôs.

---

## 1. Recuperação do contexto

| Artefato | Informação relevante | Utilização nesta etapa |
|---|---|---|
| Diagnóstico da v1 (Passo 02) | provider fixo por feature; credenciais e modelos físicos no código; troca de modelo exige rebuild | justificativa do gateway |
| Comparativo dos modelos (Passo 03) | GPT large ≡ Claude large em 100% dos casos; mini degrada F2 e F4 | mapeamento inicial só com `large`; experimento de troca para um equivalente |
| Plano de refatoração (Passo 06) | Alt 2 (contrato + adapter); 4 capacidades; LiteLLM candidato; 8 questões em §12.5 | posicionamento e questões respondidas aqui (§11) |
| Testes de caracterização (Passo 04) | 32 testes pela borda; goldens byte a byte | regressão da app; referência para comparar as saídas do gateway |
| Métricas (Passo 05) | `llm` e `config` na zona de dor | referência do piloto (nada muda nesta etapa) |
| `provider-fake/README.md` | URLs, formatos, autenticação, `/admin/calls`; trecho de `model_list` **testado com `ghcr.io/berriai/litellm:v1.102.1`**; aviso de custo zero sem preços declarados | versão escolhida e sintaxe da configuração |
| `compose.yaml`, `.env.example` | `app` e `provider-fake` recebem `env_file: .env` | onde entra o serviço `gateway` e suas variáveis |

Confirmado em 2026-11-25: a tag `v1-coupled` existe (objeto `07c2026d`, commit `8028305`); o plano está versionado (`b3fdeb2`); a app e o provider sobem saudáveis; 32 testes verdes (§10).

---

## 2. Fundamentos

### 2.1 O que é um AI Gateway e por que ele surgiu

Cada provider de LLM tem sua API: formato de mensagens, autenticação, nomes de modelo, campos de uso, formato de erro e de streaming. Quando a aplicação fala com vários, esses detalhes se espalham pelo código (é a v1: `call_openai` e `call_anthropic`). Um AI Gateway é um serviço intermediário que oferece **uma** API para todos os providers e concentra o que é transversal: tradução de formato, roteamento por nome lógico, credenciais, e depois retry, fallback, limites, custo e observabilidade. Ele reduz o *vendor lock-in* no código (trocar de provider vira configuração), mas cria dependência da própria ferramenta.

### 2.2 Componentes que costumam ser confundidos

| Componente | Responsabilidade | Problema que resolve | No projeto |
|---|---|---|---|
| Reverse Proxy | repassa HTTP para um upstream, sem entender o conteúdo | ponto de entrada único, TLS, timeouts de borda | `edge` (nginx, 30 s) |
| Load Balancer | distribui requisições entre instâncias equivalentes | capacidade e disponibilidade de **um** serviço | não há |
| API Gateway | entrada de APIs: roteamento por rota, autenticação, cotas | expor e proteger APIs para clientes | não há (o `edge` faz o mínimo) |
| AI Gateway | API única para modelos: tradução, nomes lógicos, credenciais, políticas de IA | heterogeneidade dos providers e políticas de consumo de IA | `gateway` (LiteLLM Proxy) |
| SDK de provider | cliente de **um** provider dentro do processo | chamar aquele provider com conforto | `openai`, `anthropic` em `llm.py` |
| Biblioteca de abstração | interface comum dentro do processo (ex.: LiteLLM SDK) | heterogeneidade, mas **na** aplicação | descartada: credenciais e modelos ficariam na app |

Eles não se substituem: estão em posições diferentes. O `edge` protege a **entrada** do helpdesk; o gateway fica na **saída** da aplicação para os providers. Trocar o nginx pelo gateway misturaria responsabilidades (o nginx não entende de modelos; o gateway não é a porta pública do helpdesk).

### 2.3 Princípios

| Princípio | Como o gateway contribui |
|---|---|
| Separation of Concerns | a app cuida de regras de negócio; o gateway, de como falar com cada provider |
| DIP | a app passará a depender de um nome lógico e de uma API estável, não do provider. O gateway **ajuda**, mas não inverte nada sozinho: isso é feito pelo contrato e pelo adapter na app (Passo 06, ADR 0002) |
| Encapsulamento | URLs, chaves e formato nativo ficam escondidos atrás da API do gateway |
| Indireção | o nome lógico é um nível de indireção: o mapeamento muda sem mudar o consumidor |
| Centralização de políticas | retry, fallback, limites e custo terão um único lugar (Passos 10 a 12) |
| Isolamento de detalhes tecnológicos | prefixos `openai/`, `anthropic/` e chaves ficam em `gateway/config.yaml` e no ambiente do gateway |

### 2.4 Desvantagens (todas reais aqui)

Um salto de rede a mais (medido: +6 ms, §8); um serviço a mais para subir, versionar e observar (imagem de 1,65 GB); um novo ponto único de falha para as quatro features; comportamento padrão da ferramenta que precisa ser descoberto (retries automáticos, §7.3; erros reescritos, §6.2); dependência de um projeto de terceiros.

**Quando se justifica:** vários providers, troca de modelo frequente, credenciais que não devem estar na aplicação, necessidade de políticas comuns (custo, limites, fallback). O desafio tem todas: dois providers com APIs diferentes, troca de modelo exigindo rebuild (Dor 4), provider fora derrubando metade do sistema (Dor 3) e requisitos futuros de governança. Numa aplicação com um provider e sem esses requisitos, um SDK direto seria mais simples.

---

## 3. Posicionamento arquitetural

### 3.1 Arquitetura original (v1)

```mermaid
flowchart LR
    C[Cliente] --> E[edge nginx]
    E --> A[app FastAPI]
    A -->|SDK openai, FAKE_OPENAI_KEY| PO[provider-fake openai]
    A -->|SDK anthropic, FAKE_ANTHROPIC_KEY| PA[provider-fake anthropic]
```

### 3.2 Arquitetura transitória (implementada neste passo)

```mermaid
flowchart LR
    C[Cliente] --> E[edge nginx]
    E --> A[app FastAPI inalterada]
    A -->|direto, como na v1| P[provider-fake]
    T[Cliente de teste: experimentos.py] -->|Bearer GATEWAY_MASTER_KEY| G[gateway LiteLLM]
    G -->|openai: Bearer FAKE_OPENAI_KEY| P
    G -->|anthropic: x-api-key FAKE_ANTHROPIC_KEY| P
    style G fill:#d6eaf8,stroke:#2471a3
    style T fill:#fdebd0,stroke:#ca6f1e
```

### 3.3 Arquitetura pretendida (v2-decoupled, ainda não existe)

```mermaid
flowchart LR
    C[Cliente] --> E[edge nginx]
    E --> A[app: features]
    A --> P{{ports.LanguageModel}}
    AD[adapters.gateway] -.implementa.-> P
    AD -->|Bearer chave do gateway| G[gateway LiteLLM]
    G --> PO[provider-fake openai]
    G --> PA[provider-fake anthropic]
    style P fill:#d4edda,stroke:#1e8449
```

**Por que o adapter continua necessário:** o gateway muda **para onde** a chamada vai, não **de quem** o código depende. Se as features chamassem o gateway diretamente com o SDK, continuariam acopladas a um detalhe concreto (agora o gateway), e a zona de dor só mudaria de nome. O gateway também não deve conhecer regras do helpdesk (validação de categoria, lote de 150, formato do pedido): essas continuam na app.

### 3.4 Rede do Docker Compose

```mermaid
flowchart TB
    subgraph Host[Host Windows]
        H8000[localhost:8000]
        H8090[localhost:8090]
        H4000[localhost:4000]
    end
    subgraph Rede[rede desafio-arquitetura-era-ia-1_default, bridge, DNS interno]
        EDGE[edge :80]
        APP[app :8080]
        GW[gateway :4000]
        PF[provider-fake :8090]
    end
    H8000 --> EDGE
    H8090 --> PF
    H4000 --> GW
    EDGE -->|http://app:8080| APP
    APP -->|http://provider-fake:8090| PF
    GW -->|http://provider-fake:8090| PF
```

- O Compose cria uma rede bridge padrão; cada serviço é resolvido pelo **nome** (DNS interno, *service discovery*).
- `http://provider-fake:8090` só existe **dentro** da rede (é o que o gateway usa no `api_base`). `http://localhost:8090` é a porta publicada no host (é o que os testes e o script usam, via `host.docker.internal` dentro de um container avulso). Dentro do container do gateway, `localhost` é o próprio gateway.
- A porta 4000 é publicada só para testes no host. A app usará `http://gateway:4000` (Passo 08).
- Não criamos redes separadas: não há requisito que exija isso agora (questão aberta no ADR 0003).

### 3.5 Fluxo de credenciais

```mermaid
flowchart LR
    ENV[.env local, não versionado] -->|interpolação no compose| GWENV[ambiente do gateway: FAKE_OPENAI_KEY, FAKE_ANTHROPIC_KEY, GATEWAY_MASTER_KEY]
    ENV -->|env_file, transitório| APPENV[ambiente do app: FAKE_* e, por enquanto, GATEWAY_MASTER_KEY]
    ENV -->|env_file| PFENV[ambiente do provider-fake: FAKE_*]
    CFG[gateway/config.yaml versionado: só os.environ/NOME] --> GW[LiteLLM]
    GWENV --> GW
    CLI[Consumidor] -->|Authorization: Bearer GATEWAY_MASTER_KEY| GW
    GW -->|Bearer FAKE_OPENAI_KEY| OA[openai fake]
    GW -->|x-api-key FAKE_ANTHROPIC_KEY| AN[anthropic fake]
```

**Estado transitório, declarado:** a app ainda recebe `FAKE_OPENAI_KEY` e `FAKE_ANTHROPIC_KEY` (precisa delas até o Passo 09) e, por usar `env_file: .env`, passou a ver também `GATEWAY_MASTER_KEY`, que **não usa**. O isolamento completo **não** foi atingido; ele está planejado nos incrementos 8 e 9 do plano.

---

## 4. Ferramenta e versão

### 4.1 Escolha

| Critério | LiteLLM Proxy | Portkey AI Gateway (open source) |
|---|---|---|
| Self-hosted | documentado; **validado** (container local) | documentado |
| Docker Compose | **validado** | documentado (imagem própria) |
| OpenAI | **validado** (Chat Completions) | documentado |
| Anthropic | **validado** (Messages, com tradução) | documentado |
| Endpoints personalizados (`api_base`) | **validado** para os dois fakes | documentado |
| Capacidades lógicas | **validado** (`model_name` → `litellm_params.model`) | documentado (configs por rota) |
| Autenticação própria | **validado** só com master key, sem banco (§5) | documentado |
| Streaming | **validado** pelo gateway (§7.4) | documentado |
| Resiliência (retry, fallback, timeout) | retry padrão **observado** (§7.3); fallback e timeout documentados | documentado |
| Governança (chaves virtuais, budget, rate limit) | documentado; exige PostgreSQL (§9) | parte dos recursos documentada como do produto hospedado; não verificado |
| Complexidade | um container, um YAML; imagem grande (1,65 GB) | um container |
| Indicação do desafio | **sugerido pelo enunciado e testado pelo próprio provider-fake** | — |

**Decisão:** LiteLLM Proxy. Não por popularidade, mas porque o repositório do desafio documenta a compatibilidade com o simulador nessa versão exata, e porque os requisitos futuros (chaves virtuais, orçamento, limite de requisições) estão documentados no modo self-hosted com PostgreSQL, sem serviço pago. As linhas "documentado" da alternativa não foram verificadas nesta etapa: são apenas o motivo de ela ter sido considerada.

### 4.2 Versão

| Informação | Valor selecionado |
|---|---|
| Ferramenta | LiteLLM Proxy |
| Versão | `v1.102.1` |
| Imagem Docker | `ghcr.io/berriai/litellm:v1.102.1` |
| Digest observado | `sha256:87f34979b9f8cb274fac90ca8a4fdda07d8480de22755562a26adeb95ce20d02` (criada em 2026-09-23, 1,65 GB) |
| Porta interna | 4000 |
| Porta externa | 4000 (só para testes no host) |
| Arquivo de configuração | `gateway/config.yaml`, montado somente leitura em `/app/config.yaml` |
| Dependências | nenhuma nesta etapa (sem banco: `/health/readiness` responde `"db":"Not connected"`) |
| Justificativa | é a versão citada como testada em `provider-fake/README.md`; tag fixa em vez de `latest` |

`latest` muda sem aviso: um `docker compose pull` amanhã poderia trazer outro comportamento padrão (por exemplo, retries ou formato de erro) e invalidar estas evidências. Com a tag fixa e o digest registrado, outra pessoa reproduz o mesmo ambiente. Para travar ainda mais, a referência pode usar `@sha256:...` (decisão adiada: a tag atende ao requisito e é legível).

---

## 5. Configuração

### 5.1 Arquivos

| Arquivo | Responsabilidade |
|---|---|
| `gateway/config.yaml` | configuração versionada: capacidades lógicas, destinos físicos, `api_base`, referência às chaves (`os.environ/...`) e a master key |
| `compose.yaml` (serviço `gateway`) | imagem fixa, comando, variáveis de ambiente, volume da configuração, porta, healthcheck, dependência do `provider-fake` |
| `.env.example` | nomes e valores de desenvolvimento (fake) das variáveis; o `.env` real continua fora do Git |
| `docs/gateway/experimentos.py` | cliente de teste reprodutível que gera as evidências (só biblioteca padrão) |

Não foi preciso `Dockerfile`, scripts de inicialização nem README próprio no `gateway/`.

### 5.2 `gateway/config.yaml` (resumo)

| `model_name` (capacidade) | `litellm_params.model` | `api_base` | `api_key` | outros |
|---|---|---|---|---|
| `ticket-classification` | `openai/gpt-fake-large` | `http://provider-fake:8090/openai/v1` | `os.environ/FAKE_OPENAI_KEY` | — |
| `order-extraction` | `openai/gpt-fake-large` | idem | idem | — |
| `reply-suggestion` | `anthropic/claude-fake-large` | `http://provider-fake:8090/anthropic` | `os.environ/FAKE_ANTHROPIC_KEY` | `max_tokens: 2000` |
| `topics-report` | `anthropic/claude-fake-large` | idem | idem | `max_tokens: 2000` |

- O **prefixo** (`openai/`, `anthropic/`) diz ao LiteLLM qual tradutor usar; sem ele um modelo desconhecido como `gpt-fake-large` não seria roteado.
- `api_base` do OpenAI inclui `/v1` (o LiteLLM acrescenta `/chat/completions`); o do Anthropic **não** inclui (o LiteLLM acrescenta `/v1/messages`). O log de erro confirma a URL final `http://provider-fake:8090/anthropic/v1/messages`, sem segmento duplicado.
- `max_tokens: 2000` repete o que a v1 envia ao Anthropic (`config.MAX_OUTPUT_TOKENS`). As saídas caracterizadas (606 e 360 tokens) ficam abaixo de qualquer limite, então **as evidências não provam que o valor é aplicado**; isso fica registrado como pendência (§11).
- `general_settings.master_key: os.environ/GATEWAY_MASTER_KEY`: autenticação própria do gateway.

### 5.3 Serviço no Compose

| Propriedade | Valor | Por quê |
|---|---|---|
| `image` | `ghcr.io/berriai/litellm:v1.102.1` | versão fixa |
| `command` | `--config /app/config.yaml --port 4000` | carrega o YAML montado |
| `environment` | `FAKE_OPENAI_KEY`, `FAKE_ANTHROPIC_KEY`, `GATEWAY_MASTER_KEY` com `${VAR:?mensagem}`; `LITELLM_LOCAL_MODEL_COST_MAP=True` | menor privilégio (só o que o gateway usa, sem `env_file`); falha clara se faltar variável; tabela de modelos local, sem busca na internet ao subir |
| `volumes` | `./gateway/config.yaml:/app/config.yaml:ro` | configuração versionada, sem rebuild para trocar modelo |
| `ports` | `4000:4000` | testes no host |
| `healthcheck` | `GET /health/readiness` (sem autenticação) | distingue processo iniciado de serviço pronto; `--wait` só retorna com `healthy` |
| `depends_on` | `provider-fake: service_healthy` | o gateway sobe depois do provider |

A `app` **não** depende do gateway nesta etapa: ela ainda não o usa.

---

## 6. Integração com os providers

### 6.1 Um provider por vez

| Etapa | Configuração | Evidência |
|---|---|---|
| 1 | só `ticket-classification` (OpenAI) | `up --build --wait` em 20 s; `liveliness` 200, `readiness` 200; probe 200 com `{"category": "delivery", "priority": "high"}`; `/admin/calls`: `openai`, `gpt-fake-large`, `classify`, 200 |
| 2 | configuração final (4 capacidades) | restart + healthy em 7 s; log `Proxy initialized with Config, Set models: ticket-classification, order-extraction, reply-suggestion, topics-report` |

`GET /health` (sem `/liveliness` ou `/readiness`) exige chave e respondeu 401: ele testa os modelos e não serve como healthcheck do container.

### 6.2 As quatro capacidades (entradas da caracterização)

| Capacidade | Provider esperado | Provider observado | Modelo esperado | Modelo observado | Status | Resultado |
|---|---|---|---|---|---|---|
| `ticket-classification` | openai | openai | gpt-fake-large | gpt-fake-large | 200 (1,087 s) | `delivery`/`high`, igual ao teste `entrega-urgente` |
| `order-extraction` | openai | openai | gpt-fake-large | gpt-fake-large | 200 (1,235 s) | `#481516` e `fone de ouvido bluetooth`, igual ao teste `pedido-e-produto` |
| `reply-suggestion` | anthropic | anthropic | claude-fake-large | claude-fake-large | 200 (15,964 s) | 2.424 caracteres, **idêntico byte a byte** ao golden `reply_suggestion_TK-00042` |
| `topics-report` | anthropic | anthropic | claude-fake-large | claude-fake-large | 200 (9,812 s) | lote de 137 tickets de 2026-08-01; 15 temas; **idêntico** ao golden `topics_2026-08-01` depois da mesma agregação do `report.py` |

Fonte: `evidencias/10-capacidades.json` (provider e modelo vêm do `/admin/calls`, não da resposta do gateway).

### 6.3 Tradução (Anthropic)

```mermaid
sequenceDiagram
    participant C as Consumidor
    participant G as gateway
    participant A as anthropic fake
    C->>G: POST /v1/chat/completions, model=reply-suggestion, Bearer chave do gateway
    G->>G: autentica a chave e resolve reply-suggestion para anthropic/claude-fake-large
    G->>A: POST /anthropic/v1/messages, model=claude-fake-large, max_tokens=2000, x-api-key
    A-->>G: content[0].text, stop_reason=end_turn, usage input_tokens/output_tokens
    G-->>C: choices[0].message.content, finish_reason=stop, usage prompt/completion, model=reply-suggestion
```

### 6.4 Roteamento das capacidades

```mermaid
flowchart LR
    TC[ticket-classification] --> GL[openai/gpt-fake-large]
    OE[order-extraction] --> GL
    RS[reply-suggestion] --> CL[anthropic/claude-fake-large]
    TR[topics-report] --> CL
    GL --> PO[provider-fake /openai/v1]
    CL --> PA[provider-fake /anthropic]
```

---

## 7. Experimentos

### 7.1 Autenticação

| Cenário | Esperado | Observado | Chamadas no provider |
|---|---|---|---|
| Chave válida | autorizada | 200 | 1 |
| Chave inválida | recusada | **400** `{"message":"No connected db.","type":"no_db_connection"}` | 0 |
| Sem chave | recusada | 401 `Authentication Error, No api key passed in.` | 0 |

Os três requisitos foram cumpridos (nenhuma chamada recusada chegou ao provider), mas o status da chave inválida é **400, não 401**: sem banco, o LiteLLM tenta validar qualquer chave diferente da master key como chave virtual e falha por falta de banco. Consequência para quem consumir o gateway: não usar o status para distinguir "chave errada" de "requisição inválida". Isso se resolve no Passo 12, quando houver banco e chaves virtuais.

| Credencial | Consumidor | Finalidade | Estado |
|---|---|---|---|
| `FAKE_OPENAI_KEY` | gateway (e a app, até o Passo 09) | autenticação no provider | transitória na app |
| `FAKE_ANTHROPIC_KEY` | idem | idem | idem |
| `GATEWAY_MASTER_KEY` | administração **e**, provisoriamente, consumidores | autenticação no gateway | **provisória** como chave de consumo |
| chave virtual da app | app | consumo com menor privilégio | Passo 12 (exige PostgreSQL) |

**Risco aceito e com prazo:** no piloto, a app usará a master key, que também administra o gateway. Isso viola o menor privilégio. Alternativa avaliada: subir PostgreSQL agora só para criar uma chave virtual; recusada porque introduziria um serviço antes do requisito que o justifica (governança, Passo 12). A troca da master key por uma chave virtual é critério do Passo 12.

### 7.2 Normalização

| Característica | OpenAI nativo | Anthropic nativo | Interface do gateway (os dois destinos) |
|---|---|---|---|
| Requisição | `POST /openai/v1/chat/completions`, `messages` | `POST /anthropic/v1/messages`, `messages` + `max_tokens` obrigatório | `POST /v1/chat/completions`, `model` = capacidade |
| Resposta | `choices[0].message.content` | `content[0].text` | `choices[0].message.content` nos dois |
| Autenticação | `Authorization: Bearer` | `x-api-key` + `anthropic-version` | `Authorization: Bearer` (chave do gateway) |
| Tokens | `usage.prompt_tokens`/`completion_tokens`/`total_tokens` | `usage.input_tokens`/`output_tokens` | formato OpenAI nos dois; destino Anthropic acrescenta `*_tokens_details` e `cache_*` (zerados) |
| Finalização | `finish_reason: stop` | `stop_reason: end_turn` | `finish_reason: stop` nos dois |
| Campo `model` | físico | físico | **o nome lógico** (`ticket-classification`): o consumidor não vê o modelo físico |
| Erros | `{"error":{"code":"context_length_exceeded",...}}` | `{"type":"error","error":{"type":"invalid_request_error",...}}` | envelope OpenAI nos dois, mas `code: "400"` e mensagem reescrita pelo LiteLLM (`litellm.BadRequestError: OpenAIException - ...`, `litellm.ContextWindowExceededError: ... AnthropicError - ...`), com nome de provider e de *model group* |

Mesma tarefa, mesmo conteúdo (`{"category": "delivery", "priority": "high"}`) e mesmos tokens (19/11) nos quatro caminhos.

- **Abstraído pelo gateway:** endpoint, autenticação, formato de requisição e resposta, nomes de campo de uso, motivo de finalização, nome físico.
- **Ainda é da aplicação:** interpretar o conteúdo (JSON em texto), validar regras de negócio (o 502 das features), decidir o que fazer com erros. A aplicação **não deve** analisar a mensagem de erro: ela é texto da ferramenta, menciona o provider e muda entre versões. Só o status HTTP é estável.
- **Normalização de interface ≠ equivalência funcional:** as respostas têm a mesma forma porque o gateway traduz. Que o conteúdo também seja igual entre GPT e Claude large é um fato do simulador, comprovado no Passo 03 e de novo aqui, não uma propriedade do gateway. Com `mini`, a forma continuaria igual e o conteúdo não (F2, F4).

### 7.3 Erros e retries padrão

| Gatilho | Resultado pelo gateway | Chamadas no provider |
|---|---|---|
| entrada de 10.004 tokens (contexto 8.000), destino OpenAI | 400 em ~0 s | 1 (400 não é retentado) |
| idem, destino Anthropic | 400 (`ContextWindowExceededError`) | 1 |
| capacidade inexistente | 400 `Invalid model name passed in model=...` | 0 |
| provider em `error_500` (`gpt-fake-large`) | **500 em 4,69 s** | **3** (log: `LiteLLM Retried: 2 times, LiteLLM Max Retries: 2`) |

**Achado importante:** sem nenhuma configuração de retry, a imagem já faz **2 retentativas** em 5xx (intervalos observados de 0,6 s e 1,7 s). Se o adapter do Passo 08 mantiver o padrão do SDK `openai` (2 retentativas), uma falha persistente geraria até **3 × 3 = 9** chamadas ao provider, contra 3 na v1. Isso muda o comportamento sob falha (não caracterizado, mas diagnosticado no Passo 02) e o custo. Ver a revisão do plano (§12).

### 7.4 Streaming (experimento, sem tocar na app)

| Caminho | Primeiro byte | Primeiro conteúdo | Total | Eventos `data:` | Fim do stream | Texto |
|---|---|---|---|---|---|---|
| gateway, `reply-suggestion`, `stream: true` | 0,823 s | 0,823 s | 16,127 s | 608 | `[DONE]` | igual ao golden |
| anthropic nativo | 0,004 s | 0,805 s | 16,092 s | 611 | `{"type": "message_stop"}` | igual ao golden |

O provider registrou `stream: true` nos dois. O gateway entrega SSE progressivo no formato `chat.completion.chunk` do OpenAI, termina com `[DONE]` e não acumula a resposta. Diferença: ele só envia os cabeçalhos junto com o primeiro trecho (primeiro byte = primeiro conteúdo), enquanto o nativo abre o stream na hora. O primeiro conteúdo chegou 18 ms depois do nativo. O limite de 1,5 s da F2 será medido pela borda no Passo 14; aqui só se comprova que o caminho existe. `midstream_error` não foi testado (Passo 14).

### 7.5 Troca de modelo por configuração

| Característica | Antes | Depois |
|---|---|---|
| Capacidade lógica | `ticket-classification` | `ticket-classification` |
| Requisição do consumidor | `model=ticket-classification`, `TASK: classify` + texto do TK-00042 | idêntica |
| Provider (`/admin/calls`) | openai | **anthropic** |
| Modelo físico (`/admin/calls`) | gpt-fake-large | **claude-fake-large** |
| Resposta | `{"category": "delivery", "priority": "high"}`, 200, 1,087 s | idêntica, 200, 1,255 s (primeira chamada depois do restart) |
| Container da app | `e14e9f9a8634...`, iniciado 22:58:00.897Z | mesmo Id, mesmo horário |
| Container do gateway | `dba6b3e22551...`, iniciado 22:58:31Z | mesmo Id, reiniciado 23:02:16Z |
| Código da aplicação | — | `git diff --stat -- app/` vazio |

Procedimento: copiar a configuração alternativa para `gateway/config.yaml` (só o bloco da capacidade muda), `docker compose restart gateway`, `docker compose up -d --wait gateway` (8 s no total), repetir a chamada. Depois, o original foi restaurado (sha256 conferido), e uma nova chamada voltou a `openai`/`gpt-fake-large`.

Isso prova a separação entre interface lógica e implementação física **para um cliente de teste**. Não prova o critério do helpdesk ("trocar o modelo de uma feature sem deploy da app"), porque a app ainda não usa o gateway; a prova definitiva será repetida pela borda depois da migração.

---

## 8. Latência

| Modelo | Tarefa | Direto (mediana) | Via gateway (mediana) | Diferença |
|---|---|---|---|---|
| gpt-fake-large | classify (5 repetições alternadas) | 1,080 s | 1,086 s | +6 ms |
| claude-fake-large | suggest (3 repetições alternadas) | 15,955 s | 15,961 s | +6 ms |

A variação entre repetições foi de 1 ms. O custo do salto (rede entre containers, autenticação, roteamento, tradução e serialização) é desprezível diante do tempo do modelo. A **primeira** chamada depois de cada (re)início foi mais lenta: 1,25 a 1,70 s contra 1,09 s (aquecimento de conexões e caches do processo). Isso não ameaça a F1 (≤ 3 s), mas aparece em medições logo após um deploy. As medições foram feitas do host via `host.docker.internal`; as metas oficiais (F1 ≤ 3 s, F2 primeiro trecho ≤ 1,5 s, ≤ 15 s sob falha, sem 504 na borda) serão medidas pela borda nos passos seguintes.

---

## 9. Dependências futuras (governança e resiliência)

| Recurso futuro | Suporte documentado no LiteLLM | Dependência necessária | Validação realizada? | Passo |
|---|---|---|---|---|
| Budget | sim (por chave, equipe, usuário) | PostgreSQL (`DATABASE_URL`) | não; sem banco a chave não-master é recusada com `No connected db.` | 12 |
| Rate limiting | sim (rpm/tpm por chave e por modelo) | PostgreSQL para chaves; Redis só com várias instâncias do proxy | não | 12 |
| Virtual keys | sim (`/key/generate`) | PostgreSQL | **indireta**: a ausência de banco impede o uso | 12 |
| Contabilização de custos | sim | preços dos modelos fake declarados em `model_info` (`input_cost_per_token`, `output_cost_per_token`); sem isso o custo é zero (aviso do `provider-fake/README.md`) | não | 12 |
| Retry | sim (`num_retries`) | nenhuma | **sim**: padrão de 2 retentativas observado | 10 |
| Fallback técnico | sim (`fallbacks` entre model groups) | nenhuma | não (mensagens de erro mostram `Fallbacks=None`) | 11 |
| Fallback com mini | sim (mesmo mecanismo) | nenhuma | não | 11 |
| Streaming | sim | nenhuma | **sim** (§7.4) | 14 |
| Timeout | sim (`timeout`, `stream_timeout` por modelo) | nenhuma | não | 10 |

Nenhuma dessas dependências foi introduzida. Quando o Passo 12 precisar de PostgreSQL, ele entra com ADR próprio. Preços: a tabela do `provider-fake/README.md` (US$ por 1M tokens) é a fonte para declarar o custo por token.

---

## 10. Integridade da aplicação e reprodutibilidade

| Verificação | Resultado |
|---|---|
| `curl localhost:8000/health` | `{"status":"ok"}` |
| Testes de caracterização (com o gateway no ar) | `32 passed in 60.01s` |
| `git diff --stat v1-coupled -- app/ tests/characterization/ provider-fake/ edge/ data/` | vazio |
| Arquivos alterados | `compose.yaml`, `.env.example`; novos `gateway/`, `docs/gateway/` |
| Ambiente limpo: `docker compose down` + `docker compose up -d --build --wait` | 19 s; os 4 serviços `healthy`; `readiness` `healthy`; probe 200 via openai |

Os testes passarem prova só que a app **não regrediu**: ela ainda não chama o gateway. A integração é provada pelos experimentos diretos. Introduzir a infraestrutura em paralelo, antes de migrar consumidores, permite validá-la sozinha e voltar atrás removendo um serviço, sem tocar no comportamento caracterizado.

Para quem já tinha um `.env` de passos anteriores: o compose agora exige `GATEWAY_MASTER_KEY` e falha com a mensagem `defina GATEWAY_MASTER_KEY no .env` se ela faltar. Basta copiar a linha do `.env.example` (ou recriar o `.env` a partir dele). Em uma máquina nova, `cp .env.example .env` e `docker compose up -d --build --wait` bastam, sem ajustes dentro de containers.

---

## 11. Matriz de compatibilidade

| Recurso | Necessário para o desafio? | Situação | Limitações | Passo |
|---|---|---|---|---|
| Comunicação com OpenAI fake | sim | **implementado e validado** | — | 07 |
| Comunicação com Anthropic fake | sim | **implementado e validado** | `max_tokens` configurado, mas sua aplicação não foi provada | 07 |
| Capacidades lógicas | sim | **implementado e validado** (4) | nomes sem checagem estática: erro só em execução (400) | 07 |
| Autenticação | sim | **implementado e validado** (master key) | chave inválida dá 400 sem banco; master key como chave de consumo é provisória | 07 / 12 |
| Normalização | sim | **validado** | erros normalizados no envelope, mas com mensagem reescrita e `code` genérico | 07 |
| Troca de modelo | sim | **validado com cliente de teste** | repetir pela borda após a migração | 07 / 09 |
| Streaming | sim | **investigado e validado no gateway** | cabeçalhos só no primeiro trecho; `midstream_error` não testado | 14 |
| Timeout | sim | só investigado (documentação) | não configurado | 10 |
| Retry | sim | **comportamento padrão observado** (2 retentativas) | soma com retries do SDK do adapter | 10 |
| Fallback | sim | só investigado | não configurado | 11 |
| Budget | sim | só investigado | exige PostgreSQL e preços declarados | 12 |
| Rate limiting | sim | só investigado | exige PostgreSQL | 12 |

---

## 12. Respostas às questões do plano (Passo 06, §12.5) e impacto no piloto

| # | Questão | Resposta (com evidência) |
|---|---|---|
| 1 | `api_base` customizado para o fake Anthropic funciona? | sim; URL final `.../anthropic/v1/messages` (logs, §6.3) |
| 2 | Texto da F2 byte a byte? | sim, com e sem streaming |
| 3 | `max_tokens` por modelo? | aceito na configuração; aplicação **não provada** (saídas abaixo do limite) |
| 4 | Retries padrão do proxy? | **2** em 5xx; 400 não é retentado |
| 5 | Latência adicional? | +6 ms nas medianas; F2 e F3 continuam longe dos 30 s da borda |
| 6 | Como provar que tudo passa pelo gateway? | `/admin/calls` não identifica a origem; a prova será por exclusão: sem credenciais nem URL do provider na app (FF7, FF8, FF9) e contagens de `/admin/calls` iguais às requisições registradas pelo gateway (FF10) |
| 7 | Master key sem banco? | sim; qualquer outra chave é recusada (400) |
| 8 | Isolar a rede da app? | não nesta etapa; continua como opção para o Passo 09, se FF10 não for suficiente |

**Mudança recomendada para o handoff do piloto (revisão 1.0.1 do plano):** o adapter deve criar o cliente `openai` com `max_retries=0`. Assim, o número de tentativas sob falha continua 3 (as 2 retentativas padrão do gateway), como na v1, e a política de retry passa a ter um único dono (o gateway), a ser configurada explicitamente no Passo 10. Não é uma política nova; é evitar que duas camadas somem tentativas.

---

## 13. Informações para o adapter (Passo 08)

| Item | Valor |
|---|---|
| URL interna | `http://gateway:4000`; o SDK `openai` usa `base_url=http://gateway:4000/v1` (caminho validado: `/v1/chat/completions`) |
| Autenticação | `Authorization: Bearer ${GATEWAY_MASTER_KEY}` (provisório) |
| Variáveis para a app | `GATEWAY_URL`, `GATEWAY_API_KEY` (a ser preenchida com o valor de `GATEWAY_MASTER_KEY` no compose) |
| Requisição | `chat.completions.create(model=CAPABILITY, messages=[{"role":"user","content": prompt}])` |
| Resposta | `choices[0].message.content` (texto; JSON em texto para F1, F3, F4) |
| Erros | status HTTP 400/401/500 com envelope OpenAI; não interpretar a mensagem |
| Retries | gateway faz 2 por padrão; cliente com `max_retries=0` (ver §12) |
| Dependência no compose | `app` deve passar a depender de `gateway: service_healthy` quando a primeira feature migrar |

---

## 14. Como reproduzir

```bash
cp .env.example .env                       # ou acrescente GATEWAY_MASTER_KEY a um .env existente
docker compose up -d --build --wait
curl -s localhost:4000/health/readiness    # {"status":"healthy","db":"Not connected"}

# chamada direta a uma capacidade
curl -s localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-gateway-local-0001" -H "Content-Type: application/json" \
  -d '{"model": "ticket-classification", "messages": [{"role": "user", "content": "TASK: classify\nMeu pedido #481516 não chegou"}]}'
curl -s "localhost:8090/admin/calls?last=1"   # provider e modelo físico efetivos

# todos os experimentos (uma fase por vez)
docker run --rm -v "${PWD}:/w" -w /w -e PYTHONDONTWRITEBYTECODE=1 \
  -e GATEWAY_URL=http://host.docker.internal:4000 -e PROVIDER_URL=http://host.docker.internal:8090 \
  python:3.12-slim python docs/gateway/experimentos.py capacidades
```

Fases disponíveis: `probe`, `auth`, `capacidades`, `normalizacao`, `erros`, `latencia`, `streaming`, `retries`. Cada uma começa com `POST /admin/reset`.
