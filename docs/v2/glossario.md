# Glossário do Passo 09: refatoração completa

Cada conceito traz a definição curta e onde ele apareceu de verdade neste passo. As evidências citadas estão em `docs/v2/evidencias/`. O glossário do piloto (`docs/piloto/glossario.md`) continua válido para os conceitos introduzidos lá.

| Conceito | Definição | Onde apareceu no projeto |
|---|---|---|
| Refatoração incremental | mudar a estrutura em passos pequenos, cada um verificado e reversível, sem mudar o comportamento | 5 incrementos (F4, F2, F3, remoção, credenciais), cada um com `32 passed`, verificação própria e métricas antes do próximo |
| Big Bang Refactoring | reescrever ou migrar tudo de uma vez e validar só no fim | rejeitado: migrar as 4 features e remover `llm.py` num único diff não diria qual mudança quebrou o quê |
| Parallel Change | expandir, migrar os consumidores e contrair, mantendo o sistema funcionando no meio | `llm.py` e o contrato conviveram do Passo 08 até o incremento 4 deste passo |
| Branch by Abstraction | introduzir uma abstração, mover os consumidores para ela um a um e só então remover a implementação antiga | `ports.LanguageModel` criada no piloto; F4, F2 e F3 passaram a ela uma por vez; `llm.py` removido quando chegou a Ca=0 |
| Expand and Contract | o mesmo padrão aplicado a configuração e interfaces: acrescentar o novo, migrar, retirar o velho | `config.py` ganhou `GATEWAY_*` no Passo 08 e perdeu chaves, URLs e modelos no incremento 4; o compose ganhou o gateway no Passo 07 e perdeu o `env_file` do `app` no incremento 5 |
| Arquitetura transitória | estado intermediário, deliberado e funcional, em que convivem o caminho antigo e o novo | `4a3447a`: F1 pelo gateway, F2/F3/F4 diretas; FF10 mostrava 19 chamadas no provider e 9 no gateway (`03`) |
| Dependency Inversion Principle | política e detalhe dependem de abstrações, não um do outro | as 4 features e o adapter apontam para `ports`; nenhuma seta vai da feature para a tecnologia (FF6, `10`) |
| Dependency Injection | o objeto recebe as dependências de fora | `suggest(ticket, model)`, `topics(period, model)`, `extract(ticket, model)`, `classify(ticket, model)` |
| Composition Root | o único lugar onde os concretos são criados e ligados | `main.py`: `language_model = GatewayLanguageModel()` uma vez, passada às 4 rotas; único import do adapter (`main.py:4`) |
| Ports and Adapters | a aplicação define portas; a tecnologia fica em adapters plugados na borda | `ports.py` + `adapters/gateway.py`; o gateway simulado da verificação é outro "adapter" que cabe na mesma porta |
| Structural Typing | compatibilidade pela forma, não pela declaração | qualquer objeto com `complete(capability, prompt)` serve às features; o `mypy` confere o adapter contra o `Protocol` (FF12) |
| Vendor Lock-in | dependência de um fornecedor que torna a troca cara | na v1, SDKs e nomes de modelo de dois providers dentro da app; na v2, a troca da F2 de Anthropic para OpenAI foi uma edição de 3 linhas no gateway (`20`). O lock-in mudou de lugar: agora é o LiteLLM, isolado num adapter |
| Capacidade lógica | nome estável do que a feature precisa, sem dizer quem atende | `reply-suggestion`, constante em `suggestion.py` e `model_name` em `gateway/config.yaml` |
| Modelo físico | o modelo concreto de um provider | `anthropic/claude-fake-large`; só existe em `gateway/config.yaml` (FF7 sem saída em `app/`) |
| Isolamento de credenciais | cada credencial só onde é usada | chaves dos providers só no `gateway` (usa) e no `provider-fake` (valida); o `app` só com `GATEWAY_API_KEY` (`12`) |
| Princípio do menor privilégio | cada componente recebe só o acesso necessário | o `env_file` injetava o `.env` inteiro em `app` e `provider-fake`; trocado por `environment` com só as variáveis lidas |
| Architectural Fitness Function | verificação objetiva de uma característica arquitetural | FF1 a FF12 rodadas na verificação final; FF10 objetiva por contagem (19 = 19, `14`) |
| Regressão | mudança indesejada em comportamento que funcionava | nenhuma na suíte; fora dela, falha persistente passou de ~1,3 s para ~4,3 s (backoff do gateway), registrada como entrada do Passo 10 |
| Compatibilidade de contratos | clientes antigos continuam funcionando sem mudança | OpenAPI gerado da v1 e da v2 idêntico (`22`); 32 golden masters sem alteração |
| Código legado | código em produção cujo comportamento precisa ser preservado, em geral sem testes suficientes | a v1, protegida primeiro pela caracterização (Passo 04) e só depois refatorada |
| Desacoplamento tecnológico | a regra de negócio não depende da tecnologia que a executa | `app/` sem `anthropic`, sem URL de provider, sem modelo físico; um único import de SDK, no adapter (FF5) |
| Reprodutibilidade | qualquer pessoa obtém o mesmo resultado com os mesmos passos | cópia limpa com `cp .env.example .env && docker compose up -d --build --wait` → `32 passed` (`24`); medição repetida com CSV idêntico (`23`) |
| Marco arquitetural | estado nomeado e verificado que serve de referência | `v1-coupled` (ponto de partida) e `v2-decoupled` (desacoplado, ainda sem políticas) |
| Git Tag | referência imutável a um commit; anotada, carrega autor, data e mensagem | `v1-coupled` (`07c2026d` → `8028305`); `v2-decoupled` a criar com `git tag -a` depois da aprovação |
| Git Worktree | outro diretório de trabalho do mesmo repositório, em outro commit | `../helpdesk-v1` (desde o Passo 05) e `../helpdesk-v2` (depois da tag) para rodar e medir as duas versões lado a lado |
