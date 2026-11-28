# Glossário do Passo 12: governança, credenciais, budget e rate limiting

Cada termo vem com onde ele aparece neste projeto.

| Conceito | O que é | No helpdesk |
|---|---|---|
| AI Governance | Conjunto de políticas que dizem quem usa IA, para quê, com que limites e quem responde pelo resultado e pelo custo | [ADR 0009](../adr/0009-corporate-ai-governance.md); executada no gateway ([ADR 0010](../adr/0010-gateway-governance.md)) |
| Corporate Governance | Como a organização decide, delega e presta contas; a governança de IA é um recorte dela | a política simulada do ADR 0009 (providers permitidos, identidade por app, orçamento obrigatório) |
| Accountability | Poder dizer quem consumiu, quanto e para quê, e quem responde por isso | `key_alias`, `metadata.owner`/`cost_center` e `LiteLLM_SpendLogs` por chave |
| IAM | Identity and Access Management: identidades, credenciais e permissões | versão mínima: chaves virtuais com `models` permitidos; sem IAM de usuários finais |
| Authentication | Provar quem é o chamador | `Authorization: Bearer <chave>`; inválida, ausente ou revogada → `401` antes do provider |
| Authorization | Decidir o que o chamador pode fazer | `models` da chave: `governance-budget-demo` pedindo `order-extraction` → `403 key_model_access_denied` |
| Least Privilege | Dar só o acesso necessário | a app recebe só `HELPDESK_GATEWAY_KEY` (4 capacidades, US$ 20, 600 RPM); não recebe master key, chave de provider nem senha do banco |
| API Key | Segredo estático que identifica um consumidor numa API | as chaves `sk-...` do gateway e dos providers simulados |
| Master Key | Chave administrativa do gateway: cria, altera e revoga chaves | `GATEWAY_MASTER_KEY`, só no gateway e no `gateway-bootstrap` |
| Virtual Key | Chave de consumo emitida pelo gateway, com política própria; o provider nunca a vê | `helpdesk-app`, `governance-budget-demo`, `governance-rate-demo` |
| Provider Key | Chave que o gateway usa para falar com o provider | `FAKE_OPENAI_KEY`, `FAKE_ANTHROPIC_KEY`, só no gateway e no provider-fake |
| Service Account | Identidade de um sistema, não de uma pessoa | `helpdesk-app` é a "conta de serviço" do helpdesk no gateway |
| Credential Rotation | Trocar uma credencial por outra sem parar o consumidor | não automatizada; caminho: novo valor no `.env` + `up` cria a nova; revogar a antiga com `/key/delete` |
| FinOps | Prática de dar visibilidade, dono e controle ao custo de nuvem/serviços, com finanças, engenharia e produto juntos | custo por chave e por requisição no gateway; orçamento por identidade |
| Showback | Mostrar a cada time quanto ele consumiu, sem cobrar | `select key_alias, spend from "LiteLLM_VerificationToken"` |
| Chargeback | Cobrar o consumo do centro de custo do time | fora do escopo; o `metadata.cost_center` é o gancho |
| Unit Economics | Custo por unidade de negócio | US$ 0,0001575 por classificação (F1 primária); US$ 0,000222 quando cai no Claude |
| Input Tokens | Tokens enviados ao modelo | `ceil(caracteres/4)` no provider-fake; F1 do TK-00042 = 19 |
| Output Tokens | Tokens gerados | F1 = 11; F2 bem mais (texto longo) |
| Cost Accounting | Registrar o custo de cada chamada e atribuí-lo a alguém | `x-litellm-response-cost` + gasto por chave; só o destino que respondeu é cobrado |
| Budget | Valor máximo que um consumidor pode gastar num período | `max_budget` por chave virtual |
| Soft Limit | Valor que só avisa | `soft_budget: 15` no `helpdesk-app`; sem canal de alerta configurado, fica só registrado |
| Hard Limit | Valor que bloqueia | `max_budget`: `429 budget_exceeded` antes do provider |
| Budget Reset | Volta do gasto a zero no fim do período ou por ato administrativo | `budget_duration: 30d` no helpdesk (`budget_reset_at` calculado pelo gateway); demos só com `--reset-spend` |
| Rate Limiting | Limitar a frequência de consumo | `rpm_limit` por chave; `429 throttling_error` |
| RPM | Requisições por minuto | 3 na demo, 600 no helpdesk; conta a requisição lógica, não as tentativas |
| TPM | Tokens por minuto | não configurado: o risco aqui é frequência e dinheiro, não volume de tokens |
| Quota | Volume acumulado permitido num período longo | o orçamento de 30 dias funciona como quota financeira |
| Throughput | Trabalho concluído por unidade de tempo | o RPM é um teto de throughput por consumidor |
| Burst | Rajada de requisições em pouco tempo | 6 simultâneas na demo de RPM 3: 3 passam, 3 recusadas |
| Throttling | Recusar ou atrasar para conter a taxa | o gateway recusa (não enfileira) e manda `Retry-After: 60` |
| Fixed Window | Contador por intervalo fixo | o limitador v3 do LiteLLM: janela de 60 s a partir da 1ª requisição admitida |
| Sliding Window | Janela que anda com o tempo (log de horários ou média de dois contadores) | não usada; estudada para comparar a borda da janela |
| Token Bucket | Balde que se recarrega a uma taxa e permite rajada até a capacidade | não usado; seria mais suave na virada da janela |
| Leaky Bucket | Fila que escoa a taxa constante | não usado; trocaria recusa por espera, o que não cabe no prazo síncrono |
| TTL | Tempo de vida de um registro | contadores de janela expiram com a janela; cache de gasto relido do banco a cada poucos segundos |
| Race Condition | Resultado depende da ordem de operações concorrentes | duas requisições vendo o mesmo saldo; o LiteLLM evita com reserva atômica (6 → 1 admitida) |
| Atomic Operation | Operação que não pode ser interrompida no meio | incremento do contador de janela e da reserva de orçamento no gateway |
| Bootstrap | Preparar o estado mínimo para o sistema funcionar | `gateway-bootstrap` cria as chaves antes da app subir |
| Provisioning | Criar recursos e credenciais | `POST /key/generate` com o valor fixo do `.env` |
| Idempotência | Repetir a operação dá o mesmo estado | segundo `up`: "já conforme", sem chave nova e sem zerar gasto |
| Configuration as Code | Configuração versionada e aplicada por código | preços em `config.yaml`, identidades em `IDENTITIES`, infraestrutura no `compose.yaml` |
| Startup Readiness | Estar pronto para atender, não só "rodando" | `pg_isready`, `/health/readiness` com `db: connected`, `service_completed_successfully` |
| Desired State / Reconciliation | Declarar o estado desejado e corrigir o que diverge | o bootstrap compara política desejada e efetiva e faz `key/update` só do que diverge |
