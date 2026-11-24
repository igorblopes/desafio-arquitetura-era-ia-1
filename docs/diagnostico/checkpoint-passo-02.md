# Checkpoint de continuidade: fim do Passo 02

Use este arquivo como contexto para os próximos passos.

## Estado atual
- Repositório local `D:\Projetos\Fullcycle\desafio-arquitetura-era-ia-1`, branch `main`, commit `a1aedd7`. `app/`, `provider-fake/`, `edge/` e `data/` estão idênticos ao `upstream/main`.
- Remotes: `origin` (fork do Igor) e `upstream` (Full Cycle). `.env` criado a partir do `.env.example`.
- README do fork: a seção "Diagnóstico da v1" foi escrita no `README.md`, **sem commit**.
- Containers no ar; provider em `normal`; `/admin/calls` limpo.
- Ainda não existem: a tag `v1-coupled`, a suíte de caracterização, o script de métrica e o gateway.

## Problemas comprovados (com evidência)
1. **F3 mês:** 504 em 30,03 s. 34 chamadas em série, 30 depois do corte, 195k/10,7k tokens, cerca de US$ 0,75 desperdiçados. Sem cancelamento. Causa: `report.py:15-18`, rota `def` em `main.py`, `proxy_read_timeout 30s`.
2. **F2:** TTFB = total = 15,96 s (5 medições), contra TTFT de 0,81 s; `stream: false`; 606 tokens. Causa: `llm.py:20-26`, `suggestion.py`.
3. **Providers:** openai fora → F1 e F4 com 500/504; anthropic fora → F2 e F3. Sempre 3 tentativas (backoff de 0,5/1 s; 2 s com `Retry-After`). 429 vira 500. Timeout: tentativas de 300 s, até ~15 min órfão. `slow` anthropic: F2 e F3 com 504.
4. **Troca de modelo:** restart não basta; precisa editar `config.py:10` e rebuild (6–7 s, com 502 na borda).

## Padrões dos SDKs (no container)
- `openai 3.19.0` e `anthropic 1.8.0`: timeout de connect 5 s e read 600 s; `max_retries` 2; retenta 408/409/429/≥500; backoff `min(0,5·2ⁿ, 8)` com jitter; respeita `Retry-After` (openai até 120 s).
- Diferença: o anthropic 1.8.0 não retenta um timeout do lado do cliente; o openai retenta.

## Baseline da v1 (normal, pela borda)
F1 1,08 s · F2 15,96 s (1º conteúdo = total) · F3 1 dia 9,84 s · F3 mês 504 em 30,03 s · F4 1,08 s · 3 tentativas sob falha · 2 features afetadas por provider · troca de modelo = código + rebuild.

## Cuidados de protocolo
- No modo `timeout`, o fake grava `status: 504` no início. Use `duration_ms: null` para detectar chamadas em andamento.
- `/admin/reset` apaga também o registro das chamadas em andamento. Reinicie o `app` para matar órfãs.
- Os retries do SDK se somam a retries que forem configurados no gateway ou na aplicação.

## Questões em aberto
- Impacto das threads presas sobre a capacidade do pool (não medido).
- Qualidade dos modelos `mini` por tarefa (Passo 03).
- Onde colocar timeout, retry e fallback sem multiplicar tentativas (SDK × gateway).

## Próximas atividades
Passo 03: comparar `large` × `mini` por tarefa. Depois: testes de caracterização + tag `v1-coupled`, script de métrica, plano de refatoração, gateway, modos de execução e ADRs.

## Conhecimentos consolidados
Timeout ≠ cancelamento; o menor timeout da cadeia vence; TTFT ≠ TTFB ≠ primeiro conteúdo; retry ajuda na falha transitória e amplifica a persistente; acoplamento ao modelo físico transforma decisão operacional em deploy.
