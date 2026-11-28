# 0003. Todas as chamadas de IA passam por um AI Gateway self-hosted (LiteLLM Proxy)

- Status: aceita para a infraestrutura (Passo 07) e para a integração com as quatro features (Passos 08 e 09)
- Data: 2026-11-25 (proposta no Passo 06, revisada no Passo 07)
- Nível: solução

## Contexto

Problemas da integração direta, comprovados no Passo 02:

| Problema | Evidência |
|---|---|
| Acoplamento aos providers | F1/F4 chamam `call_openai` e F2/F3 chamam `call_anthropic`; com a openai fora, F1 e F4 caem; com a anthropic fora, F2 e F3 caem |
| Acoplamento aos modelos físicos | `config.py:10-13`; trocar exige editar e fazer rebuild (6–7 s, 502 na borda) |
| Credenciais dispersas | `config.py:3-4`; o serviço `app` recebe `env_file: .env` com `FAKE_OPENAI_KEY`/`FAKE_ANTHROPIC_KEY` |
| Nenhum ponto para políticas | retries e timeouts vêm dos padrões de cada SDK (3 tentativas, 600 s) |

O desafio exige um gateway self-hosted como serviço `gateway` no Compose, sem providers reais nem serviços pagos, e um ADR para cada serviço novo.

## Opções consideradas

| Opção | Tira credenciais e modelos da app? | Local e gratuito? | Observação |
|---|---|---|---|
| SDKs diretos (v1) | não | sim | é o problema |
| Biblioteca de abstração na app (ex.: LiteLLM SDK) | não | sim | padroniza a interface, mas chaves e modelos continuam no processo da app |
| **LiteLLM Proxy** (self-hosted) | sim | sim | sugerido pelo enunciado; o `provider-fake/README.md` documenta a compatibilidade com `ghcr.io/berriai/litellm:v1.102.1` |
| Portkey AI Gateway (open source) | sim | sim | considerado; recursos só documentados, não verificados aqui |
| AI Gateway SaaS | sim | não | proibido |

## Decisão

LiteLLM Proxy `ghcr.io/berriai/litellm:v1.102.1` (digest observado `sha256:87f34979b9f8cb274fac90ca8a4fdda07d8480de22755562a26adeb95ce20d02`), como serviço `gateway` no `compose.yaml`.

- **Posição:** entre o futuro `adapters/gateway.py` e o `provider-fake`. A porta 4000 é publicada só para testes no host; a app usará `http://gateway:4000`. O `edge` continua sendo a única entrada do helpdesk.
- **Configuração:** `gateway/config.yaml`, versionado e montado somente leitura. Contém 4 capacidades lógicas (ADR 0004); `api_base` interno de cada provider; chaves referenciadas por `os.environ/...`; `max_tokens: 2000` nas capacidades Anthropic, como a v1; `general_settings.master_key`.
- **Variáveis:** declaradas uma a uma em `environment:` com `${VAR:?mensagem}`, sem `env_file`, por menor privilégio. São elas: `FAKE_OPENAI_KEY`, `FAKE_ANTHROPIC_KEY`, `GATEWAY_MASTER_KEY` e `LITELLM_LOCAL_MODEL_COST_MAP=True` (não buscar a tabela de modelos na internet ao subir).
- **Saúde:** o healthcheck consulta `GET /health/readiness`. A rota `/health` exige chave e testa os modelos, então não serve para o container.
- **Autenticação (provisória):** só a master key, sem banco. Ela será usada também pela app no piloto. Chaves virtuais por consumidor, com PostgreSQL, entram no Passo 12 com ADR próprio.
- **Fora desta decisão:**
  - fallback;
  - retry e timeout configurados;
  - budget, rate limit e preços;
  - isolamento de rede entre `app` e `provider-fake`.

## Consequências

**Comprovadas no Passo 07** (evidências em `docs/gateway/`):

