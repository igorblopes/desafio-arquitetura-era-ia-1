# Glossário do Passo 08: piloto da F1

Cada conceito traz a definição curta e onde ele apareceu de verdade neste piloto. As evidências citadas estão em `docs/piloto/evidencias/`.

| Conceito | Definição | Onde apareceu no piloto |
|---|---|---|
| Piloto arquitetural | aplicar a estratégia escolhida a uma parte real e limitada do sistema, para validá-la antes de escalar | só a F1 migrou de verdade, com código, testes e medição reais; F2, F3 e F4 ficaram intocadas como grupo de controle (a F4 respondeu 200 com o gateway parado) |
| Proof of Concept | demonstração de viabilidade de uma ideia, em geral fora do produto | o Passo 07 (gateway com um cliente de teste); o piloto já é a ideia dentro da aplicação real |
| Technical Spike | investigação curta e descartável para reduzir uma incerteza técnica específica | conferir que o SDK `openai==3.19.0` aceita `max_retries=0` e que um adapter sem ele gera 3 requisições (mutante da verificação própria) |
| Hipótese arquitetural | afirmação verificável sobre o efeito de uma mudança estrutural, com critério de invalidação | "a F1 deixa de conhecer provider, modelo e SDK sem mudar comportamento"; seis sub-hipóteses, cada uma com mecanismo e condição de invalidação (relatório, seção 5) |
| Feedback Loop | ciclo curto entre mudança e verificação objetiva, que orienta o passo seguinte | proposta → revisão → implementação → 32 testes → métricas → verificação do arquiteto; três ciclos registrados |
| Context Engineering | escolher o contexto mínimo suficiente para o agente fazer a tarefa certa | o handoff deu problema, contrato já decidido, 5 arquivos autorizados, proibições, metas por componente e comandos; nada da conversa com o arquiteto |
| Handoff | instrução independente que transfere uma tarefa a outro executor, com tudo o que ele precisa | `docs/piloto/handoff-f1.md`, em duas fases, entregue a uma sessão separada na máquina do Igor |
| Agent Evaluation | avaliar o trabalho do agente com critérios definidos antes e evidências que ele não controla | matriz da seção 11 do relatório: hashes do diff, testes rodados de novo, métricas recalculadas, verificação escrita pelo arquiteto, experimentos pela borda |
| Human-in-the-loop | decisões em pontos definidos ficam com uma pessoa | duas portas de aprovação (proposta e entrega); o commit fica com o Igor |
| Feedback determinístico | sinal que dá sempre o mesmo resultado para o mesmo código | `32 passed`; `pilot-after.csv` idêntico em três execuções; `grep` vazio; `verificacao_f1.py` com `RESULTADO: OK` |
| Dependency Inversion Principle | módulos de política não dependem de detalhes; ambos dependem de abstrações | `classification → ports ← adapters.gateway`; a aresta `classification → llm` sumiu do grafo |
| Dependency Injection | o objeto recebe as dependências de fora, em vez de criá-las | `classify(ticket, model: LanguageModel)`: a F1 recebe o modelo por parâmetro |
| Composition Root | único lugar onde os objetos concretos são criados e ligados | `main.py`: `language_model = GatewayLanguageModel()`, uma vez, passada à rota da F1; só ele importa o adapter |
| Protocol | tipo do `typing` que descreve operações esperadas, sem exigir herança | `ports.LanguageModel` com `complete(capability, prompt) -> str`; A=1 na régua porque herda de `Protocol` |
| Structural Typing | compatibilidade decidida pela forma (métodos e assinaturas), não pela declaração | o gateway simulado da verificação e qualquer dublê com `complete` servem à F1; o `mypy` aceitou o adapter e recusou uma assinatura errada |
| Adapter | componente que traduz um contrato interno para uma tecnologia externa | `GatewayLanguageModel`: transforma `complete` em `POST /v1/chat/completions` com `model=capability`; único arquivo novo com SDK |
| Ports and Adapters | a aplicação define portas (contratos) e a tecnologia fica em adapters plugados na borda | `ports.py` + `adapters/gateway.py`, sem camadas extras; a troca para Anthropic passou pelo mesmo adapter sem mudar a F1 |
| Architectural Fitness Function | verificação objetiva de uma característica arquitetural | FF1 a FF11 do plano; a FF6 se mostrou cega aos imports relativos e foi corrigida; a FF12 (`mypy`) foi proposta |
| Regressão | mudança de comportamento que antes funcionava | nenhuma na suíte. Três diferenças fora dela foram registradas: falha em 4,6 s (antes 1,25 s), gateway como dependência e 1 tentativa de conexão |
| Rollback | volta a um estado conhecido | base limpa `6efadeb`; `git restore` + remoção dos 3 arquivos novos; depois do commit, `git revert` |
| Goodhart's Law | quando uma medida vira alvo, deixa de ser uma boa medida | sem a anotação ou sem a herança, o código funcionaria igual e D pioraria para 0,50; as setas foram aceitas porque têm função fora da métrica |
| Evolução incremental | passos pequenos, verificáveis e reversíveis | infraestrutura (arquiteto) e código da F1 (agente) em incrementos separados, cada um com 32 testes; F2 a F4 esperam o próximo passo |
