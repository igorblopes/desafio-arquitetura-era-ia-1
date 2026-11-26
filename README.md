# Helpdesk com IA: da integração frágil à arquitetura resiliente

Fork de trabalho do desafio **Arquitetura na Era da IA** (Full Cycle). O enunciado original continua disponível no [repositório base](https://github.com/devfullcycle/desafio-arquitetura-era-ia-1).

> [!NOTE]
> Este README está em construção. Seções presentes: **Visão geral**, **Como rodar**, **Tabela de capacidades**, **Fluxos**, **Troca de modelo**, **Métrica**, **Mapa de decisões** e **Diagnóstico da v1**. A tabela de fallback e o roteiro de governança entram nos próximos passos.

## Visão geral

O helpdesk tem quatro funcionalidades de IA, todas síncronas: classificação de tickets (F1), sugestão de resposta (F2), relatório de temas (F3) e extração de dados do pedido (F4). Desde o Passo 09 (candidata à tag `v2-decoupled`), a aplicação está **desacoplada dos providers**:

- cada feature pede uma **capacidade lógica** (`ticket-classification`, `reply-suggestion`, `topics-report`, `order-extraction`) por um contrato de uma operação, `ports.LanguageModel.complete(capability, prompt)`;
- um único adapter (`app/helpdesk/adapters/gateway.py`) fala com o **AI Gateway** (LiteLLM Proxy, serviço `gateway`), e só `main.py` o conhece;
- modelos físicos, chaves dos providers e `max_tokens` ficam no gateway (`gateway/config.yaml`); o serviço `app` recebe só `GATEWAY_URL` e `GATEWAY_API_KEY`.

```mermaid
flowchart LR
    C[Cliente] --> E[edge :8000]
    E --> M[app: main]
    M --> F[F1, F2, F3, F4]
    F --> P{{ports.LanguageModel}}
    AD[adapters.gateway] -.implementa.-> P
    M -->|injeta| AD
    AD -->|GATEWAY_API_KEY| G[gateway :4000]
    G --> PF[provider-fake :8090]
    style P fill:#d4edda,stroke:#1e8449
    style AD fill:#d6eaf8,stroke:#2471a3
```

| Já implementado | Ainda pendente (não existe nesta versão) |
|---|---|
| comportamento externo da v1 preservado (32 testes, contratos HTTP idênticos) | timeout explícito, retry e backoff decididos (Passo 10) |
| todas as chamadas pelo gateway, com capacidades lógicas | fallback e modelo fraco por capacidade (Passo 11) |
| troca de modelo só na configuração do gateway | chave por consumidor, orçamento e limites (Passo 12) |
| credenciais dos providers fora da aplicação | streaming da sugestão (Passo 14) e relatório mensal assíncrono (Passo 15) |

A aplicação **não** tem fallback nem resiliência: com um provider fora do ar, a feature correspondente falha; com o gateway fora do ar, as quatro falham. Detalhes do passo em [docs/v2/relatorio-v2.md](docs/v2/relatorio-v2.md).

## Como rodar

### 1. Subir o ambiente

```bash
cp .env.example .env        # só na primeira vez
docker compose up -d --build --wait
curl http://localhost:8000/health                # {"status":"ok"}
curl http://localhost:4000/health/readiness      # {"status":"healthy","db":"Not connected"}
```

No PowerShell, use `Copy-Item .env.example .env` e `curl.exe`. Dependências: só Docker com Compose. Não há serviço pago nem credencial privada: as chaves do `.env.example` só funcionam contra o provider-fake. Verificado numa cópia limpa: 21,6 s até os 4 serviços saudáveis e `32 passed` ([evidência](docs/v2/evidencias/24-init-reprodutivel.txt)).

A aplicação só é acessada pela borda (`http://localhost:8000`). O provider-fake expõe a administração em `http://localhost:8090/admin/*`. O AI Gateway responde em `http://localhost:4000` (porta publicada só para testes; dentro do compose ele é `http://gateway:4000`).

| Serviço | Porta no host | Papel | Variáveis que recebe |
|---|---|---|---|
| `edge` | 8000 | borda (nginx, 30 s), única entrada do helpdesk | — |
| `app` | — | FastAPI do helpdesk | `GATEWAY_URL`, `GATEWAY_API_KEY` |
| `gateway` | 4000 | AI Gateway (LiteLLM Proxy `v1.102.1`), configuração em `gateway/config.yaml` | `FAKE_OPENAI_KEY`, `FAKE_ANTHROPIC_KEY`, `GATEWAY_MASTER_KEY` |
| `provider-fake` | 8090 | providers simulados (`openai` e `anthropic`) e `/admin/*` | `FAKE_OPENAI_KEY`, `FAKE_ANTHROPIC_KEY` |

Nenhum serviço usa `env_file`: cada um recebe do `.env`, por interpolação, só as variáveis que usa. Se faltar alguma, o compose para com `defina ... no .env`. A `GATEWAY_API_KEY` da app é, provisoriamente, o valor da master key do gateway ([ADR 0003](docs/adr/0003-ai-gateway.md)); chaves por consumidor entram no Passo 12. Logs do gateway: `docker compose logs gateway`.

### 2. Rodar os testes de caracterização

Os testes chamam a aplicação real pela borda, com o provider-fake de verdade (sem mocks). Antes de começar, eles conferem o `/health` e fazem `POST /admin/reset` no provider para garantir o modo `normal`.

Opção A, Python local (3.12 ou mais recente):

```bash
python -m venv .venv
. .venv/bin/activate              # Windows: .venv\Scripts\Activate.ps1
pip install -r tests/requirements.txt
python -m pytest tests/characterization -v
```

Opção B, sem instalar nada no host (só Docker):

```bash
docker run --rm -v "${PWD}:/w" -w /w -e PYTHONDONTWRITEBYTECODE=1 \
  -e HELPDESK_BASE_URL=http://host.docker.internal:8000 \
  -e PROVIDER_ADMIN_URL=http://host.docker.internal:8090 \
  python:3.12-slim sh -c "pip install -q -r tests/requirements.txt && python -m pytest tests/characterization -v -p no:cacheprovider"
```

| Variável | Padrão | Uso |
|---|---|---|
| `HELPDESK_BASE_URL` | `http://localhost:8000` | Borda (edge) do helpdesk |
| `PROVIDER_ADMIN_URL` | `http://localhost:8090` | Admin do provider-fake (reset para o modo `normal`) |

Resultado esperado: `32 passed` em cerca de 60 s (F1 13, F4 9, F2 4, F3 6). A F2 leva ~16 s por caso e a F3 (um dia) ~10 s, ambas abaixo dos 30 s da borda. A suíte é a mesma da `v1-coupled` (`git diff v1-coupled -- tests/characterization/` vazio).

Os valores esperados vêm de respostas reais observadas (golden masters em `tests/characterization/expected/`). Uma falha significa que o comportamento mudou: confira se a mudança foi intencional antes de atualizar qualquer expectativa. Detalhes em [docs/caracterizacao/relatorio-caracterizacao.md](docs/caracterizacao/relatorio-caracterizacao.md).

Verificações complementares do Passo 09 (caminhos que a suíte não cobre):

```bash
# adapter e features contra um gateway simulado: 502, campos nulos, lotes da F3, falha com 1 requisição
docker run --rm -v "${PWD}:/w" -v "${PWD}/data:/data:ro" -w /w -e PYTHONDONTWRITEBYTECODE=1 python:3.12-slim \
  sh -c "pip install -q -r app/requirements.txt httpx && python docs/v2/verificacao_v2.py F1 F4 F2 F3"
# pela borda: quem atendeu cada feature (features), falha injetada (falha F1|F2|F3|F4), contagem (contar)
docker run --rm -v "${PWD}:/w" -w /w -e HELPDESK_BASE_URL=http://host.docker.internal:8000 \
  -e PROVIDER_ADMIN_URL=http://host.docker.internal:8090 python:3.12-slim python docs/v2/sondas_v2.py features
```

### 3. Voltar a uma versão marcada

```bash
git worktree add --detach ../helpdesk-v1 v1-coupled
git worktree add --detach ../helpdesk-v2 v2-decoupled      # depois que a tag existir
```

Para subir duas versões, uma de cada vez, use nomes de projeto distintos (`docker compose -p helpdesk-v1 up -d --build --wait`) e pare uma antes de subir a outra (as portas são as mesmas).

### 4. Testar o AI Gateway diretamente

O gateway também pode ser chamado sem a app, com a chave do `.env`:

```bash
curl -s localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-gateway-local-0001" -H "Content-Type: application/json" \
  -d '{"model": "ticket-classification", "messages": [{"role": "user", "content": "TASK: classify\nMeu pedido #481516 não chegou"}]}'
curl -s "localhost:8090/admin/calls?last=1"     # provider e modelo físico que atenderam
```

Experimentos reprodutíveis do Passo 07 (autenticação, quatro capacidades, normalização, erros, streaming, latência, retries), uma fase por vez:

```bash
docker run --rm -v "${PWD}:/w" -w /w -e PYTHONDONTWRITEBYTECODE=1 \
  -e GATEWAY_URL=http://host.docker.internal:4000 -e PROVIDER_URL=http://host.docker.internal:8090 \
  python:3.12-slim python docs/gateway/experimentos.py capacidades
```

Fases: `probe`, `auth`, `capacidades`, `normalizacao`, `erros`, `latencia`, `streaming`, `retries` (cada uma começa com `POST /admin/reset`). Resultados e análise em [docs/gateway/relatorio-gateway.md](docs/gateway/relatorio-gateway.md).

### 5. Medir o acoplamento (métricas de Robert C. Martin)

Pré-requisito: Python 3.12 ou mais recente. A ferramenta analisa só o código-fonte (AST): não precisa do Docker no ar e não executa os módulos analisados.

```bash
pip install -r metrics/requirements.txt pytest     # matplotlib==3.11.2 (só para o gráfico)
python -m pytest tests/metrics -q                  # testes da própria ferramenta (64)
python metrics/measure.py --source app/helpdesk --name v2-decoupled                      # código atual
git worktree add --detach ../helpdesk-v1 v1-coupled
python metrics/measure.py --source ../helpdesk-v1/app/helpdesk --name v1-coupled         # qualquer checkout
```

| Opção | Obrigatória | Uso |
|---|---|---|
| `--source` | sim | diretório do pacote a medir; aponte para qualquer checkout (worktree, outra pasta) |
| `--name` | sim | nome da medição; vira `metrics/results/<name>.csv` e `.png` |
| `--output-dir` | não | outro diretório de saída (padrão `metrics/results/`) |
| `--root-package` | não | pacote raiz dos imports absolutos (padrão: nome do diretório de `--source`) |
| `--no-plot` | não | só o CSV |

Saída: 0 sucesso, 1 arquivo ilegível ou com erro de sintaxe (nada é gravado), 2 argumentos inválidos. Sem Python no host: `docker run --rm -v "${PWD}:/w" -w /w python:3.12-slim sh -c "pip install -q -r metrics/requirements.txt && python metrics/measure.py --source app/helpdesk --name v2-decoupled"`.

## Tabela de capacidades

A aplicação pede **capacidades lógicas**; o gateway decide qual modelo físico atende ([ADR 0004](docs/adr/0004-logical-capabilities.md)). Na `v2-decoupled`, todas usam o modelo `large` que a v1 já usava, e as quatro são usadas pela aplicação.

| Capacidade lógica | Feature | Modelo primário | Fallback técnico | Modelo fraco | Tentativas máximas |
|---|---|---|---|---|---|
| `ticket-classification` | F1 classificação | `openai/gpt-fake-large` | pendente (Passo 11) | pendente (Passo 11) | não configurado (Passo 10)¹ |
| `reply-suggestion` | F2 sugestão | `anthropic/claude-fake-large` (`max_tokens` 2000) | pendente (Passo 11) | pendente (Passo 11) | não configurado (Passo 10)¹ |
| `topics-report` | F3 relatório | `anthropic/claude-fake-large` (`max_tokens` 2000) | pendente (Passo 11) | pendente (Passo 11) | não configurado (Passo 10)¹ |
| `order-extraction` | F4 extração | `openai/gpt-fake-large` | pendente (Passo 11) | pendente (Passo 11) | não configurado (Passo 10)¹ |

¹ Nenhuma política foi decidida. Observado: o adapter não retenta (`max_retries=0`) e o LiteLLM retenta 2 vezes por padrão em 5xx, com backoff. Sob falha persistente, cada feature faz 3 chamadas ao provider e responde 500 em 4,0 a 4,6 s (na v1, 1,2 a 1,4 s) ([evidência](docs/v2/evidencias/16-falha-depois.txt)).

## Fluxos

Os quatro fluxos são síncronos (rotas `def`, resposta só no fim, sem streaming) e seguem o mesmo caminho: `edge` → `main` → feature → `ports.LanguageModel` → `adapters.gateway` → `gateway` → provider. O contrato HTTP é o mesmo da v1 (OpenAPI idêntico, [evidência](docs/v2/evidencias/22-openapi.txt)).

| Fluxo | Rota | Capacidade | Chamadas ao modelo | Tempo típico |
|---|---|---|---|---|
| F1 classificação | `POST /tickets/classification` | `ticket-classification` | 1; JSON validado (502 se a categoria ou a prioridade não existir) | ~1,1 s |
| F2 sugestão | `POST /tickets/reply-suggestion` | `reply-suggestion` | 1; texto devolvido como veio | ~16 s |
| F3 relatório | `POST /reports/topics` | `topics-report` | 1 por lote de 150 tickets do período, em série; temas somados e ordenados | ~10 s por dia; o mês passa dos 30 s da borda (Dor 1) |
| F4 extração | `POST /tickets/extraction` | `order-extraction` | 1; JSON validado (502 se o número do pedido tiver formato inválido) | ~1,2 s |

```bash
curl -s -X POST localhost:8000/tickets/classification -H "Content-Type: application/json" \
  -d '{"ticket_id": "TK-00042", "text": "Meu pedido #481516 não chegou e já passou do prazo, urgente"}'
# {"ticket_id":"TK-00042","category":"delivery","priority":"high"}

curl -s -X POST localhost:8000/tickets/reply-suggestion -H "Content-Type: application/json" \
  -d '{"ticket_id": "TK-00042", "text": "Meu pedido #481516 não chegou e já passou do prazo, urgente"}'
# {"ticket_id":"TK-00042","suggestion":"Olá! Sinto muito pelo transtorno ..."}

curl -s -X POST localhost:8000/reports/topics -H "Content-Type: application/json" \
  -d '{"start": "2026-08-01", "end": "2026-08-01"}'
# {"start":"2026-08-01","end":"2026-08-01","total_tickets":137,"topics":[...]}

curl -s -X POST localhost:8000/tickets/extraction -H "Content-Type: application/json" \
  -d '{"ticket_id": "TK-00200", "text": "Pedido #481516, o fone de ouvido bluetooth veio com chiado"}'
# {"ticket_id":"TK-00200","order_number":"#481516","product":"fone de ouvido bluetooth"}
```

No Windows, o PowerShell corrompe os acentos do corpo: use Git Bash, `--data-binary @arquivo.json` ou a sonda (`docs/v2/sondas_v2.py features`). Os diagramas de sequência dos quatro fluxos estão em [docs/v2/relatorio-v2.md](docs/v2/relatorio-v2.md), seção 22.

## Troca de modelo

O mapeamento capacidade → modelo físico fica só em [`gateway/config.yaml`](gateway/config.yaml). Para trocar o modelo de uma capacidade, altere o bloco `litellm_params` dela e reinicie **só** o gateway. Exemplo com a F2 (feito no Passo 09):

```yaml
  - model_name: reply-suggestion
    litellm_params:
      model: openai/gpt-fake-large                  # antes: anthropic/claude-fake-large
      api_base: http://provider-fake:8090/openai/v1 # antes: http://provider-fake:8090/anthropic
      api_key: os.environ/FAKE_OPENAI_KEY           # antes: os.environ/FAKE_ANTHROPIC_KEY
      max_tokens: 2000
```

```bash
docker inspect -f "{{.Id}} {{.Image}} {{.State.StartedAt}}" desafio-arquitetura-era-ia-1-app-1   # antes
docker compose restart gateway && docker compose up -d --wait                                     # ~9 s
curl -s -X POST localhost:8000/tickets/reply-suggestion -H "Content-Type: application/json" \
  -d '{"ticket_id": "TK-00042", "text": "Meu pedido #481516 não chegou e já passou do prazo, urgente"}'
curl -s "localhost:8090/admin/calls?last=1"     # provider e model mostram quem atendeu
docker inspect -f "{{.Id}} {{.Image}} {{.State.StartedAt}}" desafio-arquitetura-era-ia-1-app-1   # depois: igual
```

Resultado registrado ([evidência](docs/v2/evidencias/20-troca-modelo.txt)): `/admin/calls` passou de `anthropic`/`claude-fake-large` para `openai`/`gpt-fake-large`; a resposta pela borda ficou idêntica byte a byte; o container da app manteve Id, imagem e horário de início; os arquivos de `app/` não mudaram. Para desfazer: `git restore gateway/config.yaml` e o mesmo restart. Na v1, a mesma troca exigia editar `config.py` e reconstruir a app (Dor 4).

## Métrica

A régua vem do enunciado; a ferramenta está em `metrics/` e a decisão em [ADR 0001](docs/adr/0001-metrics-and-architectural-stability.md). Fundamentos, exercícios e glossário em [docs/metricas/fundamentacao.md](docs/metricas/fundamentacao.md); análise da v1 em [docs/metricas/relatorio-v1-coupled.md](docs/metricas/relatorio-v1-coupled.md); da v2 em [docs/v2/relatorio-v2.md](docs/v2/relatorio-v2.md), seção 15.

| Item | Definição |
|---|---|
| Componente | cada `.py` de `app/helpdesk/` (recursivo), exceto `__init__.py`; nome com pontos (`adapters.gateway`) |
| Dependência | import absoluto ou relativo que resolve para **outro** componente; externos, biblioteca padrão, duplicatas, transitivas e autorreferências não contam |
| Ca | componentes distintos que importam o componente |
| Ce | componentes distintos que o componente importa |
| I | Ce / (Ca + Ce); 0 se ambos forem 0 |
| A | classes que herdam de `typing.Protocol` ou `abc.ABC` / total de classes; 0 sem classes |
| D | \|A + I − 1\| |
| Zona de dor | A < 0,5 e I < 0,5 e D ≥ 0,5 |

**Análise estática:** cada arquivo vira uma AST (`ast.parse`); os nós `Import`/`ImportFrom` são resolvidos contra o inventário de componentes (inclusive relativos, aliases e símbolos reexportados por `__init__.py`), e os `ClassDef` têm as bases checadas pela origem do nome. Cálculo com frações exatas; só o resultado é arredondado (2 casas, meio para cima).

**Main Sequence:** a reta A + I = 1. Perto dela, o componente equilibra quanto é usado (estabilidade) com quanto é extensível (abstração). Longe, abaixo e à esquerda, fica a zona de dor: concreto e difícil de mudar.

### Baseline da v1 (`v1-coupled`, commit `8028305`)

| Componente | Ca | Ce | I | A | D | Zona de dor |
|---|---|---|---|---|---|---|
| classification | 1 | 3 | 0.75 | 0.00 | 0.25 | |
| config | 6 | 0 | 0.00 | 0.00 | 1.00 | **sim** |
| extraction | 1 | 3 | 0.75 | 0.00 | 0.25 | |
| llm | 4 | 1 | 0.20 | 0.00 | 0.80 | **sim** |
| main | 0 | 5 | 1.00 | 0.00 | 0.00 | |
| report | 1 | 4 | 0.80 | 0.00 | 0.20 | |
| schemas | 5 | 0 | 0.00 | 0.00 | 1.00 | **sim** |
| suggestion | 1 | 3 | 0.75 | 0.00 | 0.25 | |
| tickets | 1 | 1 | 0.50 | 0.00 | 0.50 | no limite (I = 0,5) |

![Main Sequence da v1-coupled](metrics/results/v1-coupled.png)

**Leitura:** a v1 tem zero abstrações. As dependências apontam para o que é mais estável (o SDP é respeitado em todas as 20 arestas), mas o que é estável é concreto e tecnológico: `llm` (SDKs e um método por provider) e `config` (nomes de modelos físicos). É a expressão estrutural das Dores 3 e 4 do diagnóstico.

**Exigiam investigação (Passo 05):** `llm` e `config` (problemas reais); `tickets` (no limite); as features (métrica boa, mas escolhiam o provider pelo nome da função, um acoplamento semântico que a régua não vê).

**Limitações:** a régua não conta SDKs e frameworks, acoplamento semântico, configuração de runtime, contratos HTTP, coesão nem frequência de mudança; módulos isolados e DTOs geram falsos positivos. Nenhuma mudança é feita só para baixar D (Goodhart).

Medição intermediária do piloto (só a F1 migrada): [`docs/piloto/metricas/pilot-after.csv`](docs/piloto/metricas/pilot-after.csv), 22 arestas, `llm` ainda na zona de dor (3/1/0,25/0/0,75).

### V2 desacoplada (`v2-decoupled`)

Medida com o mesmo comando sobre o código do Passo 09 e reproduzida com CSV idêntico ([`metrics/results/v2-decoupled.csv`](metrics/results/v2-decoupled.csv)).

| Componente | Ca | Ce | I | A | D | Zona de dor | Mudança desde a v1 |
|---|---|---|---|---|---|---|---|
| adapters.gateway | 1 | 2 | 0.67 | 0.00 | 0.33 | | novo: o único componente que fala com o gateway (SDK `openai`); só `main` o importa |
| classification | 1 | 2 | 0.67 | 0.00 | 0.33 | | troca `llm` e `config` por `ports` |
| config | 3 | 0 | 0.00 | 0.00 | 1.00 | **sim** | Ca 6 → 3; perdeu chaves, URLs e modelos físicos |
| extraction | 1 | 2 | 0.67 | 0.00 | 0.33 | | idem F1 |
| main | 0 | 6 | 1.00 | 0.00 | 0.00 | | ganha `adapters.gateway` (Composition Root) |
| ports | 5 | 0 | 0.00 | 1.00 | 0.00 | | novo: o contrato, sobre a Main Sequence |
| report | 1 | 4 | 0.80 | 0.00 | 0.20 | | troca `llm` por `ports` |
| schemas | 5 | 0 | 0.00 | 0.00 | 1.00 | **sim** | inalterado |
| suggestion | 1 | 2 | 0.67 | 0.00 | 0.33 | | idem F1 |
| tickets | 1 | 1 | 0.50 | 0.00 | 0.50 | no limite | inalterado |

![Main Sequence da v2-decoupled](metrics/results/v2-decoupled.png)

**Comparação.** 20 → 19 arestas. `llm` (D 0,80, zona de dor) deixou de existir; o componente mais usado passou a ser uma abstração (`ports`, A=1, Ca=5, D=0). Zona de dor: {`config`, `llm`, `schemas`} → {`config`, `schemas`}. O resultado é idêntico à projeção do plano (seção 14.2).

**Interpretação.** As features **pioraram** em D (0,25 → 0,33) porque perderam dependências e foram para o centro do gráfico; isso era esperado e foi aceito, sem dependência acrescentada para "corrigir" o número. O componente concreto que fala com o gateway, `adapters.gateway`, ficou fora da zona de dor com dois imports que têm função (`config` para endereço e chave, `ports` para a checagem de tipo).

**Exceções.** `schemas` é exceção candidata (DTOs do contrato HTTP público). `config` virou candidata: não tem mais nada volátil, só o endereço e a chave do gateway e dois parâmetros do relatório; a decisão entre declará-lo estável ou dissolvê-lo é do Passo 16. `adapters.gateway` e as features nunca são exceção. A terceira medição, da arquitetura final, será adicionada aqui.

## Mapa de decisões

| ADR | Decisão | Nível | Status |
|---|---|---|---|
| [0001](docs/adr/0001-metrics-and-architectural-stability.md) | medir acoplamento com ferramenta estática própria | software | aceita; medições v1 e v2 |
| [0002](docs/adr/0002-contracts-and-dependency-inversion.md) | features dependem de um contrato de IA; só a composição conhece o adapter | software | aceita (as quatro features) |
| [0003](docs/adr/0003-ai-gateway.md) | AI Gateway self-hosted: LiteLLM Proxy `v1.102.1`; toda a IA passa por ele | solução | aceita (infraestrutura e as quatro features) |
| [0004](docs/adr/0004-logical-capabilities.md) | capacidades lógicas mapeadas no gateway | solução | aceita (quatro capacidades) |

Fallback, governança e modos de execução terão ADRs próprios quando forem decididos (Passos 10 a 15). Plano da refatoração: [docs/refactoring-plan.md](docs/refactoring-plan.md) (versão 1.2). Piloto da F1: [docs/piloto/relatorio-piloto.md](docs/piloto/relatorio-piloto.md). Refatoração completa: [docs/v2/relatorio-v2.md](docs/v2/relatorio-v2.md).

## Diagnóstico da v1

### Condições dos experimentos

| Item | Valor |
|---|---|
| Commit | `a1aedd76fc046077edc71c11222f3f999d3e1433` ("initial commit"); `git diff --stat upstream/main -- app provider-fake edge data compose.yaml` vazio |
| Data | 24/11/2026, entre 19:10 e 19:58 UTC |
| Ambiente | Windows + Docker Desktop 29.9.2, Compose v5.6.1; `cp .env.example .env && docker compose up -d --build --wait` |
| SDKs no container `app` | `openai 3.19.0`, `anthropic 1.8.0` |
| Entrada | todas as features **pela borda** (`localhost:8000`); `/admin/*` pelo `localhost:8090` |
| Medição | `curl -w "status=%{http_code} ttfb=%{time_starttransfer} total=%{time_total}"`, com horário UTC registrado antes de cada requisição |
| Isolamento | `POST /admin/reset` antes de cada experimento; espera até não haver chamada com `duration_ms: null` em `/admin/calls`; `docker compose restart app` quando sobrava chamada órfã |
| Corpo padrão (F1, F2, F4) | `{"ticket_id": "TK-00042", "text": "Meu pedido #481516 não chegou e já passou do prazo, urgente"}` |

Comandos de apoio:

```bash
curl -s -X POST localhost:8090/admin/reset
curl -s localhost:8090/admin/failures
curl -s "localhost:8090/admin/calls?last=50"
curl -s -X POST localhost:8090/admin/failures -H "Content-Type: application/json" -d '{"provider": "openai", "mode": "error_500"}'
docker compose logs app --since 5m
docker compose logs edge --since 5m
```

---

### Dor 1: o relatório do mês não chega

**Problema.** O painel pede o relatório de agosto (5.000 tickets) e recebe erro.

**Hipótese.** A F3 processa os lotes em série dentro de uma única requisição HTTP. O tempo acumulado passa dos 30 s da borda, e o processamento continua depois que o cliente desiste.

**Comando**

```bash
curl -s -o /dev/null -w "status=%{http_code} ttfb=%{time_starttransfer} total=%{time_total}\n" \
  -X POST localhost:8000/reports/topics -H "Content-Type: application/json" \
  -d '{"start": "2026-08-01", "end": "2026-08-31"}'
```

**Referência (1 dia, `2026-08-01`):** `200` em 9,84 s, `total_tickets: 137`, 15 temas, 1 chamada `topics` (6.132 tokens de entrada / 360 de saída).

**Resultado observado (mês)**

| Medida | Valor |
|---|---|
| Status | **`504 Gateway Time-out`** (HTML do nginx) |
| Tempo | `ttfb=30.031 total=30.032` |
| Log da borda | `upstream timed out (110: Operation timed out) while reading response header from upstream ... POST /reports/topics` |
| Chamadas ao provider | **34** `anthropic / claude-fake-large / topics`, todas `200`, estritamente sequenciais, de 9,2 a 9,85 s cada |
| Período das chamadas | 19:11:02,767 → cerca de 19:16:34 UTC (**cerca de 5 min depois do `504`**) |
| Chamadas iniciadas depois do `504` | **30** (mais 1 que estava em andamento no momento do corte) |
| Tokens depois do `504` | 195.483 de entrada / 10.742 de saída |
| Custo estimado depois do `504` | **US$ 0,75** (US$ 0,77 incluindo a chamada em andamento), a US$ 3/M de entrada e US$ 15/M de saída |
| Custo do mês inteiro | 222.114 / 12.162 tokens → US$ 0,85 |
| Log do `app` | **nenhuma** linha `POST /reports/topics` para essa requisição; o trabalho órfão terminou em silêncio |

Trecho de `/admin/calls` (ts, status, entrada, saída, ms):

```
19:11:02.767  200  6711  361  9827
19:11:12.595  200  6637  361  9826
19:11:22.424  200  6627  361  9826
19:11:32.252  200  6656  337  9228   <- começou 0,6 s antes do 504
... 29 chamadas de ~9,8 s ...
19:16:25.448  200  2225  315  8676   <- último lote (~50 tickets)
```

**Causa no código**

```python
# app/helpdesk/report.py:15-18
for first in range(0, len(selected), config.TICKETS_PER_CALL):
    batch = selected[first:first + config.TICKETS_PER_CALL]
    content = "\n".join(f"[{t['id']}] {t['text']}" for t in batch)
    answer = llm.parse_json(llm.call_anthropic(config.REPORT_MODEL, "topics", content))
```

```python
# app/helpdesk/main.py:30-32  (rota síncrona: executa numa thread, que não é cancelada)
@app.post("/reports/topics")
def topics_report(period: PeriodInput) -> TopicsReport:
    return report.topics(period)
```

```nginx
# edge/nginx.conf
proxy_read_timeout 30s;
```

**Causa raiz.** O tamanho do lote (`TICKETS_PER_CALL = 150`, `config.py:18`) é imposto pela janela de 8.000 tokens do modelo. Por isso, 5.000 tickets viram 34 chamadas. Como elas rodam em série, o tempo é de 34 × ~9,8 s ≈ 5,4 min, contra uma borda que espera no máximo 30 s. A entrega é síncrona e não há como o cliente buscar o resultado depois. A rota `def` roda numa thread do pool, e a desconexão do cliente não interrompe essa thread: **o timeout da borda encerra a conexão, mas não cancela o processamento**.

**Impacto.** O relatório nunca chega a quem pediu (nem mesmo em parte), e cerca de 88% do custo é pago depois que o cliente desistiu. Cada nova tentativa do usuário dispara outra execução completa e órfã.

**Conclusão.** ✅ Comprovado. Execução síncrona e sequencial, incompatível com o orçamento de latência da borda, e sem cancelamento.

---

### Dor 2: a sugestão deixa o atendente esperando sem ver nada

**Problema.** O atendente pede uma sugestão de resposta e a tela fica vazia até o texto inteiro ficar pronto.

**Hipótese.** A aplicação chama o modelo sem streaming e só responde depois da geração completa. O tempo até o primeiro byte (TTFB) é igual ao tempo total, que cresce com o tamanho do texto.

**Comandos**

```bash
# 5 repetições
curl -s -o /dev/null -w "status=%{http_code} ttfb=%{time_starttransfer} total=%{time_total}\n" \
  -X POST localhost:8000/tickets/reply-suggestion -H "Content-Type: application/json" \
  -d '{"ticket_id": "TK-00042", "text": "Meu pedido #481516 não chegou e já passou do prazo, urgente"}'

# chegada dos bytes, sem buffer do curl
curl -N -v --trace-time -X POST localhost:8000/tickets/reply-suggestion -H "Content-Type: application/json" -d '...'
```

**Resultado observado**

| Medida | Valor |
|---|---|
| Status | `200` nas 5 repetições, 2.606 bytes |
| TTFB × total (s) | 15,956/15,957 · 15,955/15,955 · 15,955/15,956 · 15,955/15,956 · 15,956/15,956 |
| Média | **15,956 s** de TTFB = 15,956 s de total |
| `curl -N --trace-time` | status, headers (`Content-Type: application/json`, `Content-Length: 2606`) e corpo chegaram **juntos**, 15,95 s depois do envio |
| Sonda de chunks pela borda | headers 15,963 s; primeiro byte 15,963 s; último byte 15,963 s |
| Tempo até o primeiro conteúdo para o atendente | **15,96 s** (a resposta é um JSON único) |
| `/admin/calls` | `anthropic / claude-fake-large / suggest`, **`stream: false`**, 19 tokens de entrada / **606 de saída**, 15.950 ms |
| Mesmo prompt direto no provider com `stream: true` (só comparação) | headers 0,008 s; **primeiro texto (TTFT) 0,809 s**; fim 16,21 s |

A conta do provider fecha com a medição: 0,8 s de TTFT + 606 tokens ÷ 40 tokens/s = **15,95 s**. O primeiro token existe em 0,8 s, mas o atendente só o vê em 15,96 s.

**Causa no código**

```python
# app/helpdesk/llm.py:20-26
def call_anthropic(model: str, task: str, content: str) -> str:
    response = anthropic_client.messages.create(
        model=model,
        max_tokens=config.MAX_OUTPUT_TOKENS,
        messages=[{"role": "user", "content": f"TASK: {task}\n{content}"}],
    )                                    # sem stream: espera a geração inteira
    return response.content[0].text

# app/helpdesk/suggestion.py:6-7
text = llm.call_anthropic(config.SUGGESTION_MODEL, "suggest", ticket.text)
return ReplySuggestion(ticket_id=ticket.ticket_id, suggestion=text)
```

**Causa raiz.** O contrato da F2 é síncrono e devolve um JSON único (`ReplySuggestion`). A integração usa `messages.create` sem `stream`, e a aplicação acumula o texto inteiro antes de responder. Por isso, a latência percebida é igual à latência total, que é proporcional aos tokens de saída. O buffering do nginx (padrão) não chega a ser exercitado, porque o `app` não envia nada antes do fim.

**Impacto.** São 16 s de tela vazia por sugestão. Uma resposta 2× maior dobraria a espera e passaria de 30 s, gerando `504` (foi o que aconteceu no modo `slow`, na Dor 3).

**Conclusão.** ✅ Comprovado. A diferença entre o TTFT (0,81 s) e o primeiro conteúdo visível (15,96 s) é desperdício de experiência causado pelo modo de entrega.

---

### Dor 3: com um provider fora do ar ou travado, parte do helpdesk para

**Problema.** Uma instabilidade em um provider derruba as features ligadas a ele.

**Hipótese.** Cada feature está presa a um único provider, sem destino alternativo. A aplicação depende dos padrões dos SDKs (timeout longo e retries), que amplificam a latência e não respeitam os 30 s da borda.

**Padrões dos SDKs** (lidos no container: `client.timeout`, `client.max_retries`, `_constants.py` e `_base_client.py`)

| | `openai 3.19.0` | `anthropic 1.8.0` |
|---|---|---|
| Timeout | connect 5 s, read/write/pool **600 s** | connect 5 s, read/write/pool **600 s** |
| Retries | **2** (3 tentativas no total) | **2** (3 tentativas no total) |
| Retenta | 408, 409, 429, ≥500 (respeita `x-should-retry`) | 408, 409, 429, ≥500 (respeita `x-should-retry`) |
| Backoff sem `Retry-After` | `min(0,5·2ⁿ, 8) × jitter(0,75–1)` | igual |
| Com `Retry-After` | usa se 0 < valor ≤ 120 s | usa se > 0 |
| Timeout do lado do cliente | retenta | **não retenta** (`APITimeoutError` direto), lido no código e não observado |

**Comandos**

```bash
curl -s -X POST localhost:8090/admin/reset
curl -s -X POST localhost:8090/admin/failures -H "Content-Type: application/json" -d '{"provider": "openai", "mode": "error_500"}'
# F1, F2, F3 (só 2026-08-01) e F4 pela borda com curl -w; depois:
curl -s "localhost:8090/admin/calls?last=50"
docker compose logs app --since 5m
```

**Resultado observado (matriz de impacto; F3 com 1 dia)**

| Provider | Modo | F1 | F2 | F3 | F4 | Tentativas e intervalos |
|---|---|---|---|---|---|---|
| openai | `error_500` | **500** em 1,30 s | 200 15,96 s | 200 9,84 s | **500** em 1,18 s | 3 por requisição; [0,47 s, 0,83 s] e [0,39 s, 0,79 s] |
| anthropic | `error_500` | 200 1,08 s | **500** em 1,28 s | **500** em 1,51 s | 200 1,08 s | 3; [0,44 s, 0,83 s] e [0,50 s, 0,98 s] |
| openai | `error_429` | **500** em 4,01 s | 200 | 200 | **500** em 4,01 s | 3; [2,00 s, 2,00 s] (respeitou `Retry-After: 2`) |
| anthropic | `error_429` | 200 | **500** em 4,01 s | **500** em 4,05 s | 200 | 3; [2,00 s, 2,00 s] |
| openai | `slow` | 200 em 10,76 s | 200 | 200 | 200 em 10,76 s | 1 |
| anthropic | `slow` | 200 | **504** em 30,03 s | **504** em 30,03 s | 200 | 1; órfãs terminaram com 200 após 159,5 s (F2) e 98,0 s (F3) |
| openai | `timeout` | **504** em 30,03 s | 200 15,96 s | 200 9,84 s | não executada | **3 tentativas de 300 s**: 19:30:12, 19:35:13, 19:40:14; terminou por volta de 19:45:14 |
| anthropic | `timeout` | 200 1,08 s | **504** em 30,03 s | não executada | 200 1,08 s | 2ª tentativa às 19:52:52 (+300,4 s); interrompida com `docker compose restart app` |

Logs do `app`: `openai.InternalServerError: Error code: 500`, `openai.RateLimitError: Error code: 429`, `anthropic.InternalServerError`, `anthropic.RateLimitError` e, no timeout, `openai.InternalServerError: Error code: 504 - Timeout simulado` às 19:45:14. Nenhuma das requisições abandonadas (504 na borda) gerou linha de acesso.

**Causa no código**

```python
# app/helpdesk/llm.py:8-9  (sem timeout, max_retries ou destino alternativo)
openai_client = OpenAI(api_key=config.OPENAI_API_KEY, base_url=config.OPENAI_BASE_URL)
anthropic_client = Anthropic(api_key=config.ANTHROPIC_API_KEY, base_url=config.ANTHROPIC_BASE_URL)

# app/helpdesk/classification.py:11  (provider fixo pela função)
text = llm.call_openai(config.CLASSIFICATION_MODEL, "classify", ticket.text)
```

Nenhuma feature tem `try/except` em torno da chamada ao modelo: a exceção do SDK vira `500 Internal Server Error`.

**Causa raiz.** Cada feature escolhe o provider no código (`call_openai` para F1 e F4; `call_anthropic` para F2 e F3), sem destino equivalente. A aplicação não declara timeout nem política de retry, então herda os padrões dos SDKs: 600 s de leitura e 3 tentativas, ou seja, até cerca de 15 min por requisição contra 30 s da borda. Os erros do provider não são traduzidos: um `429` vira `500` para o cliente.

**Impacto.**
- **Raio de impacto:** um provider fora derruba exatamente metade das features (openai → F1 e F4; anthropic → F2 e F3), embora existam modelos equivalentes no outro provider.
- **Amplificação:** cada requisição gera 3 chamadas ao provider (3× carga num provider já degradado).
- **Trabalho órfão:** com o provider travado, uma F1 que o cliente abandonou em 30 s segurou uma thread do `app` por cerca de 15 min.
- **Lentidão:** a feature de saída longa estoura a borda (F2 em `slow`: 504, com a geração seguindo por 159 s).

**Conclusão.** ✅ Comprovado. Não há resiliência explícita: sem timeout próprio, sem fallback, com retries implícitos dos SDKs que amplificam a latência e a carga.

---

### Dor 4: trocar o modelo de uma feature exige mudar código e reconstruir

**Problema.** Trocar o modelo de uma feature, por exemplo por um mais barato, é uma decisão operacional que hoje exige deploy.

**Hipótese.** Os nomes dos modelos físicos são literais no código. Mudar só o ambiente ou reiniciar o container não basta: é preciso editar `config.py` e reconstruir a imagem.

**Comandos e resultado** (alteração **temporária**, revertida no mesmo experimento)

| Passo | Comando | Resultado em `/admin/calls` |
|---|---|---|
| 1. Original | F1 pela borda | `openai / gpt-fake-large / classify`, 1.076 ms |
| 2. Edição | `CLASSIFICATION_MODEL = "gpt-fake-large"` → `"gpt-fake-mini"` em `app/helpdesk/config.py:10` | — |
| 3. Só reiniciar | `docker compose restart app` + F1 | **continua `gpt-fake-large`**: o código está dentro da imagem |
| 4. Reconstruir | `docker compose up -d --build app --wait` (7,27 s) | durante a troca, `/health` pela borda respondeu **`502`** uma vez |
| 5. Depois do rebuild | F1 pela borda (0,40 s) | **`openai / gpt-fake-mini / classify`**, 374 ms |
| 6. Reverter | `git checkout -- app/helpdesk/config.py` + `docker compose up -d --build app --wait` (6,01 s; outro `502`) | `gpt-fake-large`, 1.076 ms |
| 7. Prova | `git status` e `git diff --stat upstream/main -- app` | ambos vazios |

```python
# app/helpdesk/config.py:9-13
# A classificação e a extração rodam na OpenAI; a sugestão e o relatório, na Anthropic.
CLASSIFICATION_MODEL = "gpt-fake-large"
EXTRACTION_MODEL = "gpt-fake-large"
SUGGESTION_MODEL = "claude-fake-large"
REPORT_MODEL = "claude-fake-large"
```

**Causa raiz.** A escolha do modelo físico é uma decisão de infraestrutura, mas mora no código da aplicação (`config.py`, valores literais) e é consumida diretamente pelas features. O provider também está fixo pela função chamada (`call_openai` / `call_anthropic`). Portanto, trocar `gpt-fake-large` por `claude-fake-large` não seria nem uma mudança de configuração: exigiria trocar a função em `classification.py`. As credenciais (`FAKE_OPENAI_KEY`, `FAKE_ANTHROPIC_KEY`) também chegam ao `app` por `env_file`.

**Impacto.** Cada troca de modelo exige editar o código, gerar uma nova imagem e recriar o container, com indisponibilidade breve observada (`502`). Mudar de provider exige mexer no código das features. Não há como trocar o modelo de uma feature sem passar por desenvolvimento e deploy.

**Conclusão.** ✅ Comprovado. O sistema está acoplado ao modelo físico, ao provider e ao SDK.

---

### Resumo do diagnóstico

| Dor | Status | Causa raiz | Onde |
|---|---|---|---|
| Relatório não chega | ✅ 504 em 30 s; 30 chamadas e US$ 0,75 depois do corte | lotes sequenciais síncronos + rota sem cancelamento | `report.py:15-18`, `main.py:30-32`, `nginx.conf` |
| Tela parada na sugestão | ✅ 15,96 s até o 1º byte (TTFT do modelo: 0,81 s) | chamada sem streaming, resposta JSON única | `llm.py:20-26`, `suggestion.py:6-7` |
| Provider fora derruba metade | ✅ 500/504 nas features do provider; 3 tentativas; até ~15 min órfão | provider fixo por feature, padrões dos SDKs, sem fallback | `llm.py:8-26`, features |
| Troca de modelo exige deploy | ✅ restart não basta; rebuild com 502 | modelo físico literal no código | `config.py:10-13` |