- As 4 capacidades chegam ao provider e ao modelo esperados (`/admin/calls`). As saídas são iguais às da caracterização, incluindo o golden da F2 byte a byte e o relatório de um dia.
- Interface única: os destinos OpenAI e Anthropic respondem no formato Chat Completions, com o nome lógico no campo `model`.
- A troca de modelo é feita por configuração, reiniciando só o gateway (8 s). O container da app não mudou, e `app/` ficou sem diff.
- Streaming SSE passa pelo gateway (primeiro conteúdo em 0,82 s; termina com `[DONE]`).
- O overhead é de +6 ms nas medianas.
- O ambiente sobe do zero com um comando (19 s).

**Ainda não comprovadas** (dependem da migração): a aplicação desacoplada dos providers, credenciais fora da app e troca de modelo sem deploy do helpdesk.

**Negativas e riscos:**

- Um salto e um serviço a mais. O gateway é ponto único de falha das 4 features, e a imagem tem 1,65 GB.
- A imagem faz **2 retentativas por padrão** em 5xx (3 chamadas ao provider, 4,69 s). Somadas às do SDK, uma falha viraria até 9 chamadas; o piloto deve usar `max_retries=0` no cliente (plano, revisão 1.0.1).
- Os erros são normalizados no envelope OpenAI, mas a mensagem é reescrita pelo LiteLLM (cita o provider e o *model group*) e o `code` vira o status (`"400"`). Consumidores devem depender só do status HTTP.
- Sem banco, uma chave inválida recebe 400 (`No connected db.`) em vez de 401. Ainda assim é recusada antes do provider.
- Estado transitório: a app ainda tem as chaves dos providers e, via `env_file`, passou a ver `GATEWAY_MASTER_KEY` sem usá-la.

## Limitações e questões em aberto

- Não está provado que `max_tokens: 2000` é aplicado (as saídas caracterizadas ficam abaixo do limite).
- `midstream_error` não foi testado (Passo 14).
- Budget, rate limit e chaves virtuais exigem PostgreSQL, e os preços dos modelos fake precisam ser declarados em `model_info`; sem eles, o custo é zero (Passo 12).
- `/admin/calls` não identifica quem chamou. A prova de que "tudo passa pelo gateway" será por exclusão (credenciais e URLs ausentes da app) e por contagem (FF10 do plano).

## Evidência

- `docs/gateway/relatorio-gateway.md` e `docs/gateway/evidencias/` (arquivos 00 a 25), gerados por `docs/gateway/experimentos.py`.
- Testes de caracterização com o gateway no ar: `32 passed in 60.01s`.
- `git diff --stat v1-coupled -- app/ tests/characterization/ provider-fake/ edge/ data/`: vazio.

## Revisão no Passo 08 (primeiro consumidor real)

A F1 é o primeiro consumidor real do gateway. Ela usa o adapter `GatewayLanguageModel` (ADR 0002), com `max_retries=0`, `GATEWAY_URL=http://gateway:4000` e a master key entregue ao `app` como `GATEWAY_API_KEY`.

**Confirmado** (`docs/piloto/evidencias/`):
- As chamadas da F1 chegam ao gateway (log com o IP do `app`) e só as dela. F2, F3 e F4 seguem direto ao provider até o Passo 09.
- O retry tem um único dono. Sob 5xx persistente, sai 1 requisição app → gateway e há 3 tentativas no provider, a mesma contagem da v1 (não 9).
- Com uma conexão keep-alive reutilizada pelo cliente único, o custo do salto extra não aparece no caminho feliz: F1 em 1,08 a 1,09 s, antes e depois.

**Consequências previstas que se concretizaram** (agora medidas):

| Consequência | v1 | Com gateway (F1) |
|---|---|---|
| Latência sob falha persistente do provider | 500 em 1,25 s (retries rápidos do SDK) | 500 em 4,6 a 4,7 s (backoff do LiteLLM) |
| Gateway fora do ar | não se aplica | F1 em 500 (3,99 s), 0 chamadas ao provider; F4, ainda direta, segue em 200 |
| Falha de conexão no primeiro salto | 3 tentativas (SDK → provider) | 1 tentativa (app → gateway) |

