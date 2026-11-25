# Glossário do Passo 06 (refatoração arquitetural)

Cada conceito traz o significado e onde ele aparece no helpdesk.

| Conceito | Significado | No projeto |
|---|---|---|
| Refatoração | Muda a estrutura interna sem mudar o comportamento observável, em passos pequenos e verificáveis (Fowler). | Mover a F1 de `llm.call_openai` para `LanguageModel.complete`, com os mesmos 32 testes verdes. |
| Reescrita | Substitui o sistema por outro, construído do zero. | Descartada: perderia o comportamento caracterizado de uma aplicação de ~200 linhas que funciona. |
| Reengenharia | Analisa e reconstrói um sistema existente, muitas vezes mudando a tecnologia. | Não é o caso: FastAPI, rotas e contratos continuam os mesmos. |
| Dívida arquitetural | Custo futuro causado por decisões estruturais que facilitaram o presente. | Modelos físicos em `config.py`: trocar um modelo custa uma edição e um rebuild (Dor 4). |
| Erosão arquitetural | A estrutura se afasta das intenções à medida que surgem atalhos. | O risco é a v2 voltar a ter uma feature importando o adapter. FF6 vigia isso. |
| Architectural Smell | Sinal estrutural de problema, como dependência de um componente concreto e instável ou um hub. | `llm`: Ca=4, A=0, D=0,80, concreto no centro do grafo. |
| SOLID | Cinco princípios de design: SRP, OCP, LSP, ISP e DIP. | Ver o plano, §10.3. Exemplo de SRP: `llm` mistura dois clientes e o parse. |
| Dependency Inversion Principle (DIP) | Política e detalhe dependem de abstrações; a abstração pertence a quem usa. | `classification` e `adapters.gateway` dependem de `ports.LanguageModel`. |
| Dependency Injection (DI) | Quem usa um objeto o recebe de fora, em vez de criá-lo ou buscá-lo. | `classify(ticket, model)` recebe o adapter por parâmetro. |
| Inversion of Control (IoC) | Quem controla a criação e a ligação dos objetos é o framework ou o ponto de entrada, não o código de negócio. | `main` cria o adapter; a feature só o usa. |
| Composition Root | O único lugar onde os objetos concretos são criados e ligados. | `main.py`, o único importador de `adapters.gateway` (Ca = 1). |
| Ports and Adapters (Hexagonal) | O núcleo define portas; adapters ligam as portas à tecnologia (Cockburn). | Porta de saída: `ports.LanguageModel`. Adapter: `adapters/gateway.py`. Adapter de entrada: as rotas FastAPI. |
| Protocol | Interface estrutural do `typing`: qualquer objeto que tenha os métodos satisfaz o tipo, sem herança. | `LanguageModel(Protocol)`: um dublê de teste com `complete` serve. Conta como abstrato na régua. |
| Abstract Base Class (ABC) | Interface nominal: a implementação precisa herdar e implementar os métodos abstratos. | Considerada e preterida: o Protocol basta e não exige herança. |
| Duck typing / tipagem estrutural | O tipo vale pelo que o objeto faz, não pelo nome da classe. | É por isso que o adapter nem precisaria importar `ports`. A simulação mostrou o efeito disso na métrica (plano, §14.3). |
| Composição | Montar o comportamento combinando objetos, em vez de usar herança ou acesso global. | A feature recebe o modelo; não herda de nada nem acessa um cliente global. |
| Architecture Decision Record (ADR) | Registro curto de uma decisão: contexto, opções, decisão, consequências e evidência. | ADRs 0002 a 0004, com status "proposta" até haver evidência; ADR 0001 revisado. |
| AI Gateway | Serviço entre a aplicação e os providers: API única, nomes lógicos, credenciais, roteamento e, depois, retry, fallback e custo. | Serviço `gateway` (LiteLLM Proxy) no Passo 07. |
| Capacidade lógica | Nome da intenção de negócio pedida ao gateway, independente do modelo físico. | `ticket-classification` em vez de `gpt-fake-large`. |
| Fitness Function | Verificação objetiva, de preferência automatizada, de uma característica arquitetural. | FF1 a FF11 do plano: pytest, `git diff`, a ferramenta de métricas e `grep`. |
| Evolutionary Architecture | Arquitetura que suporta mudança guiada e incremental, protegida por fitness functions (Ford, Parsons, Kua). | v1 → v2 → `main`, cada marco medido com a mesma régua. |
| Context Engineering | Escolher e organizar o contexto que um agente recebe: o necessário e suficiente, sem ruído. | O handoff (§19) dá o código, o problema, o escopo, as restrições e os comandos de verificação. |
| Handoff | Entrega estruturada de uma tarefa a outro executor (pessoa ou agente). | Template §19.1 para o piloto F1. |
| Feedback determinístico | Sinal que não depende de opinião: o mesmo resultado para o mesmo código. | 32 testes, CSV de métricas, `git diff --exit-code`. |
| Human-in-the-loop | A pessoa revisa e decide nos pontos críticos. | Aceitar, revisar ou rejeitar o piloto é decisão humana (§20). |
| Piloto de refatoração | Aplicar a estratégia num único componente para validar a hipótese antes de escalar. | F1 `classification` no Passo 08. |
| Strangler Fig (substituição progressiva) | O novo cresce ao lado do antigo, que é removido quando fica sem uso. | `llm.py` convive com o adapter até a última feature migrar. |
| Rollback | Voltar a um estado conhecido e bom. | `git revert` do incremento; `v1-coupled` intocada; worktree `../helpdesk-v1`. |
| Goodhart | Quando uma medida vira meta, deixa de medir bem. | Importar `ports` só para baixar D seria motivo de recusa; o D das features piora de forma legítima. |
