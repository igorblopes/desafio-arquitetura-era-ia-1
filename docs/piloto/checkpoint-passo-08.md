# Checkpoint do Passo 08 (entrada do Passo 09)

| Item | Estado |
|---|---|
| Estado da aplicação | transitório: F1 pelo contrato e pelo gateway; F2, F3 e F4 via `llm.py` direto ao provider-fake. Comportamento externo igual à `v1-coupled` (32 testes) |
| Componente selecionado | F1, `app/helpdesk/classification.py` |
| Justificativa | menor feature com o caminho completo (prompt, JSON, regra de negócio com 502); 13 testes; determinística; mesma forma da F4 |
| Hipótese | a F1 deixa de conhecer provider, modelo e SDK sem mudar comportamento, e o padrão se repete sem mudar o contrato. **Confirmada** na F1; a repetição é provável e só o Passo 09 comprova |
| Agente | Claude Code, sessão separada na máquina do Igor (modelo não registrado) |
| Handoff | `docs/piloto/handoff-f1.md`, em duas fases; registro em `docs/refactoring-plan.md` §19.2 |
| Contrato | `ports.LanguageModel(Protocol)`: `complete(capability: str, prompt: str) -> str` |
| Adapter | `adapters/gateway.py`: `GatewayLanguageModel(LanguageModel)`, SDK `openai`, `base_url={GATEWAY_URL}/v1`, `GATEWAY_API_KEY`, `max_retries=0`, `model=capability` |
| Composição | `main.py` cria uma instância no carregamento do módulo e a passa por parâmetro à F1 |
| Arquivos modificados | agente: `classification.py`, `main.py`, `ports.py` (novo), `adapters/__init__.py` (novo), `adapters/gateway.py` (novo). Arquiteto: `config.py` (+`GATEWAY_URL` e `GATEWAY_API_KEY`), `compose.yaml` (`environment` e `depends_on` do `app`), `.env.example`, `README.md`, `docs/refactoring-plan.md` (1.1), ADRs 0001 a 0004, `docs/piloto/` |
| Métricas anteriores | `pilot-before.csv` = `v1-coupled.csv`. `classification` 1/3/0,75/0/0,25; `llm` 4/1/0,20/0/0,80; 20 arestas |
| Métricas posteriores | `pilot-after.csv`: `classification` 1/2/0,67/0/0,33; `ports` 2/0/0/1/0; `adapters.gateway` 1/2/0,67/0/0,33; `llm` 3/1/0,25/0/0,75; `main` 0/6/1/0/0; 22 arestas. Igual à projeção |
| Testes | `32 passed` antes (59,95 s), depois do incremento de infraestrutura (60,02 s), pelo agente (60,33 s) e pelo arquiteto (59,97 s); `tests/metrics` com 64 passed; `verificacao_f1.py` OK |
| Gateway | log com 9 chamadas da suíte (os 9 sucessos da F1) vindas do IP do `app`; sob falha, 1 requisição + 2 retries do LiteLLM; com o gateway parado, F1 em 500 e F4 em 200 |
| Troca de modelo | só `gateway/config.yaml` mudou e a F1 passou a ser atendida por `anthropic`/`claude-fake-large` pela borda, com a mesma resposta e a app intocada; restaurado |
| Problemas | FF6 cega aos imports relativos; a suíte não cobre 502 e falhas; falha persistente 1,25 → 4,6 s; gateway como dependência em execução; 1 tentativa de conexão no primeiro salto; `str \| None` × `str` (pré-existente) |
| Correções | nenhuma no código do agente; a FF6 e o protocolo de validação foram corrigidos no plano |
| Decisão | **aprovada** |
| Revisões do plano | 1.1: FF6 corrigida, FF12, protocolo 17.6 com itens 11 a 13, processo real (17.8, 18, 22), riscos R18 a R21, seções 19.2, 23, 24 e 25 |
| Reutilizável | contrato e adapter sem mudança; uma linha de composição por rota; `sondas.py` e `verificacao_f1.py` como modelo; handoff em duas fases; infraestrutura separada do código do agente |
| Limitações | o caminho Anthropic e o `max_tokens` não foram exercitados pela app; a régua não vê dependências de execução; uma única feature migrada |
| Riscos remanescentes | R5, R6, R14 (F2); R17; R18 a R21 |
| Commits de referência | `v1-coupled` = `8028305` (tag `07c2026d`); Passo 05 (régua) = `13fc247`; antes do piloto = `6efadeb`; **depois do piloto: o commit do Igor (a registrar)** |
| Conhecimentos | ver `docs/piloto/glossario.md` e o relatório, seção 2 |

## Pendências para o Passo 09

1. Migrar F4, F2 e F3 nessa ordem. Para cada uma: verificação própria contra gateway simulado, sonda de falha pela borda, FF6 revisada e FF12.
2. Na F2: provar que o texto continua byte a byte pela app e que `max_tokens` é aplicado.
3. Na F3: só a linha da chamada e a assinatura mudam; medir o efeito de R18 em várias chamadas.
4. Incremento 8: remover `llm.py`, as chaves `FAKE_*`, as URLs, os modelos físicos e `MAX_OUTPUT_TOKENS` de `config`, e o `anthropic` de `requirements.txt`.
5. Incremento 9: `app` sem `env_file`, só com `GATEWAY_*` (FF9).
6. Medir a v2, repetir a troca de modelo pela borda e criar a tag `v2-decoupled`, só com a aprovação do Igor.
7. Levar R18 a R21 como entradas do Passo 10.