**Limitações:**
- O ponto único de falha deixou de ser hipótese: cada feature migrada no Passo 09 passa a depender dele em execução (risco R19 do plano).
- O backoff padrão nunca foi uma decisão nossa. O Passo 10 deve configurar `num_retries`, backoff e timeouts explicitamente (R18, R21).
- As mensagens de erro do gateway citam o provider e o *model group*. Hoje aparecem só no log da app, porque a rota responde 500 genérico.
- `max_tokens: 2000` continua sem prova pela app: a F1 não o usa. A verificação fica para a F2.

**A decisão continua válida.** A integração completa não está validada, porque só uma de quatro features migrou.

## Revisão no Passo 09 (comunicação exclusiva pelo gateway)

**Gateway efetivamente utilizado.** LiteLLM Proxy `v1.102.1`, sem banco, `gateway/config.yaml` sem mudança neste passo: 4 capacidades, cada uma com o modelo `large` da v1 e a chave do provider lida do ambiente do gateway.

**Comunicação exclusiva da aplicação.** As quatro features chegam ao provider só pelo gateway:
- FF10: depois de um reset e da suíte inteira, 19 chamadas no provider e 19 `POST /v1/chat/completions` no log do gateway, todas 200 (antes da migração: 19 × 9) (`docs/v2/evidencias/14`).
- Com o gateway parado, as quatro rotas respondem 500 em ~3,9 s e o provider recebe 0 chamadas; o log da app mostra `APIConnectionError` no adapter (`18`). Não existe caminho alternativo.

**Isolamento de detalhes tecnológicos e credenciais.**
- A app não tem SDK `anthropic`, URL de provider, modelo físico nem `max_tokens` (`10`).
- O serviço `app` não tem `env_file` e recebe só `GATEWAY_URL` e `GATEWAY_API_KEY` (`12`). O `provider-fake` também perdeu o `env_file` e recebe só as duas chaves que valida.
- **Decisão deste passo:** a chave de consumo da app continua sendo o **valor** da master key, entregue como `GATEWAY_API_KEY`. A alternativa (chave virtual por consumidor) exige o banco do LiteLLM (Postgres), um serviço a mais que não se justifica antes da governança. Fica para o Passo 12; a app já usa uma variável própria e não precisará mudar de código.
- `max_tokens: 2000` do gateway é o limite efetivamente aplicado: com 20, a F2 veio truncada pela borda (`19`).

**Evidências da troca de modelo.** `reply-suggestion` trocada de `anthropic/claude-fake-large` para `openai/gpt-fake-large` só em `gateway/config.yaml`, com restart só do gateway (8,6 s): mesma resposta byte a byte, mesmo Id, imagem e horário de início do container da app (`20`). Detalhe no ADR 0004.

**Consequências operacionais (medidas).**

| Consequência | v1 | v2 |
|---|---|---|
| Falha persistente (5xx) | 500 em 1,2 a 1,4 s, 3 tentativas | 500 em 4,0 a 4,6 s, 3 tentativas (backoff padrão do LiteLLM) (`16`) |
| Gateway fora do ar | não se aplica | as 4 features em 500; 0 chamadas ao provider |
| Caminho feliz | F1 1,09 s; F4 1,23 s; F2 15,96 s; F3 9,84 s | iguais (`15`) |
| Subida limpa | — | `cp .env.example .env && docker compose up -d --build --wait` em 21,6 s, `32 passed` (`24`) |

O gateway é agora ponto único de falha de toda a IA da aplicação (R19). Timeout, `num_retries` e backoff explícitos são entrada do Passo 10; fallback, do Passo 11; chaves por consumidor e orçamento, do Passo 12.

**A decisão continua válida, sem mudança.**

## Revisão no Passo 12 (2026-11-28)

O texto acima fica como registro. A autenticação provisória terminou: a app passou a usar a chave virtual `helpdesk-app` (`HELPDESK_GATEWAY_KEY`), e a master key só administra o gateway (gateway e serviço de bootstrap a recebem; a app não). O gateway ganhou um Postgres próprio ([ADR 0007](0007-gateway-governance-database.md)), as chaves são criadas sem passo manual ([ADR 0008](0008-key-bootstrap-service.md)) e os preços dos modelos simulados estão declarados em `input/output_cost_per_token` de cada destino, não em `model_info` como previsto antes ([ADR 0010](0010-gateway-governance.md)).
