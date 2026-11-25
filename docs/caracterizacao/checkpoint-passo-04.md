# Checkpoint de continuidade: fim do Passo 04

## Estado atual
- Base: `bf5df3b` (Passo 03), sobre `ab53bae` e `a1aedd7`. `app/`, `provider-fake/`, `edge/` e `data/` estão idênticos a `a1aedd7` e ao `upstream/main`.
- Novos na pasta local: `tests/` (suíte de caracterização), a seção "Como rodar" no README e `docs/caracterizacao/`.
- Commit, tag `v1-coupled` e push: **aguardando a aprovação do Igor**.
- Provider em `normal`, containers no ar.

## Suíte
- 32 testes (F1 13, F2 4, F3 6, F4 9), todos pela borda, com o provider-fake real. Cerca de 60 s.
- Verde em 3 rodadas completas, numa rodada isolada de F4, na ordem inversa e num nó único.
- 5 de 5 mutações das expectativas detectadas, sem falsos positivos.

## Decisões
- Expectativas copiadas de respostas reais (inline ou golden JSON gerado mecanicamente).
- Sem asserções sobre modelo, provider ou contagem de chamadas, para que a mesma suíte valide a v2.
- Execução via `python:3.12-slim` com `host.docker.internal`, sem novo serviço no compose (que exigiria ADR).

## Lacunas para os próximos passos
- Os 502 de validação de saída e as falhas do provider só serão exercitados com injeção de falha.
- F3 com vários lotes e o mês inteiro (504) ficam para a solução assíncrona.
- Comportamentos discutíveis travados como estão: "Não é urgente" → `high`; F4 com dois pedidos pega o primeiro.

## Próximo passo
Depois da tag: `git worktree add --detach ../helpdesk-v1 v1-coupled` para conferir a reprodutibilidade. Em seguida, começar a v2 sempre com esta suíte verde.
