# Incremento 5 (Passo 09): tirar as credenciais dos providers do serviço app

Handoff do arquiteto para o agente de IA. É independente: tudo o que você precisa está aqui e nos arquivos citados.

## Contexto (igual para todos os incrementos do Passo 09)

- **Desafio:** Full Cycle "Arquitetura na Era da IA". O helpdesk (`app/helpdesk/`, FastAPI, síncrono) usa IA em 4 features. A meta deste passo é a `v2-decoupled`: todas as features chamam o modelo **só pelo AI Gateway** (serviço `gateway`, LiteLLM Proxy), pedindo **capacidades lógicas**, sem SDK de provider, sem modelo físico e sem chave de provider na app, e com o **comportamento externo idêntico** ao da tag `v1-coupled`.
- **Arquitetura atual (commit `4a3447a`, piloto do Passo 08 aprovado):**
  - `app/helpdesk/ports.py`: `LanguageModel(Protocol)` com uma operação, `complete(capability: str, prompt: str) -> str`.
  - `app/helpdesk/adapters/gateway.py`: `GatewayLanguageModel(LanguageModel)`, o **único** componente que fala com o gateway (SDK `openai` apontado para `{GATEWAY_URL}/v1`, chave `GATEWAY_API_KEY`, `max_retries=0`, `model=capability`).
  - `app/helpdesk/main.py`: Composition Root. Cria **uma** instância (`language_model = GatewayLanguageModel()`) e a passa por parâmetro à feature.
  - F1 (`classification.py`) já migrada: `CAPABILITY = "ticket-classification"`, `classify(ticket, model: LanguageModel)`, `model.complete(CAPABILITY, f"TASK: classify\n{ticket.text}")`, `json.loads`.
  - F2, F3 e F4 ainda usam `llm.py` (`call_openai`/`call_anthropic`) e `config.*_MODEL`.
- **Arquitetura pretendida:** `feature -> ports <- adapters.gateway`; só `main` importa o adapter; `llm.py` some; `config.py` fica só com `GATEWAY_URL`, `GATEWAY_API_KEY`, `TICKETS_FILE`, `TICKETS_PER_CALL`; o serviço `app` não recebe chave de provider.
- **Estratégia validada no piloto:** mesmo contrato, mesmo adapter, uma constante `CAPABILITY` por feature, o prompt `TASK: <tarefa>\n<conteúdo>` montado pela feature exatamente como `llm.py` montava, `llm.parse_json` trocado por `json.loads` (é o que ele fazia), injeção por parâmetro a partir de `main`.
- **Revisões do plano (1.1) que valem aqui:** a busca de imports do adapter procura **linhas de import** (imports relativos não contêm a palavra `adapters` no arquivo do adapter); cada feature migrada passa por uma verificação do arquiteto contra gateway simulado (`docs/v2/verificacao_v2.py`) e por uma sonda de falha pela borda (`docs/v2/sondas_v2.py`); o retry é só do gateway (`max_retries=0`); a latência sob falha persistente subiu (risco conhecido, não é para corrigir agora).
- **Capacidades no gateway** (`gateway/config.yaml`, não alterar): `ticket-classification` e `order-extraction` → `openai/gpt-fake-large`; `reply-suggestion` e `topics-report` → `anthropic/claude-fake-large` com `max_tokens: 2000` (o mesmo limite que a v1 enviava).

## Artefatos disponíveis

`docs/refactoring-plan.md` (v1.1: seções 10, 13, 14.2, 16, 17.6, 18, 23), `docs/adr/0002` a `0004`, o código do piloto (`ports.py`, `adapters/gateway.py`, `classification.py`, `main.py`), `tests/characterization/` (32 testes pela borda), `metrics/measure.py` e `metrics/results/v1-coupled.csv`, `docs/piloto/metricas/pilot-after.csv`, `gateway/config.yaml`, `docs/v2/verificacao_v2.py`, `docs/v2/sondas_v2.py`.

## Restrições (valem para todos os incrementos)

- Não fazer commit, push, branch, stash, tag, nem mover tags. Não apagar volumes (`down -v`).
- Não alterar: `tests/`, `metrics/`, `provider-fake/`, `edge/`, `data/`, `gateway/`, `docs/` (exceto onde o incremento mandar), nem a tag `v1-coupled`.
- Não alterar rotas, contratos de entrada e saída, status HTTP, mensagens de erro nem o modo síncrono (rotas `def`, sem streaming, sem async, sem background).
- Não usar modelos `mini`. Não implementar fallback, timeout, retry, backoff, budget, rate limit, cache.
- Não criar contrato novo, método novo no contrato, classe nova, wrapper, factory, contêiner de DI nem import sem uso. Não mudar `ports.py` nem `adapters/gateway.py` (se achar que precisa, **pare e explique** na proposta).
- Não mexer em nenhum arquivo fora da lista autorizada do incremento.
- Não alterar testes nem a ferramenta de métricas para aprovar a própria implementação.

## Componente-alvo

