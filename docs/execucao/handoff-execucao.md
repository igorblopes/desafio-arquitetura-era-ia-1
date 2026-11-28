# Handoff do Passo 13: consolidação da execução síncrona de F1 e F4

Handoff preparado na subetapa 4.24 para o agente de implementação, no formato dos Passos 08 a 12. Foi escrito **depois** da revisão (4.15 a 4.20) e da baseline (4.11), porque só então havia problemas comprovados para entregar. O plano do agente aparece no fim, revisado antes da execução.

## Contexto

| Item | Estado em `8227f5a` |
|---|---|
| Arquitetura | borda nginx (30 s) → FastAPI `def` → feature → `ports.LanguageModel` → `adapters.gateway` (SDK `openai`, `max_retries=0`) → LiteLLM `v1.102.1` → provider-fake |
| Modos de execução | F1 e F4 síncronas e mantidas assim (ADR 0011); F2 streaming e F3 assíncrona são hipóteses para os Passos 14 e 15 |
| Contratos | F1 `{"ticket_id","category","priority"}` com enums fechados; F4 `{"ticket_id","order_number","product"}`, número `#` + 6 dígitos ou `null`, produto texto ou `null` |
| Resiliência | gateway: timeout 3 s por tentativa (mini 2 s), primário repete 1× só em `500`/`503`, backoff nativo; app: prazo global 14 s (`config.GATEWAY_DEADLINE_SECONDS`) |
| Fallback | F1: primário → `claude-fake-large` → `gpt-fake-mini`; F4: primário → `claude-fake-large` → erro (mini proibido, ADR 0006) |
| Governança | chave virtual `helpdesk-app`; recusas antes do router viram `503 model_budget_exceeded` / `model_throttled` e `502 model_rejected` |
| Latência medida pela borda | F1 e F4 ~1,09 s normal; primário travado 4,1 s (F1) e 4,25 s (F4); pior caso do gateway 8,05 s (F1) e 6,05 s (F4); gateway congelado 14,02 s |

### Problemas comprovados (evidência `evidencias/15-contrato-saida-antes.txt`)

| # | Feature | Saída do modelo | Resposta antes | Problema |
|---|---|---|---|---|
| 1 | F1 e F4 | JSON entre cercas, texto livre, lista, `null` | `500 Internal Server Error` (texto) | falha não explícita, sem distinção de bug da app |
| 2 | F1 | `{"ticket_id": "TK-99999", ...}` | `500` (`TypeError` de argumento duplicado) | o `**data` deixa o modelo interferir no `ticket_id` |
| 3 | F1 | `{"category": ["delivery"], ...}` | `500` (`unhashable list`) | tipo não verificado antes do `in` |
| 4 | F4 | `{}`, só um dos campos | **`200` com `null` fictício** | falha mascarada como ausência legítima, numa automação sem revisão |
| 5 | F4 | `"#481516\n"`, `"#٤٨١٥١٦"` | **`200` com número inválido** | `re.match("^#\d{6}$")` aceita `\n` no fim e dígitos Unicode |
| 6 | F4 | número ou produto numérico | `500` | tipo não verificado |

O provider-fake não produz nenhum desses casos (é determinístico e sempre devolve JSON correto). Eles aparecem com LLMs reais e foram reproduzidos com o código real em processo e um `LanguageModel` substituto.

## Tarefa

1. Fazer toda saída fora do contrato virar `502` explícito, sem `500` e sem `200`.
2. F1: construir `Classification` com campos explícitos (o `ticket_id` vem sempre da requisição); checar tipo antes do enum.
3. F4: exigir as duas chaves presentes (mesmo `null`); validar `order_number` com `fullmatch` de `#[0-9]{6}`; validar `product` como texto ou `null`.
4. Produzir `tests/execution`: contrato de saída em processo, prazo da app com gateway mudo e integração pela borda (latência, fallback, timeout, mini proibido, governança).

## Escopo autorizado

`app/helpdesk/classification.py`, `app/helpdesk/extraction.py`, `tests/execution/`, `docs/execucao/`, `docs/adr/0011-execution-modes.md`, `README.md`.

## Restrições

- Não alterar F2 (`suggestion.py`) nem F3 (`report.py`), nem `main.py`, `ports.py`, `schemas.py`, `adapters/`, `config.py`, `gateway/`, `compose.yaml`.
- Não implementar streaming nem processamento assíncrono; não converter rotas para `async def`.
- Não tocar `provider-fake/`, `edge/`, `data/`, `tests/characterization/` nem as tags.
- Não reintroduzir modelos físicos, chaves de provider ou master key em `app/`.
- Não mudar a política de fallback, os timeouts, o prazo de 14 s nem os enums.
- Não adicionar módulo, dependência ou import novo (a régua de métricas não pode mudar por isso).
- Não fazer commit (o usuário revisa e commita).

## Plano apresentado pelo agente (revisado antes da execução)

| Passo | Plano | Revisão |
|---|---|---|
| 1 | Escrever `test_output_contract.py` e rodar contra o código atual para registrar as falhas | ✅ prova antes de corrigir |
| 2 | Criar um módulo `helpdesk/output.py` com o parser comum | ❌ rejeitado: novo componente na régua e abstração para 6 linhas; manter uma função privada `_json_object` em cada feature (duplicação consciente; extrair quando houver um terceiro uso, provavelmente a F3 no Passo 15) |
| 3 | Usar `Literal` nos schemas de resposta | ❌ rejeitado: muda o OpenAPI (evidência de contrato idêntico ao da v1) sem ganho; os conjuntos `CATEGORIES`/`PRIORITIES` já existem |
| 4 | Corrigir `classification.py` e `extraction.py` como na Tarefa | ✅ |
| 5 | Erro `502` com `{"detail"}` (mesmo formato do `502` que já existia) | ✅ mantém o comportamento caracterizado; `code` só existe nos erros do modelo (limitação registrada) |
| 6 | Reconstruir a app, rodar `tests/execution` e as 4 suítes anteriores | ✅ |
