# Handoffs: governança no gateway (Passo 12)

Handoffs incrementais para o agente de implementação, um bloco por vez. As decisões de política (identidades, valores, onde recusar) foram tomadas antes, com evidência, e **não** são do agente: ele apresenta o plano do bloco antes de mexer no código, o plano é revisado contra os critérios abaixo e só então executado.

> Neste passo a implementação foi feita pelo Claude Code na própria sessão de mentoria, seguindo estes blocos na ordem. Os itens "Ocorreu na implementação" são fatos observados; os itens "Recusar na revisão" são o que um revisor deve barrar se o agente propuser.

## Contexto comum a todos os blocos

- App desacoplada (`v2-decoupled` + Passos 10 e 11): features pedem 4 capacidades lógicas por `ports.LanguageModel`; adapter único `adapters/gateway.py`; `max_retries=0` no SDK.
- Gateway LiteLLM Proxy `v1.102.1`, `gateway/config.yaml` com 10 grupos (4 capacidades, 4 `-equivalent`, 2 `-degraded`), retry e fallback no router.
- Ponto de partida (evidência `00`): app com a **master key**; custo `0.0`; sem banco (`/key/info` → `500 Database not connected`).
- Preços: `provider-fake/README.md` (US$/1M): GPT L 2,50/10; Claude L 3/15; GPT m 0,15/0,60; Claude m 0,80/4.
- Diretórios protegidos: `provider-fake/`, `edge/`, `data/`, `tests/characterization/`; tags `v1-coupled` e `v2-decoupled`.
- Proibido em todos os blocos: novo serviço sem ADR, propriedade YAML ou endpoint inventado, master key ou chave de provider na app, retry/fallback de recusa de governança, rate limit no Nginx, algoritmo próprio de rate limit, cache, streaming, assíncrono, circuit breaker.
- Formato da entrega: diff, comandos rodados com saída, o que não foi verificado.

## Bloco 1. Infraestrutura de governança
- **Problema:** chave virtual e orçamento exigem banco no LiteLLM (evidência `00`).
- **Arquivos:** `compose.yaml`, `.env.example`.
- **Estratégia aprovada:** `gateway-db` `postgres:17.2-alpine`, volume nomeado, `pg_isready`, sem porta no host; `DATABASE_URL` só no gateway; gateway espera o banco saudável. Sem Redis (uma instância).
- **Aceite:** `docker compose config` sem `DATABASE_URL`/senha na app; `/health/readiness` → `db: connected`; migrações sem internet.
- **Recusar na revisão:** publicar `5432` no host "para depurar" (use `docker compose exec gateway-db psql`); Redis "por boa prática"; `env_file` compartilhado.

## Bloco 2. Precificação
- **Problema:** custo zero com modelos simulados.
- **Arquivos:** `gateway/config.yaml`.
- **Estratégia:** `input_cost_per_token`/`output_cost_per_token` em cada um dos 10 destinos (custo do modelo que respondeu).
- **Aceite:** `x-litellm-response-cost` = cálculo manual nos 4 modelos (`sondas_governanca.py precos`); nenhuma chamada `200` com custo 0.
- **Recusar na revisão:** preço só no grupo primário ou na capacidade (o fallback seria cobrado pelo preço errado ou zero); preço de modelo comercial real; unidade por 1M colada como se fosse por token.

## Bloco 3. Provisionamento automatizado
- **Problema:** `cp .env.example .env && docker compose up -d --build --wait` sem passo manual.
- **Arquivos:** `gateway/scripts/bootstrap_keys.py`, `compose.yaml`, `.env.example`.
- **Estratégia:** serviço `gateway-bootstrap` (imagem do gateway), valores fixos no `.env`, `GET /key/info` → `generate` ou `update` só de política, verificação final, `exit 1` em falha; app com `service_completed_successfully`.
- **Aceite:** cenários A–D do [ADR 0008](../adr/0008-key-bootstrap-service.md); nenhuma chave duplicada; gasto preservado; log sem segredo.
- **Ocorreu na implementação:** a primeira versão comparava `soft_budget` com um campo que o LiteLLM guarda em outra tabela e falhava na verificação; a falha parou a subida da app (comportamento desejado) e foi corrigida. O reset ingênuo (`spend: 0`) foi desfeito pela gravação em lote do gasto; o reset passou a esperar o gasto estabilizar.

## Bloco 4. Budget
- **Arquivos:** `IDENTITIES` do bootstrap.
- **Estratégia:** `governance-budget-demo` com US$ 0,0004, só `ticket-classification`, sem RPM; `helpdesk-app` com US$ 20/30 dias.
- **Aceite:** 3 × `200`, 4ª `429 budget_exceeded`, `/admin/calls` igual antes e depois.

## Bloco 5. Rate limiting
- **Estratégia:** `rpm_limit` nativo do LiteLLM (limitador v3, memória); `governance-rate-demo` com 3 RPM e US$ 1.
- **Aceite:** 3 × `200`, 4ª `429 throttling_error`, 0 chamadas novas, recuperação após a janela; janela documentada como observada (não presumida).

## Bloco 6. Integração com resiliência
- **Arquivos:** `app/helpdesk/adapters/gateway.py`, `ports.py`, `main.py`.
- **Estratégia:** menor mudança: dois motivos novos no contrato (`throttled`, `budget_exceeded`) e `retry_after` opcional; decisão pelo `type` do corpo e pelo início da mensagem no `429`; respostas sem detalhe administrativo; nenhum retry na app.
- **Aceite:** `429` do gateway ≠ `429` do provider; nenhuma chamada ao provider com orçamento/RPM esgotado e cadeia em falha.
- **Recusar na revisão:** repetir o `429` de RPM na app depois do `Retry-After` (repetir é decisão do consumidor final e não cabe no prazo síncrono); decidir só pelo status HTTP; devolver resposta vazia ou campo nulo no lugar da recusa.

## Bloco 7. Testes
- **Arquivos:** `tests/governance/`.
- **Estratégia:** gateway e provider reais; chaves efêmeras por teste (não consome as demos nem a do helpdesk); prova por `/admin/calls`; app real em processo para a tradução de erros.
- **Aceite:** suíte verde duas vezes seguidas; caracterização, resiliência e fallback inalteradas e verdes.

## Bloco 8. Documentação
- ADRs 0007–0010, revisões em 0003/0005/0006, README (Roteiro de governança), relatório, glossário e checkpoint, todos com valores conferidos contra a configuração e as evidências.
