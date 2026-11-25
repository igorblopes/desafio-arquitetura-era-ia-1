# 0003. Todas as chamadas de IA passam por um AI Gateway self-hosted (LiteLLM Proxy)

- Status: proposta (validar no Passo 07)
- Data: 2026-11-25
- Nível: solução

## Contexto

Problemas da integração direta, comprovados no Passo 02:

| Problema | Evidência |
|---|---|
| Credenciais dos providers dentro da aplicação | `config.py:3-4`; o serviço `app` recebe `env_file: .env` com `FAKE_OPENAI_KEY` e `FAKE_ANTHROPIC_KEY` |
| Troca de modelo exige editar `config.py:10` e fazer rebuild | 6–7 s de rebuild, com 502 na borda durante a troca |
| Cada feature presa a um provider | openai fora derruba F1 e F4; anthropic fora derruba F2 e F3 |
| Nenhum ponto central para custo, limites, retry ou fallback | os padrões dos SDKs ficam espalhados (3 tentativas, timeout de 600 s) |

O desafio pede um gateway como serviço `gateway` no Docker Compose. Não permite providers reais nem serviços pagos. Exige ADR para qualquer serviço novo.

## Opções consideradas

| Opção | Resolve credenciais e modelo fora da app? | Local e gratuito? | Observação |
|---|---|---|---|
| SDKs diretos (v1) | não | sim | é o problema |
| Biblioteca de abstração na app (ex.: LiteLLM SDK) | não | sim | padroniza a interface, mas as chaves e os modelos continuam no processo da app |
| **AI Gateway self-hosted (LiteLLM Proxy)** | sim | sim | sugerido pelo enunciado; API OpenAI-compatível; `model_name` lógico mapeado para `litellm_params` físico |
| AI Gateway SaaS | sim | não | proibido |

## Decisão

Opção 3, LiteLLM Proxy, como serviço `gateway` no `compose.yaml`, com a versão da imagem fixada no Passo 07.

- **Posição arquitetural:** fica entre o adapter da aplicação (`adapters/gateway.py`) e o `provider-fake`. É acessível só pela rede interna do compose. A borda (`edge`) continua sendo a única entrada externa da aplicação.
- **Responsabilidades na v2:**
  - guardar as credenciais dos providers, lidas do ambiente do próprio `gateway`;
  - mapear capacidade lógica para modelo físico e provider (ADR 0004);
  - expor uma API única e traduzir para a API Anthropic;
  - autenticar a aplicação por uma chave própria (`GATEWAY_API_KEY`);
  - definir `max_tokens = 2000` nas capacidades Anthropic. Esta decisão é **provisória** e depende da validação no Passo 07.
- **Fora da v2:** fallback, retry configurado, timeouts por capacidade, budget, rate limiting, virtual keys e banco de dados. Essas decisões ficam para os ADRs da `main`.
- **Serviço `app`:** deixa de receber `env_file: .env` e passa a receber só `GATEWAY_URL` e `GATEWAY_API_KEY` (incremento 9 do plano).

## Consequências

- (+) A troca de modelo vira configuração do gateway, sem rebuild da aplicação.
- (+) As credenciais saem do código e do ambiente da `app`.
- (+) Fallback, governança e custo terão um ponto central na `main`.
- (−) Um serviço e um salto de rede a mais; o gateway vira ponto único de falha.
- (−) Uma tradução OpenAI → Anthropic que precisa preservar o texto byte a byte (golden da F2).
- (−) Os retries padrão do proxy se somam aos 2 do SDK no adapter (risco R16 do plano).

### Limitações a investigar no Passo 07

1. `api_base` customizado para o fake Anthropic.
2. O texto da F2 idêntico ao golden.
3. O `max_tokens` padrão do proxy, e se é configurável por modelo.
4. Os retries padrão do proxy.
5. A latência adicional frente aos 30 s da borda.
6. Como provar que todas as chamadas passam pelo gateway (logs × `/admin/calls`).
7. Se a master key funciona sem banco.
8. Se vale isolar a rede do `app` em relação ao `provider-fake`.

## Evidência

Pendente (Passo 07). Critérios para aceitar:

- o serviço `gateway` sobe com `docker compose up`;
- as 4 capacidades respondem direto no gateway com os mesmos textos dos goldens e das expectativas da caracterização;
- a requisição sem a chave do gateway é recusada;
- `docker compose config` mostra as chaves `FAKE_*` só nos serviços `gateway` e `provider-fake`, a partir do incremento 9;
- os 32 testes de caracterização continuam verdes.
