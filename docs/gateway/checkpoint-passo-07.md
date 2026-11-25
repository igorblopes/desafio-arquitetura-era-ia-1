# Checkpoint de continuidade: fim do Passo 07

## Estado
- **Aplicação:** inalterada. Ainda chama o provider-fake diretamente; `git diff v1-coupled` vazio em `app/`, `tests/characterization/`, `provider-fake/`, `edge/` e `data/`.
- **Commits do Igor:** `13fc247` (Passo 05) e `b3fdeb2` (Passo 06). O Passo 07 está na pasta local, **sem commit**.
- **Arquivos novos:** `gateway/config.yaml`, `docs/gateway/` (relatório, experimentos, evidências, glossário e este checkpoint).
- **Arquivos alterados:** `compose.yaml` (serviço `gateway`), `.env.example` (`GATEWAY_MASTER_KEY`), README, ADRs 0003 e 0004 e `docs/refactoring-plan.md` (revisão 1.0.1).
- **`.env` local do Igor:** ganhou a linha `GATEWAY_MASTER_KEY`.

## Gateway
- **Ferramenta:** LiteLLM Proxy `ghcr.io/berriai/litellm:v1.102.1`, digest `sha256:87f34979...`. É a versão testada pelo `provider-fake/README.md`.
- **Endereços:**
  - interno: `http://gateway:4000`;
  - host: `http://localhost:4000`;
  - rota de inferência: `POST /v1/chat/completions` (formato OpenAI).
- **Saúde:** `/health/liveliness` e `/health/readiness` (sem chave). A rota `/health` exige chave.
- **Autenticação:** `Authorization: Bearer ${GATEWAY_MASTER_KEY}`. É provisória: a chave virtual da app fica para o Passo 12, com PostgreSQL.
- **Configuração:** `gateway/config.yaml`, montado somente leitura. As variáveis são declaradas no compose, sem `env_file`.
- **Subir:** `cp .env.example .env` + `docker compose up -d --build --wait` (19 s com imagens em cache).

## Capacidades (todas `large`, mesmo provider da v1)
| Capacidade | Provider e modelo |
|---|---|
| `ticket-classification` | openai/gpt-fake-large |
| `order-extraction` | openai/gpt-fake-large |
| `reply-suggestion` | anthropic/claude-fake-large, `max_tokens` 2000 |
| `topics-report` | anthropic/claude-fake-large, `max_tokens` 2000 |

## Resultados dos experimentos
- **Roteamento:** confirmado pelo `/admin/calls` nas 4 capacidades. As saídas são iguais à caracterização: o golden da F2 bate byte a byte e o relatório do dia 2026-08-01 bate após a agregação.
- **Normalização:** os dois destinos respondem no formato OpenAI, com o nome lógico em `model`; `end_turn` vira `stop`. Os erros vêm no envelope OpenAI, com mensagem reescrita pelo LiteLLM e `code` igual ao status.
- **Autenticação:**
  - chave válida: 200;
  - chave inválida: **400** `No connected db.`;
  - sem chave: 401.
  - As requisições recusadas não chegaram ao provider.
- **Troca de modelo:** `ticket-classification` passou de gpt para claude em 8 s, reiniciando só o gateway. A resposta foi idêntica, a app manteve o mesmo container e horário de início, e `app/` ficou sem diff. Feita com um cliente de teste.
- **Streaming:** SSE progressivo pelo gateway. Primeiro conteúdo em 0,823 s (nativo: 0,805 s); termina com `[DONE]`; o fake registrou `stream: true`. Os cabeçalhos só chegam com o primeiro trecho.
- **Latência:** +6 ms nas medianas (F1: 1,080 → 1,086 s; F2: 15,955 → 15,961 s). A primeira chamada após um restart leva de 1,25 a 1,70 s.
- **Retries:** o padrão da imagem é **2 retentativas** em 5xx (3 chamadas, 500 em 4,69 s). O 400 não é retentado.
- **Integridade:** 32 testes de caracterização verdes com o gateway no ar.

## Limitações e dependências futuras
- Não está provado que `max_tokens` é aplicado.
- `midstream_error` não foi testado.
- `/admin/calls` não identifica a origem da chamada.
- Budget, rate limit e chaves virtuais dependem de PostgreSQL e de preços declarados em `model_info`; sem os preços, o custo fica zero.
- Fallback e timeout não foram configurados.
- A app ainda tem as chaves dos providers e vê `GATEWAY_MASTER_KEY` via `env_file`. Esse estado é transitório e termina no Passo 09.

## Para o adapter (Passo 08)
- SDK `openai` com `base_url=http://gateway:4000/v1`, `api_key=GATEWAY_API_KEY` e **`max_retries=0`**. O gateway já faz 2 retentativas; sem isso, uma falha viraria 9 chamadas.
- Chamada: `model=CAPABILITY`, uma mensagem de usuário com o prompt. A resposta está em `choices[0].message.content`.
- Não interpretar mensagens de erro: só o status.
- Compose: `app` recebe `GATEWAY_URL` e `GATEWAY_API_KEY` (este com o valor de `GATEWAY_MASTER_KEY`) e passa a ter `depends_on: gateway: service_healthy`.

## ADRs
- **0003 (gateway):** aceita para a infraestrutura.
- **0004 (capacidades):** aceita no gateway.
- **0002 (contrato):** continua proposta.
- **0001:** inalterado.

## Conhecimentos adquiridos
- O gateway muda **para onde** a chamada vai, não **de quem** o código depende.
- Normalização de interface não é equivalência funcional.
- Processo iniciado não é serviço pronto.
- Padrões invisíveis (como retries) aparecem só em experimento.
- `latest` não é reprodutível.
- Sem banco, o LiteLLM só conhece a master key.

## Pendências
- **Igor:** revisar e commitar o Passo 07 e fazer `git push origin v1-coupled`, se ainda não fez.
- **Passo 08:** executar o piloto F1 com o handoff atualizado (plano, §19.1, revisão 1.0.1).
