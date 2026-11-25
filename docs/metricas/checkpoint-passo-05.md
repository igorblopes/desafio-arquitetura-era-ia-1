# Checkpoint de continuidade: fim do Passo 05

## Estado
- Aplicação: inalterada (`app/`, `provider-fake/`, `edge/`, `data/` idênticos a `a1aedd7`).
- Commit analisado: `80283055f02175a84c8b6bc62dacf81964ad15f0`, via tag anotada `v1-coupled` (`07c2026d`), no worktree `../helpdesk-v1`.
- Nesta etapa, na pasta local: `metrics/`, `tests/metrics/`, `metrics/results/v1-coupled.{csv,png}`, `docs/metricas/`, `docs/adr/0001-metrics-and-architectural-stability.md` e as seções do README.

## Ferramenta
- `metrics/measure.py` (CLI) + `discovery`, `parsing`, `dependencies`, `abstraction`, `calculations`, `reporting`.
- Análise: só biblioteca padrão (`ast`, `pathlib`, `fractions`, `decimal`, `csv`). Gráfico: `matplotlib==3.11.2`.
- Por quê: AST não executa o código analisado (o `config.py` real quebraria fora do container); frações exatas evitam erro de arredondamento; módulos separados permitem testar cada responsabilidade.

## Comandos
```bash
pip install -r metrics/requirements.txt pytest
python -m pytest tests/metrics -q
git worktree add --detach ../helpdesk-v1 v1-coupled   # se ainda não existir
python metrics/measure.py --source ../helpdesk-v1/app/helpdesk --name v1-coupled
```

## Resultados
- Testes da ferramenta: 64 verdes; 6 de 6 mutações deliberadas da ferramenta detectadas.
- v1: 9 componentes, 20 arestas, sem ciclos, A = 0 em todos.
- Zona de dor: **`config`** (D=1,00), **`llm`** (D=0,80), **`schemas`** (D=1,00).
- No limite: `tickets` (I=0,50, D=0,50).
- SDP respeitado em todas as arestas; SAP violado nos três estáveis.

## Exceções candidatas
- `schemas` (DTOs do contrato HTTP): candidata, revisar na versão final.
- `config`: **não** é candidata (guarda decisões voláteis de infraestrutura).
- `llm` / futuro componente de comunicação com o gateway e as features: **proibidos** como exceção.

## Limitações
Não captura acoplamento externo (SDKs), semântico, de runtime, HTTP, coesão nem frequência de mudança. Isolados e DTOs geram falsos positivos.

## Hipóteses para o Passo 06
Inverter `llm` (contrato de capacidade + adaptador para o gateway); tirar nomes de modelo de `config`; features dependendo da capacidade, não do provider.

## Pendências
- `git push origin v1-coupled` (a tag ainda não está no remoto).
- Medições da `v2-decoupled` e da `main` final nos passos 09 e 16, com a mesma ferramenta e a mesma régua.
