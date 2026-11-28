# Helpdesk com IA: da integração frágil à arquitetura resiliente

Fork de trabalho do desafio **Arquitetura na Era da IA** (Full Cycle). O enunciado original continua disponível no [repositório base](https://github.com/devfullcycle/desafio-arquitetura-era-ia-1).

> [!NOTE]
> Este README está em construção. Seções presentes: **Visão geral**, **Como rodar**, **Roteiro de governança**, **Tabela de capacidades**, **Tabela de fallback**, **Política de resiliência**, **Fluxos**, **Troca de modelo**, **Métrica**, **Mapa de decisões** e **Diagnóstico da v1**.

## Visão geral

O helpdesk tem quatro funcionalidades de IA, todas síncronas: classificação de tickets (F1), sugestão de resposta (F2), relatório de temas (F3) e extração de dados do pedido (F4). A aplicação é **desacoplada** dos providers (Passo 09, tag `v2-decoupled`), **resiliente** a falha de provider (timeout, retry e fallback, Passos 10 e 11) e **governada** no gateway (Passo 12): consome com uma chave virtual própria, com preço por modelo, orçamento e limite de requisições aplicados antes do provider:

- cada feature pede uma **capacidade lógica** (`ticket-classification`, `reply-suggestion`, `topics-report`, `order-extraction`) por um contrato de uma operação, `ports.LanguageModel.complete(capability, prompt)`;
- um único adapter (`app/helpdesk/adapters/gateway.py`) fala com o **AI Gateway** (LiteLLM Proxy, serviço `gateway`), e só `main.py` o conhece;
- modelos físicos, chaves dos providers, `max_tokens` e preços ficam no gateway (`gateway/config.yaml`); o serviço `app` recebe só `GATEWAY_URL` e `GATEWAY_API_KEY`, que é a chave virtual `helpdesk-app` (nunca a master key).

```mermaid
flowchart LR
    C[Cliente] --> E[edge :8000]
    E --> M[app: main]
    M --> F[F1, F2, F3, F4]
    F --> P{{ports.LanguageModel}}
    AD[adapters.gateway] -.implementa.-> P
    M -->|injeta| AD
    AD -->|chave virtual helpdesk-app| G[gateway :4000]
    G --> PF[provider-fake :8090]
    G --> DB[(gateway-db)]
    BS[gateway-bootstrap] -->|master key: cria chaves| G
    style P fill:#d4edda,stroke:#1e8449
    style AD fill:#d6eaf8,stroke:#2471a3
```

| Já implementado | Ainda pendente (não existe nesta versão) |
|---|---|
| contratos de sucesso da v1 preservados (32 testes, OpenAPI idêntico) | deadline da cadeia dentro do gateway (cadeia órfã, ver ADR 0006) |
| todas as chamadas pelo gateway, com capacidades lógicas | alta disponibilidade do gateway e contadores compartilhados (Redis) |
| troca de modelo só na configuração do gateway | streaming da sugestão (Passo 14) |
| credenciais dos providers fora da aplicação; timeout, retry limitado e backoff ([ADR 0005](docs/adr/0005-resilience-policy.md)) | relatório mensal assíncrono (Passo 15) |
| fallback técnico nas 4 capacidades e mini só na F1/F2 ([ADR 0006](docs/adr/0006-fallback-policy.md)) | |
| chave virtual por consumidor, preço dos 4 modelos, orçamento e RPM com recusa antes do provider ([ADR 0010](docs/adr/0010-gateway-governance.md)) | |

Com um provider fora do ar, cada feature é atendida pelo modelo `large` equivalente do outro provider; com os dois `large` fora, F1 e F2 usam um `mini` e F3 e F4 falham explicitamente (`503`); com o gateway fora do ar, as quatro falham. Detalhes do passo em [docs/v2/relatorio-v2.md](docs/v2/relatorio-v2.md).

## Como rodar

### 1. Subir o ambiente

```bash
cp .env.example .env        # só na primeira vez
docker compose up -d --build --wait
curl http://localhost:8000/health                # {"status":"ok"}
curl http://localhost:4000/health/readiness      # {"status":"healthy","db":"connected"}
```

No PowerShell, use `Copy-Item .env.example .env` e `curl.exe`. Dependências: só Docker com Compose. Não há serviço pago nem credencial privada: as chaves do `.env.example` só funcionam contra o provider-fake. O `up` cria o banco do gateway, aplica as migrações e roda o serviço `gateway-bootstrap`, que cria as três chaves virtuais (ver [Roteiro de governança](#roteiro-de-governança)) e termina; a app só sobe depois dele. Nenhum passo manual. Verificado numa cópia limpa no Passo 12: 28 s até tudo saudável, chaves criadas e quatro features `200` ([evidência](docs/governanca/evidencias/30-ambiente-limpo.txt)).

A aplicação só é acessada pela borda (`http://localhost:8000`). O provider-fake expõe a administração em `http://localhost:8090/admin/*`. O AI Gateway responde em `http://localhost:4000` (porta publicada só para testes; dentro do compose ele é `http://gateway:4000`).

| Serviço | Porta no host | Papel | Variáveis que recebe |
|---|---|---|---|
| `edge` | 8000 | borda (nginx, 30 s), única entrada do helpdesk | — |
| `app` | — | FastAPI do helpdesk | `GATEWAY_URL`, `GATEWAY_API_KEY` (= `HELPDESK_GATEWAY_KEY`) |
| `gateway` | 4000 | AI Gateway (LiteLLM Proxy `v1.102.1`), configuração em `gateway/config.yaml` | `FAKE_OPENAI_KEY`, `FAKE_ANTHROPIC_KEY`, `GATEWAY_MASTER_KEY`, `DATABASE_URL` |
| `gateway-db` | — | Postgres 17.2 do gateway: chaves virtuais e gasto ([ADR 0007](docs/adr/0007-gateway-governance-database.md)) | `GATEWAY_DB_PASSWORD` |
| `gateway-bootstrap` | — | cria ou alinha as chaves virtuais a cada `up` e termina com `Exited (0)` ([ADR 0008](docs/adr/0008-key-bootstrap-service.md)) | `GATEWAY_MASTER_KEY` e as 3 chaves virtuais |
| `provider-fake` | 8090 | providers simulados (`openai` e `anthropic`) e `/admin/*` | `FAKE_OPENAI_KEY`, `FAKE_ANTHROPIC_KEY` |

Nenhum serviço usa `env_file`: cada um recebe do `.env`, por interpolação, só as variáveis que usa. Se faltar alguma, o compose para com `defina ... no .env`. A app recebe só a sua chave virtual: nem master key, nem chave de provider, nem senha do banco (`docker compose exec app env`). Logs: `docker compose logs gateway` e `docker compose logs gateway-bootstrap`.

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

O gateway também pode ser chamado sem a app, com a chave virtual do helpdesk (`HELPDESK_GATEWAY_KEY` do `.env`):

```bash
curl -s localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-helpdesk-local-0001" -H "Content-Type: application/json" \
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

### 6. Testar a resiliência (Passo 10)

Pré-requisito: o ambiente da seção 1 no ar. A suíte liga modos de falha no provider-fake, roda em sequência (não use paralelismo nem rode a caracterização ao mesmo tempo) e reseta o provider antes e depois de cada teste. Leva cerca de 3 min.

```bash
docker run --rm -v "${PWD}:/w" -w /w -e PYTHONDONTWRITEBYTECODE=1   -e HELPDESK_BASE_URL=http://host.docker.internal:8000   -e PROVIDER_ADMIN_URL=http://host.docker.internal:8090   python:3.12-slim sh -c "pip install -q -r tests/resilience/requirements.txt && python -m pytest tests/resilience -v -p no:cacheprovider"
```

Experimentos manuais (Python no host):

```bash
python docs/resiliencia/sondas_resiliencia.py error_500            # normal | error_429 | slow | timeout
python docs/resiliencia/experimentos_extra.py recuperacao
curl -s -X POST localhost:8090/admin/failures -H "Content-Type: application/json"   -d '{"provider": "openai", "model": "gpt-fake-large", "mode": "error_500"}'
curl -s "localhost:8090/admin/calls?last=10"                       # evidência das tentativas
curl -s -X POST localhost:8090/admin/reset                         # sempre restaurar no fim
```

### 7. Testar o fallback (Passo 11)

Mesmas regras da seção 6 (sequencial, reseta o provider). Cerca de 4 min.

```bash
docker run --rm -v "${PWD}:/w" -w /w -e PYTHONDONTWRITEBYTECODE=1   -e HELPDESK_BASE_URL=http://host.docker.internal:8000   -e PROVIDER_ADMIN_URL=http://host.docker.internal:8090   python:3.12-slim sh -c "pip install -q -r tests/fallback/requirements.txt && python -m pytest tests/fallback -v -p no:cacheprovider"
```

Resultado esperado: `40 passed` (técnico, degradado, indisponibilidade completa, orçamento). Experimentos manuais, com Python no host:

```bash
curl -s -X POST localhost:8090/admin/reset                         # estado conhecido
python docs/fallback/sondas_fallback.py primario-500               # P 500, P 500, equivalente 200
python docs/fallback/sondas_fallback.py larges-500                 # os dois large fora: F1/F2 no mini, F3/F4 503
python docs/fallback/sondas_fallback.py providers-500              # tudo fora: cadeia esgota, 4/3 chamadas
python docs/fallback/sondas_fallback.py primario-timeout F1        # também primario-429, primario-slow, providers-timeout
# derrubar só os dois large, mantendo os mini (falha por modelo):
curl -s -X POST localhost:8090/admin/failures -H "Content-Type: application/json" -d '{"provider": "openai", "model": "gpt-fake-large", "mode": "error_500"}'
curl -s -X POST localhost:8090/admin/failures -H "Content-Type: application/json" -d '{"provider": "anthropic", "model": "claude-fake-large", "mode": "error_500"}'
curl -s "localhost:8090/admin/calls?last=10"                       # leia ANTES de resetar
docker compose logs app | grep fallback                            # destino que atendeu
curl -s -X POST localhost:8090/admin/reset                         # sempre restaurar no fim
```

Em experimentos com provider travado, a F2 deixa uma cadeia órfã no gateway por até ~45 s: espere esse tempo antes do próximo experimento ou filtre `/admin/calls` pelo campo `task`. Comparação large × mini com 1.000 tickets: `python docs/fallback/comparar_modelos.py`.

### 8. Testar a governança (Passo 12)

Gateway real com o banco, provider-fake real e a app real em processo; cada teste cria e apaga a sua própria chave efêmera, então não consome as chaves de demonstração nem a do helpdesk. Cerca de 3 min (um teste espera a janela de 60 s do rate limit).

```bash
docker run --rm -v "${PWD}:/w" -w /w -e PYTHONDONTWRITEBYTECODE=1 \
  -e HELPDESK_BASE_URL=http://host.docker.internal:8000 -e PROVIDER_ADMIN_URL=http://host.docker.internal:8090 \
  -e GATEWAY_URL=http://host.docker.internal:4000 python:3.12-slim \
  sh -c "pip install -q -r tests/governance/requirements.txt && python -m pytest tests/governance -v -p no:cacheprovider"
```

Resultado esperado: `33 passed` (autenticação, orçamento, rate limit, isolamento, contabilização, integração com retry e fallback). Experimentos com evidência em JSON: `python docs/governanca/sondas_governanca.py precos|autenticacao|budget|rate|isolamento|fallback-budget|fallback-rate|custo-cadeia|concorrencia-budget|concorrencia-rate|reserva-sequencial|latencia`. Relatório: [docs/governanca/relatorio-governanca.md](docs/governanca/relatorio-governanca.md).

### 9. Testar a execução síncrona de F1 e F4 (Passo 13)

Borda, app, gateway e provider-fake reais (sem mocks para os requisitos de tempo), mais o contrato de saída e o prazo da app com o código real em processo. Roda em sequência (altera o modo do provider) e leva cerca de 2 min.

```bash
docker run --rm -v "${PWD}:/w" -w /w -e PYTHONDONTWRITEBYTECODE=1 \
  -e HELPDESK_BASE_URL=http://host.docker.internal:8000 -e PROVIDER_ADMIN_URL=http://host.docker.internal:8090 \
  -e GATEWAY_URL=http://host.docker.internal:4000 python:3.12-slim \
  sh -c "pip install -q -r tests/execution/requirements.txt && python -m pytest tests/execution -v -p no:cacheprovider"
```

Resultado esperado: `57 passed` (F1 ≤ 3 s pela borda nas 9 entradas da caracterização, primário travado ≤ 15 s, mini nunca chamado na F4, recusas de governança sem chamar o provider, 25 casos de saída do modelo fora do contrato, prazo de 14 s com o gateway mudo).

Experimentos com evidência em JSON (`docs/execucao/evidencias/`), um por vez:

```bash
# baseline | normal-f1 | normal-f4 | invalidas | error500 | timeout | slow | error429 |
# larges-500 | providers-500 | providers-timeout | concorrencia
docker run --rm -v "${PWD}:/w" -w /w -e HELPDESK_BASE_URL=http://host.docker.internal:8000 \
  -e PROVIDER_ADMIN_URL=http://host.docker.internal:8090 python:3.12-slim \
  sh -c "pip install -q httpx && python docs/execucao/sondas_execucao.py timeout"

# prazo global da app: congelar o gateway, medir e descongelar
docker compose pause gateway && <mesmo docker run> python docs/execucao/sondas_execucao.py deadline; docker compose unpause gateway

# event loop: def x async def bloqueante x async def não bloqueante (FastAPI mínimo, sem o helpdesk)
docker run --rm -v "${PWD}:/w" -w /w python:3.12-slim \
  sh -c "pip install -q fastapi==0.115.6 uvicorn==0.34.0 httpx && python docs/execucao/exemplo_event_loop.py 10"
```

Modos de falha e consulta manual: `curl -s -X POST localhost:8090/admin/failures -H "Content-Type: application/json" -d '{"provider": "openai", "model": "gpt-fake-large", "mode": "timeout"}'`, depois `curl -s "localhost:8090/admin/calls?last=10"` e, sempre no fim, `curl -s -X POST localhost:8090/admin/reset`. Relatório: [docs/execucao/relatorio-execucao.md](docs/execucao/relatorio-execucao.md).

## Roteiro de governança

O gateway aplica as políticas por **chave virtual**, antes de encaminhar ao provider ([ADR 0010](docs/adr/0010-gateway-governance.md)). As chaves são criadas pelo `gateway-bootstrap` em todo `docker compose up`, com os valores do `.env` ([ADR 0008](docs/adr/0008-key-bootstrap-service.md)):

| Identidade | Variável no `.env` | Capacidades | Orçamento | Rate limit | Quem usa |
|---|---|---|---|---|---|
| `helpdesk-app` | `HELPDESK_GATEWAY_KEY` | as 4 | US$ 20 / 30 dias (aviso em 15) | 600 req/min | só o serviço `app` |
| `governance-budget-demo` | `GOVERNANCE_BUDGET_KEY` | `ticket-classification` | US$ 0,0004, acumulado | — | Experimento A |
| `governance-rate-demo` | `GOVERNANCE_RATE_KEY` | `ticket-classification` | US$ 1 (nunca é a causa) | 3 req/min | Experimento B |
| master key | `GATEWAY_MASTER_KEY` | administração | — | — | gateway e bootstrap; nunca a app |

Preços configurados (os do `provider-fake/README.md`): `gpt-fake-large` US$ 2,50/10,00, `claude-fake-large` 3,00/15,00, `gpt-fake-mini` 0,15/0,60, `claude-fake-mini` 0,80/4,00 por 1M tokens de entrada/saída. As funcionalidades continuam sendo validadas pela borda (porta 8000, chave do helpdesk); os experimentos abaixo chamam o gateway direto (porta 4000) porque cada um usa uma chave diferente.

Comandos em bash (Linux, macOS ou Git Bash), na raiz do repositório. Rode cada experimento sem outro tráfego no ambiente: a prova compara `/admin/calls` antes e depois, e **não** use `/admin/reset` entre as duas contagens.

```bash
M=sk-gateway-local-0001          # master key (GATEWAY_MASTER_KEY), só para consultar a chave
B='{"model":"ticket-classification","messages":[{"role":"user","content":"TASK: classify\nMeu pedido #481516 nao chegou"}]}'
chamadas() { curl -s "localhost:8090/admin/calls?last=5000" | grep -o '"id"' | wc -l; }
```

### Experimento A: recusa por orçamento

Cada chamada custa US$ 0,0001375 (11 tokens de entrada × 2,50 + 11 de saída × 10,00, por milhão). O gateway admite enquanto o gasto for **menor** que US$ 0,0004: passam 3 (gasto 0,0004125) e a 4ª é recusada.

```bash
K=sk-governance-budget-local-0001                                   # GOVERNANCE_BUDGET_KEY
# 1-2. estado inicial e orçamento: "max_budget":0.0004, "spend":0.0 (se não, passo 10 antes)
curl -s "localhost:4000/key/info?key=$K" -H "Authorization: Bearer $M" | grep -oE '"(key_alias|max_budget|spend)":[^,]*'
# 3. três requisições autorizadas (custo de cada uma no header)
for i in 1 2 3; do curl -s -o /dev/null -D - localhost:4000/v1/chat/completions -H "Authorization: Bearer $K" \
  -H "Content-Type: application/json" -d "$B" | grep -iE "^HTTP|x-litellm-response-cost:"; sleep 1; done
# 4. consumo: o gasto vai ao banco em lote; espere ~15 s ("spend":0.0004125)
sleep 15; curl -s "localhost:4000/key/info?key=$K" -H "Authorization: Bearer $M" | grep -oE '"spend":[^,]*'
# 5. contagem de chamadas ao provider ANTES
chamadas
# 6-7. nova requisição: recusada pelo gateway
curl -s -w "\nHTTP %{http_code}\n" localhost:4000/v1/chat/completions -H "Authorization: Bearer $K" -H "Content-Type: application/json" -d "$B"
# 8-9. contagem DEPOIS (mesmo número = nenhuma chamada nova ao provider)
chamadas
docker compose logs gateway --since 2m | grep "Budget has been exceeded"   # recusa na autenticação
# 10. restaurar para repetir (só chaves de demonstração; espera o gasto estabilizar, ~35 s)
docker compose run --rm gateway-bootstrap --reset-spend governance-budget-demo
```

Observado ([evidência](docs/governanca/evidencias/30-ambiente-limpo.txt)): `HTTP 429` com `"type":"budget_exceeded"` e `Budget has been exceeded! Key=governance-budget-demo (sk-...0001) Current cost: 0.0004125..., Max budget: 0.0004`, e a mesma contagem antes e depois. O `429` sozinho não prova nada: a prova é a contagem igual.

### Experimento B: recusa por limite de requisições

Janela **fixa** de 60 s que começa na primeira requisição admitida (limitador do LiteLLM `v1.102.1`, contador em memória). Cada requisição recebida conta 1, mesmo que o gateway faça retry ou fallback por dentro.

```bash
K=sk-governance-rate-local-0001                                     # GOVERNANCE_RATE_KEY
# 1-2. estado e limite ("rpm_limit":3); comece com a chave parada há 60 s (janela vazia)
curl -s "localhost:4000/key/info?key=$K" -H "Authorization: Bearer $M" | grep -oE '"(key_alias|rpm_limit)":[^,]*'
# 3. três requisições (saldo no header: 2, 1, 0)
for i in 1 2 3; do curl -s -o /dev/null -D - localhost:4000/v1/chat/completions -H "Authorization: Bearer $K" \
  -H "Content-Type: application/json" -d "$B" | grep -iE "^HTTP|remaining-requests"; done
# 4. contagem ANTES
chamadas
# 5-6. requisição adicional: recusada, com Retry-After
curl -s -D - localhost:4000/v1/chat/completions -H "Authorization: Bearer $K" -H "Content-Type: application/json" -d "$B" | grep -ioE "^HTTP.*|retry-after.*|\"type\":\"[a-z_]*\""
# 7-8. contagem DEPOIS (mesmo número)
chamadas
# 9. recuperação: 60 s depois da PRIMEIRA requisição a chave volta sozinha
sleep 60; curl -s -o /dev/null -w "HTTP %{http_code}\n" localhost:4000/v1/chat/completions -H "Authorization: Bearer $K" -H "Content-Type: application/json" -d "$B"
```

Observado: `HTTP 429`, `retry-after: 60`, `"type":"throttling_error"` (`Rate limit exceeded for api_key: <hash>. Limit type: requests. Current limit: 3, Remaining: 0`), contagem igual e `200` depois da janela. O "Limit resets at" do corpo e o `Retry-After` são pessimistas: contam 60 s a partir da recusa, mas a janela termina 60 s depois da primeira requisição.

### Outras verificações

```bash
curl -s -o /dev/null -w "%{http_code}\n" localhost:4000/v1/chat/completions -H "Authorization: Bearer sk-invalida" -H "Content-Type: application/json" -d "$B"   # 401, sem chamada ao provider
docker compose exec app env | grep -E "KEY|DATABASE"        # só GATEWAY_API_KEY (a chave virtual do helpdesk)
docker compose exec gateway-db psql -U litellm -d litellm -c 'select key_alias, spend, max_budget, rpm_limit from "LiteLLM_VerificationToken";'
```

Recusa por orçamento ou rate limit não dispara retry nem fallback (nenhum modelo é chamado, nem com o primário em falha). Na app elas viram `503` com `code` `model_budget_exceeded` ou `model_throttled` (com `Retry-After`), sem expor chave nem limite.

## Tabela de capacidades

A aplicação pede **capacidades lógicas**; o gateway decide qual modelo físico atende ([ADR 0004](docs/adr/0004-logical-capabilities.md)) e em que ordem recuperar ([ADR 0006](docs/adr/0006-fallback-policy.md)). Os destinos de fallback são grupos internos do gateway (`<capacidade>-equivalent`, `<capacidade>-degraded`) que a app nunca pede.

| Capacidade | Feature | Primário | Fallback técnico | Modelo inferior | Tentativas máximas por destino (primário / técnico / inferior) | Timeout por tentativa | Deadline da app |
|---|---|---|---|---|---|---|---|
| `ticket-classification` | F1 classificação | `openai/gpt-fake-large` | `anthropic/claude-fake-large` | `openai/gpt-fake-mini` | 2 / 1 / 1 (total 4) | 3 / 3 / 2 s | 14 s |
| `reply-suggestion` | F2 sugestão | `anthropic/claude-fake-large` | `openai/gpt-fake-large` | `anthropic/claude-fake-mini` | 2 / 1 / 1 (total 4) | 20 / 20 / 5 s | 25 s |
| `topics-report` | F3 relatório | `anthropic/claude-fake-large` | `openai/gpt-fake-large` | — (rejeitado) | 2 / 1 (total 3), por lote | 12 / 12 s | 25 s por lote |
| `order-extraction` | F4 extração | `openai/gpt-fake-large` | `anthropic/claude-fake-large` | — (rejeitado) | 2 / 1 (total 3) | 3 / 3 s | 14 s |

No primário, as 2 tentativas valem para `500`/`503`; `429`, timeout e `4xx` têm 1 tentativa e migram direto. `max_tokens` 2000 em todos os destinos Anthropic e nos de F2/F3.

## Tabela de fallback

Comportamento quando os **dois modelos `large`** estão indisponíveis (falha por modelo; os `mini` continuam no ar). Status medidos em `docs/fallback/evidencias/08-larges-500.json`.

| Feature | Aceita modelo inferior? | Comportamento esperado | Status HTTP atual | Justificativa |
|---|---|---|---|---|
| F1 | sim (`gpt-fake-mini`) | classificação pelo mini, mesmo contrato | `200` em 2,3 s | cliente esperando na abertura; mini igual ao large em 1.000/1.000 tickets |
| F2 | sim (`claude-fake-mini`) | sugestão mais curta (~44% do texto) | `200` em 4,8 s | o atendente revisa e edita antes de enviar |
| F3 | não | falha explícita, nenhum relatório parcial | `503 model_unavailable` em 3,0 s | ninguém espera e dá para reprocessar; um agregado errado não avisa ninguém |
| F4 | não | falha explícita, sem campos nulos artificiais | `503 model_unavailable` em 2,4 s | automação sem revisão; o mini errou o pedido em 150/1.000 e omitiu o produto em 192/1.000 |

Com os dois providers inteiros fora, as quatro respondem `503` em cerca de 2 s (4 chamadas na F1/F2, 3 na F3/F4). Esta tabela muda quando a F2 ganhar streaming (Passo 14) e a F3 virar assíncrona (Passo 15).

## Política de resiliência

| Item | Política ([ADR 0005](docs/adr/0005-resilience-policy.md), revisada pelo [ADR 0006](docs/adr/0006-fallback-policy.md)) |
|---|---|
| Onde fica | gateway (`gateway/config.yaml`): timeout por tentativa, retry, backoff e cadeia de fallback. App: deadline global da operação (`config.py`), tradução do erro e log do destino que atendeu. SDK da app com `max_retries=0` |
| Ordem | primário `large` → `large` equivalente de outro provider → `mini` só na F1/F2 → erro explícito. Finita (`max_fallbacks: 2`), sem ciclo |
| Repete no mesmo destino | só `500`/`503` no primário, 1 vez |
| Migra sem repetir | `429` do provider, timeout, falha de conexão; nos destinos de fallback, qualquer erro (1 tentativa) |
| Não repete | `400`, `401`, `403`, `404`, contexto excedido, política de conteúdo (o LiteLLM ainda percorre a cadeia em `400` na F1/F4, cada destino uma vez) |
| Backoff | LiteLLM: 0,5 s × 2ⁿ + jitter de 0 a 0,75 s, mais uma pausa depois da última tentativa; só no primário |
| Deadline | uma chamada HTTP da app ao gateway: trocar de destino não reinicia o prazo (14 s F1/F4, 25 s F2 e F3 por lote) |
| Esgotou | `503` (`model_timeout`, `model_rate_limited`, `model_unavailable`) ou `502` (`model_rejected`), corpo `{"detail", "code"}` |

Resultados do Passo 11: `500` no primário vira `200` pelo equivalente (F1 2,8 s, F4 3,6 s, F2 18,1 s, F3 12,4 s); F1 com o primário travado responde em 4,1 s; nenhum `504` da borda. Limitações: a F2 travada ainda responde `503` aos 25 s e deixa a cadeia correndo no gateway (cadeia órfã); a F3 do mês continua passando da borda. Detalhes em [docs/fallback/relatorio-fallback.md](docs/fallback/relatorio-fallback.md) e, para o Passo 10, [docs/resiliencia/relatorio-resiliencia.md](docs/resiliencia/relatorio-resiliencia.md).

## Fluxos

Os quatro fluxos são síncronos (rotas `def`, resposta só no fim, sem streaming) e seguem o mesmo caminho: `edge` → `main` → feature → `ports.LanguageModel` → `adapters.gateway` → `gateway` → provider. O contrato HTTP é o mesmo da v1 (OpenAPI idêntico, [evidência](docs/v2/evidencias/22-openapi.txt)).

| Fluxo | Rota | Capacidade | Chamadas ao modelo | Tempo típico |
|---|---|---|---|---|
| F1 classificação | `POST /tickets/classification` | `ticket-classification` | 1; JSON validado (502 se não for objeto JSON ou se a categoria ou a prioridade não existir) | ~1,1 s |
| F2 sugestão | `POST /tickets/reply-suggestion` | `reply-suggestion` | 1; texto devolvido como veio | ~16 s |
| F3 relatório | `POST /reports/topics` | `topics-report` | 1 por lote de 150 tickets do período, em série; temas somados e ordenados | ~10 s por dia; o mês passa dos 30 s da borda (Dor 1) |
| F4 extração | `POST /tickets/extraction` | `order-extraction` | 1; JSON validado (502 se faltar um dos dois campos, se o número não for `#` + 6 dígitos ou se o produto não for texto) | ~1,1–1,2 s |

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

### Fluxos síncronos: F1 e F4 (Passo 13, [ADR 0011](docs/adr/0011-execution-modes.md))

F1 e F4 são **Request-Response síncronos por decisão**: alguém (o cliente na tela, ou a automação de troca) espera o resultado agora, ele cabe com folga no orçamento de latência e não serve pela metade. Internamente as rotas são `def` (rodam no thread pool de 40 threads do FastAPI) com o cliente HTTP síncrono; isso não muda o contrato. F2 (streaming) e F3 (assíncrona) ainda são hipóteses dos Passos 14 e 15.

**F1: classificação**

```bash
curl -s -X POST http://localhost:8000/tickets/classification \
  -H "Content-Type: application/json" \
  -d '{"ticket_id": "TK-00042", "text": "Meu pedido #481516 não chegou e já passou do prazo, urgente"}' \
  -w '\nHTTP: %{http_code}\nTTFB: %{time_starttransfer}s\nTempo total: %{time_total}s\n'
# {"ticket_id":"TK-00042","category":"delivery","priority":"high"}
# HTTP: 200 / TTFB: 1.09s / Tempo total: 1.09s
```

**F4: extração**

```bash
curl -s -X POST http://localhost:8000/tickets/extraction \
  -H "Content-Type: application/json" \
  -d '{"ticket_id": "TK-00042", "text": "Quero devolver o teclado do pedido #481516."}' \
  -w '\nHTTP: %{http_code}\nTTFB: %{time_starttransfer}s\nTempo total: %{time_total}s\n'
# {"ticket_id":"TK-00042","order_number":"#481516","product":null}
# ("teclado" sozinho não é um produto do simulador, que conhece "teclado mecânico": null legítimo)
```

| Feature | Entrada | Saída | Validações | Requisito de latência | Medido pela borda |
|---|---|---|---|---|---|
| F1 | `{"ticket_id": str≥1, "text": str≥1}` | `{"ticket_id", "category", "priority"}` | objeto JSON; `category` ∈ delivery, payment, exchange_return, product_defect, other; `priority` ∈ low, medium, high; `ticket_id` sempre o da requisição | **3 s** normal; **15 s** travado | 1,06–1,16 s; 4,10 s com primário travado |
| F4 | idem | `{"ticket_id", "order_number", "product"}` | objeto JSON; as duas chaves presentes; número `#[0-9]{6}` ou `null`; produto texto ou `null` | **15 s** travado (sem meta normal no enunciado) | 1,06–1,24 s; 4,25 s com primário travado |

| Situação | F1 | F4 |
|---|---|---|
| Entrada inválida | `422`, nenhuma chamada ao modelo | `422`, nenhuma chamada |
| Primário `500`, `429`, lento ou travado | `200` pelo `claude-fake-large` (1,1–4,1 s) | `200` pelo `claude-fake-large` (1,25–4,25 s) |
| Dois `large` fora | `200` pelo `gpt-fake-mini` (2,5 s) | `503 model_unavailable`, mini nunca chamado |
| Tudo fora ou travado | `503` em 2,2–8,1 s | `503` em 2,2–6,1 s |
| Gateway travado | `503 model_timeout` aos 14 s (prazo da app) | idem |
| Orçamento ou RPM esgotado | `503 model_budget_exceeded` / `model_throttled`, sem chamar o provider | idem |
| Saída do modelo fora do contrato | `502 {"detail"}` | `502 {"detail"}`; nunca um `null` fictício |

Limites de execução: timeout por tentativa 3 s (mini 2 s), no máximo 4 chamadas (F1) ou 3 (F4) por requisição, prazo global de 14 s na app, borda de 30 s. Nenhum cenário produziu `504` da borda. Limitações remanescentes: sem validação semântica (um `#123456` bem formado pode ser o pedido errado), trabalho órfão quando a app desiste, margem de 1 s entre o prazo e os 15 s, e no máximo 40 esperas simultâneas por processo ([relatório](docs/execucao/relatorio-execucao.md), seção 30).

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
| [0005](docs/adr/0005-resilience-policy.md) | timeout, retry limitado e backoff no gateway; limite externo e erros na app | solução | aceita; tentativas e prazo da F3 revisados pelo 0006 |
| [0006](docs/adr/0006-fallback-policy.md) | fallback técnico para o large de outro provider em todas; mini só na F1 e F2; F3 e F4 falham explicitamente | solução | aceita; revisado no Passo 12 |
| [0007](docs/adr/0007-gateway-governance-database.md) | Postgres próprio do gateway para chaves virtuais e gasto | solução | aceita |
| [0008](docs/adr/0008-key-bootstrap-service.md) | serviço de bootstrap idempotente cria as chaves a cada `up` | solução | aceita |
| [0009](docs/adr/0009-corporate-ai-governance.md) | política corporativa (simulada): consumo só pelo gateway, identidade, orçamento e limite por consumidor | corporativa | aceita |
| [0010](docs/adr/0010-gateway-governance.md) | preço por modelo, chave virtual, orçamento e RPM no gateway; recusa sem retry nem fallback | solução | aceita |
| [0011](docs/adr/0011-execution-modes.md) | modo de execução por feature (ADR único): F1 e F4 síncronas; F2 streaming e F3 assíncrona como hipóteses | solução | aceita para F1 e F4; F2 e F3 preliminares (Passos 14 e 15) |

Os ADRs 0003, 0005 e 0006 têm seção de revisão do Passo 12. Execução síncrona: [docs/execucao/relatorio-execucao.md](docs/execucao/relatorio-execucao.md) e [checkpoint](docs/execucao/checkpoint-passo-13.md). Governança: [docs/governanca/relatorio-governanca.md](docs/governanca/relatorio-governanca.md) e [checkpoint](docs/governanca/checkpoint-passo-12.md). Fallback: [docs/fallback/relatorio-fallback.md](docs/fallback/relatorio-fallback.md) e [checkpoint](docs/fallback/checkpoint-passo-11.md). Plano da refatoração: [docs/refactoring-plan.md](docs/refactoring-plan.md) (versão 1.2). Piloto da F1: [docs/piloto/relatorio-piloto.md](docs/piloto/relatorio-piloto.md). Refatoração completa: [docs/v2/relatorio-v2.md](docs/v2/relatorio-v2.md).

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
