# 0003. Todas as chamadas de IA passam por um AI Gateway self-hosted (LiteLLM Proxy)

- Status: aceita para a infraestrutura (validada isoladamente no Passo 07); a integração com a aplicação está pendente (Passos 08 e 09)
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
