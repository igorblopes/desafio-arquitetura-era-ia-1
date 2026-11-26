# Checkpoint do Passo 09 (entrada do Passo 10)

| Item | Estado |
|---|---|
| Estado da aplicação | desacoplada: as 4 features pelo contrato e pelo gateway; comportamento externo igual à `v1-coupled` (32 testes, OpenAPI idêntico); síncrona; modelos `large` |
| Arquitetura | `edge` → `main` (Composition Root) → features → `ports.LanguageModel` ← `adapters.gateway` → `gateway` (LiteLLM) → `provider-fake` |
| Componentes (`app/helpdesk/`) | `main`, `classification`, `suggestion`, `report`, `extraction`, `ports`, `adapters/gateway`, `schemas`, `tickets`, `config`. `llm.py` removido |
| Contrato | `ports.LanguageModel(Protocol)`: `complete(capability: str, prompt: str) -> str`, sem mudança desde o piloto |
| Adapter | `GatewayLanguageModel(LanguageModel)`: SDK `openai==3.19.0`, `base_url={GATEWAY_URL}/v1`, `api_key=GATEWAY_API_KEY`, `max_retries=0`, `model=capability`; sem timeout próprio nem tratamento de erro |
| Composição | `main.py` cria uma instância no carregamento e a passa por parâmetro às 4 rotas; único importador do adapter |
| Capacidades lógicas | `ticket-classification` (F1), `reply-suggestion` (F2), `topics-report` (F3), `order-extraction` (F4) |
| Modelos físicos | `openai/gpt-fake-large` (F1, F4); `anthropic/claude-fake-large` com `max_tokens: 2000` (F2, F3); só em `gateway/config.yaml` |
| Configuração do gateway | `gateway/config.yaml` sem mudança no passo; sem banco; `master_key` = `GATEWAY_MASTER_KEY`; retries, timeout e fallback **não configurados** (padrões do LiteLLM) |
| Credenciais | `app`: só `GATEWAY_URL` e `GATEWAY_API_KEY` (valor da master key, provisório até o Passo 12). `gateway`: `FAKE_*` e `GATEWAY_MASTER_KEY`. `provider-fake`: só `FAKE_*`. Nenhum `env_file` |
| Integrações antigas removidas | `llm.py`; chaves, URLs, 4 modelos e `MAX_OUTPUT_TOKENS` de `config.py`; `anthropic` de `requirements.txt`; `env_file` e `depends_on: provider-fake` do `app`; `env_file` do `provider-fake` |
| Migrações | F1 (piloto, sem mudança); F4, F2, F3 aprovadas sem correção; remoção e credenciais aprovadas sem correção |
| Handoffs | `docs/v2/handoffs/handoff-1-f4.md` a `handoff-5-credenciais.md`, em duas fases, sessão separada do Claude Code |
| Problemas encontrados | falha persistente mais lenta (4,0 a 4,6 s contra 1,2 a 1,4 s); gateway como ponto único de falha; `str \| None` do SDK (FF12, 1 erro); `pytest` ausente do `metrics/requirements.txt` (a baseline instalou à parte) |
| Correções | nenhuma no código do agente; instrumentos do arquiteto corrigidos antes do uso (comparação de corpos 502, ordem do `/admin/calls`, meta de `config` no handoff 3) |
| Métricas da V1 | `metrics/results/v1-coupled.csv`: 20 arestas; zona de dor `config`, `llm`, `schemas` |
| Métricas da V2 | `metrics/results/v2-decoupled.csv`: 19 arestas; `ports` 5/0/0/1/0; `adapters.gateway` 1/2/0,67/0/0,33; features 0,33; `config` 3/0/0/0/1,00; zona de dor `config`, `schemas`; igual à projeção |
| Comparação | `llm` removido; abstração no centro do grafo; `config` Ca 6 → 3; features D 0,25 → 0,33 (aceito) |
| Testes | `32 passed` em todos os incrementos e 3 vezes no fim (60,10 s; 60,06 s; 60,60 s em cópia limpa); `tests/metrics` 64 passed; `verificacao_v2.py` 13/13 |
| Isolamento tecnológico | FF5 (só o adapter importa SDK), FF6 (só `main` importa o adapter), FF7 e FF8 sem saída, FF9 (ambiente e compose), FF10 (19 = 19), gateway parado → 0 chamadas ao provider |
| Troca de modelo | F2: `anthropic/claude-fake-large` → `openai/gpt-fake-large` só no gateway; resposta idêntica; container da app com o mesmo Id, imagem e horário; restaurado |
| ADRs | 0001 a 0004 com "Revisão no Passo 09"; 0002, 0003 e 0004 aceitos para as 4 features |
| Revisões do plano | 1.2: seção 28; 18, 24, 25, 26.2 e 27 atualizadas |
| Limitações remanescentes | R18 (latência sob falha), R19 (SPOF), R20 (`str \| None`), R21 (1 tentativa no primeiro salto); master key como chave de consumo; suíte sem falhas, timeouts e períodos longos; capacidade em dois lugares |
| Commit da `v1-coupled` | `8028305` (tag anotada `07c2026d`) |
| Commit da `v2-decoupled` | **a registrar** depois do commit do Igor (o código verificado parte de `4a3447a` + alterações locais) |
| Publicação das tags | `v1-coupled` publicada; `v2-decoupled` **pendente** (4.39 a 4.43) |
| Conhecimentos | `docs/v2/glossario.md`; relatório `docs/v2/relatorio-v2.md` |

## Pendências

1. Igor: aprovar o commit, a tag `v2-decoupled` e o push.
2. Depois da tag: `git diff v1-coupled v2-decoupled -- tests/characterization/` vazio (4.40); worktrees das duas tags rodando a suíte, uma de cada vez (4.41); medir os dois worktrees (4.42); push da tag (4.43). Registrar os resultados no relatório (seção 19) e neste checkpoint.

## Entradas do Passo 10 (Timeout, Retry e Backoff)

| Tema | Ponto de partida medido |
|---|---|
| Orçamento de latência | borda 30 s; F2 ~16 s; F3 ~10 s por dia; F1 ~1,1 s; F4 ~1,2 s |
| Timeouts explícitos | nenhum: SDK com o padrão (600 s), gateway com o padrão do LiteLLM, só a borda corta (30 s) |
| Retries limitados | adapter 0; gateway 2 por padrão (3 chamadas ao provider sob 5xx) |
| Exponential Backoff | o do LiteLLM, não decidido: falha persistente em 4,0 a 4,6 s |
| Retry amplification | evitada por `max_retries=0`; voltar o SDK ao padrão levaria a até 9 chamadas |
| Falhas transitórias × persistentes | tratadas igual (retry em todo 5xx) |
| Tratamento de erros | 500 genérico; erro do gateway só no log; conteúdo nulo vira 500 |
| Instrumentos prontos | `docs/v2/sondas_v2.py falha F1..F4`, `verificacao_v2.py`, contagem da FF10 |