- **Configuração de execução:** `compose.yaml` e `.env.example`.
- **Hoje:** o serviço `app` tem `env_file: .env`, que injeta **todas** as variáveis do `.env` (inclusive `FAKE_OPENAI_KEY`, `FAKE_ANTHROPIC_KEY` e `GATEWAY_MASTER_KEY`) no container, mesmo depois de a app não as ler mais. O `provider-fake` também usa `env_file: .env` e recebe a `GATEWAY_MASTER_KEY`, de que não precisa (ele só lê `FAKE_OPENAI_KEY` e `FAKE_ANTHROPIC_KEY`, ver `provider-fake/app/main.py`). O `app` ainda declara `depends_on: provider-fake`, mas não fala mais com ele.

## Tarefa

- Serviço `app`: remover `env_file: .env`; manter `environment:` só com `GATEWAY_URL: http://gateway:4000` e `GATEWAY_API_KEY: ${GATEWAY_MASTER_KEY:?...}` (atualize o comentário: chave de consumo do gateway; virtual key por consumidor no Passo 12); remover `depends_on: provider-fake` (manter `gateway: service_healthy`). Manter volume `./data:/data:ro`, healthcheck e build.
- Serviço `provider-fake`: trocar `env_file: .env` por `environment:` com só `FAKE_OPENAI_KEY` e `FAKE_ANTHROPIC_KEY` interpolados do `.env` (mesmo padrão do serviço `gateway`). Não mexer no diretório `provider-fake/`.
- Comentário do serviço `gateway`: tirar a frase do estado transitório (todas as features passam por ele).
- `.env.example`: atualizar os comentários (as chaves `FAKE_*` vão só ao gateway e ao provider-fake; a app recebe só a chave do gateway). Não mudar valores nem nomes.
- Não usar `docker compose down -v`. Para aplicar: `docker compose up -d --build --wait` (recria o que mudou).

**Arquivos autorizados:** `compose.yaml`, `.env.example`.

## Critérios de aceite

- `docker compose config` sem `env_file` no `app` nem no `provider-fake`, e o `app` com só `GATEWAY_URL` e `GATEWAY_API_KEY` no `environment` (cole o bloco do `app`, mascarando o valor da chave).
- `docker compose exec app env | grep -E "FAKE_|sk-fake|sk-ant|GATEWAY_MASTER"` vazio.
- 32 testes passam; `verificacao_v2.py F1 F4 F2 F3` OK; sonda `features` com as 4 features atendidas pelos modelos `large` esperados.

## Como trabalhar (duas fases)

**Fase 1, proposta (não altere nenhum arquivo):** leia o código e responda: (a) como a tarefa é construída hoje, como o modelo e o provider são escolhidos, como a resposta é interpretada e validada; (b) o diff exato que pretende aplicar; (c) dependências que saem e que entram, e as métricas que espera para os componentes afetados; (d) riscos. **Pare e aguarde a autorização do arquiteto.**

**Fase 2, implementação (só depois de autorizado):** aplique exatamente o proposto (ou o ajuste pedido) e rode, na raiz do repositório (Git Bash), colando a saída **integral** de cada comando:

```bash
git status --short --untracked-files=all
git diff
docker compose up -d --build --wait app
docker run --rm -v "${PWD}:/w" -w /w -e PYTHONDONTWRITEBYTECODE=1 -e HELPDESK_BASE_URL=http://host.docker.internal:8000 -e PROVIDER_ADMIN_URL=http://host.docker.internal:8090 python:3.12-slim sh -c "pip install -q -r tests/requirements.txt && python -m pytest tests/characterization -v -p no:cacheprovider"
docker run --rm -v "${PWD}:/w" -v "${PWD}/data:/data:ro" -w /w -e PYTHONDONTWRITEBYTECODE=1 python:3.12-slim sh -c "pip install -q -r app/requirements.txt httpx && python docs/v2/verificacao_v2.py F1 F4 F2 F3"
docker run --rm -v "${PWD}:/w" -w /w -e PYTHONDONTWRITEBYTECODE=1 -e HELPDESK_BASE_URL=http://host.docker.internal:8000 -e PROVIDER_ADMIN_URL=http://host.docker.internal:8090 python:3.12-slim python docs/v2/sondas_v2.py features
docker compose logs --since 5m gateway | grep -c "POST /v1/chat/completions"
docker run --rm -v "${PWD}:/w" -w /w python:3.12-slim sh -c "pip install -q -r metrics/requirements.txt && python metrics/measure.py --source app/helpdesk --name v2-incremento-5-credenciais --output-dir /tmp/m --no-plot && cat /tmp/m/v2-incremento-5-credenciais.csv"
grep -rnE "^\s*(from|import) .*(adapters|gateway)" app/helpdesk --include=*.py
docker compose config
docker compose exec app env | grep -E "FAKE_|sk-fake|sk-ant|GATEWAY_MASTER"   # esperado: vazio
docker compose exec app env | grep -E "^GATEWAY_" | sed -E "s/(KEY=).*/\1***/"
```

## Formato da entrega

1. Resumo da implementação. 2. Arquivos modificados (e o conteúdo integral de cada um). 3. Dependências removidas. 4. Dependências introduzidas. 5. Justificativas técnicas. 6. Testes executados. 7. Resultados observados (saídas integrais acima). 8. Métricas coletadas (CSV). 9. Evidências de comunicação pelo gateway (sonda `features` e contagem no log). 10. Riscos e limitações. **Depois da entrega, pare e aguarde o arquiteto.**
