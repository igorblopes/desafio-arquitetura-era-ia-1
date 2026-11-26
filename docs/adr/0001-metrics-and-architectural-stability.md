# 0001. Medir o acoplamento com uma ferramenta estática própria, aplicada a cada checkout

- Status: aceita
- Data: 2026-11-25
- Nível: software

## Contexto

O desafio exige medir Ca, Ce, I, A e D dos componentes de `app/helpdesk/` em três estados (`v1-coupled`, `v2-decoupled` e `main`), com CSV `component,ca,ce,i,a,d` e o gráfico da Main Sequence. A **régua é dada pelo enunciado** e não é decisão deste ADR:

| Item | Regra |
|---|---|
| Componente | cada `.py` sob `app/helpdesk/`, recursivo, exceto `__init__.py`; nome com pontos |
| Dependência | import absoluto ou relativo que resolve para outro componente; só internas, sem duplicatas, sem transitivas |
| Ca / Ce | componentes distintos que importam / são importados |
| I | Ce / (Ca + Ce), ou 0 se ambos forem 0 |
| A | abstratas / total de classes, ou 0 sem classes; abstrata = herda de `typing.Protocol` ou `abc.ABC` |
| D | \|A + I − 1\| |
| Zona de dor | A < 0,5 e I < 0,5 e D ≥ 0,5 |
| Saída | 2 casas decimais; `metrics/results/<nome>.csv` e `.png` |

**Problema:** precisamos de um instrumento confiável, reproduzível e igual para as três versões, capaz de demonstrar o acoplamento da v1 e servir de critério objetivo (não único) para aceitar ou recusar as refatorações feitas por agentes.

Baseline medida (v1, commit `8028305`): `config` (Ca=6, D=1,00), `llm` (Ca=4, I=0,20, D=0,80) e `schemas` (Ca=5, D=1,00) na zona de dor; A = 0 em todos os 9 componentes.

## Opções consideradas

1. **Ferramenta própria com `ast` da biblioteca padrão**, executada da `main` sobre qualquer checkout (`--source`).
2. Ferramenta pronta (por exemplo, `pydeps`, `import-linter`, plugins de IDE).
3. Análise dinâmica: importar os módulos e inspecionar `sys.modules`/`inspect`.
4. Expressões regulares sobre o texto dos arquivos.

## Decisão

Opção 1.

- **Estática (AST):** não executa o código analisado. Importar a v1 executaria `config.py` (que exige `FAKE_OPENAI_KEY`) e `llm.py` (que instancia clientes de SDK); a análise dinâmica (3) depende de ambiente e ainda mede o que foi importado em runtime, não o que está declarado.
- **Própria:** as ferramentas prontas (2) usam outras definições de componente, contam externos ou pacotes, e não calculam A pela régua (`Protocol`/`ABC` por origem). Adaptá-las custaria mais que ~400 linhas legíveis e testadas.
- **Regex (4)** erra com imports em várias linhas, aliases, `import a, b` e texto em strings.
- **Implementação:** módulos separados (descoberta, parsing, resolução, abstração, cálculo, relatório), só biblioteca padrão na análise; `matplotlib==3.11.2` fixado apenas para o PNG. Cálculo com `Fraction` e arredondamento final `ROUND_HALF_UP`, sem arredondamento intermediário.
- **Fora da tag:** a ferramenta vive na `main` e mede a tag por `git worktree`. A `v1-coupled` permanece o código original.

Interpretações onde o enunciado é omisso (detalhes em `docs/metricas/fundamentacao.md` §6), nenhuma das quais altera a medição da v1:

- import absoluto é interno quando começa pelo pacote raiz (nome do diretório analisado);
- símbolo reexportado por `__init__.py` gera aresta para o módulo de origem;
- imports dentro de funções, `if TYPE_CHECKING` e `try` contam;
- abstração só por herança **direta**, com a origem do nome verificada (aliases, `typing.Protocol`, `Protocol[T]`); herança indireta, `ABCMeta`, `typing_extensions` não contam;
- todas as classes (inclusive aninhadas) entram no total;
- a zona de dor é avaliada sobre os valores publicados (2 casas), e a ferramenta avisa quando o valor exato classificaria diferente.

### Interpretação da Main Sequence

D próximo de 0 indica equilíbrio entre estabilidade e abstração. D alto exige **investigação**, não conclusão: DTOs, constantes e módulos isolados podem ficar na zona de dor sem rigidez real. Nenhuma mudança será feita só para reduzir D.

### Exceções

| Componente | Situação | Justificativa |
|---|---|---|
| `schemas` | **candidata** | DTOs Pydantic do contrato HTTP, sem lógica nem dependência interna; mudam só quando o contrato muda, e a caracterização trava o contrato |
| `config` | não é candidata | guarda modelo físico e URL de provider, que são voláteis (Dor 4) |
| `llm`, futuro componente de comunicação com o gateway e as features | **proibidos** como exceção | regra do desafio |

As exceções definitivas serão revisadas sobre a arquitetura final (Passo 16).

## Consequências

- (+) Mesma ferramenta e mesma régua para as três medições; o CSV da v1 é reproduzível byte a byte.
- (+) Cada responsabilidade tem teste próprio (`tests/metrics/`, 64 testes), com módulos artificiais.
- (+) A baseline expõe o problema central: as features dependem de um detalhe tecnológico concreto (`llm`, `config`).
- (−) Mantemos código de ferramenta próprio; qualquer correção precisa preservar a régua e reproduzir o `v1-coupled.csv` versionado.
- (−) A régua não vê SDKs, acoplamento semântico, runtime, HTTP, coesão nem frequência de mudança (ver relatório, §6). Isso exige leitura crítica a cada medição.
- Vigiar: Goodhart. Protocols sem uso, imports artificiais, fragmentação de módulos e responsabilidades movidas sem ganho real são motivos de recusa de uma refatoração.

### Critérios de uso durante a refatoração

1. Medir antes e depois de cada tarefa do agente, com o mesmo comando e `--name` diferente.
2. Aceitar só com a caracterização verde **e** com uma melhora explicável pelo código (por exemplo, features passando a depender de um contrato com A = 1).
3. Comparar componente a componente; examinar qualquer componente novo na zona de dor e qualquer abstração nova com Ca = 0.
4. Não alterar a régua para acomodar um resultado.

## Evidência

```bash
git worktree add --detach ../helpdesk-v1 v1-coupled
python metrics/measure.py --source ../helpdesk-v1/app/helpdesk --name v1-coupled
python -m pytest tests/metrics -q
```

`metrics/results/v1-coupled.csv` versionado; uma segunda execução produz bytes idênticos.

## Revisão no Passo 06 (planejamento da refatoração)

A régua não muda. Esta revisão confere se os critérios do `docs/refactoring-plan.md` são compatíveis com a interpretação deste ADR e registra o que a simulação de métricas antecipou. Os valores são **projetados**: foram calculados com esta ferramenta sobre um esqueleto de imports. Não são medições da v2.

- **Compatibilidade.** Os critérios do plano usam a métrica sempre junto com os testes de caracterização e a revisão do diff, como manda a seção "Critérios de uso durante a refatoração".
  - Nenhuma meta é percentual ou uniforme.
  - Cada meta deriva do problema medido no componente.
- **`config`.** Na v2 ele perde os modelos físicos, as URLs e as chaves de provider. Mesmo assim, a projeção indica Ca=3 e D=1,00, ou seja, continua na zona de dor.
  - A razão pela qual ele foi recusado como exceção (conteúdo volátil) deixa de existir.
  - A decisão fica para a `main` final (Passo 16), com a medição real: declará-lo naturalmente estável por revisão deste ADR, ou dissolvê-lo se isso aumentar a coesão.
  - Nada muda na v2.
- **Componentes novos.**
  - `ports` (o `Protocol` de IA) é projetado com A=1, I=0, D=0.
  - `adapters.gateway` é o componente de comunicação com o gateway, que **não pode** ser exceção. Ele é projetado com Ca=1, Ce=2 e D=0,33.
  - A simulação mostrou que um adapter sem nenhum import interno teria D=1,00, ou seja, estaria na zona de dor. Por isso, o desenho do adapter será revisado no piloto, e qualquer import acrescentado só para escapar da zona de dor é motivo de recusa.
- **Features.** O D projetado sobe de 0,25 para 0,33, porque elas passam a ter menos dependências. É uma piora esperada e aceita, não um defeito.
- **Status:** a decisão deste ADR continua aceita. As exceções seguem como na tabela acima.

## Revisão no Passo 08 (piloto da F1)

A régua não mudou: `git diff 13fc247 -- metrics/*.py tests/metrics/` está vazio, e `tests/metrics` passa com `64 passed`. Ela foi usada como este ADR manda: mesmo comando antes e depois, nomes diferentes (`pilot-before`, `pilot-after`), sempre junto com a caracterização e a revisão do diff.

- **Reprodutibilidade.**
  - `pilot-before.csv` é idêntico a `v1-coupled.csv`.
  - `pilot-after.csv` deu o mesmo resultado em três execuções independentes: a do agente, a da verificação e a do arquiteto.
  - Ele coincide componente a componente com a projeção do Passo 06: 22 arestas; `ports` 2/0/0/1/0; `adapters.gateway` 1/2/0,67/0/0,33.
- **O adapter fora da zona de dor sem import artificial.** A preocupação do Passo 06 era que um adapter sem import interno teria D=1,00. O adapter aprovado tem dois imports internos, ambos com função:
  - `config`, de onde lê endereço e chave;
  - `ports`, de quem herda para que o `mypy` recuse uma assinatura incompatível, como demonstrado no piloto.
- **Goodhart, medido.** Duas variações hipotéticas, não aplicadas, mostram que a régua mede dependências **declaradas**:
  - sem a anotação do contrato na F1, ou sem a herança no adapter, o comportamento é idêntico;
  - nos dois casos, Ce cai para 1 e D sobe para 0,50.
  - O critério 2 deste ADR (melhora explicável pelo código) foi o que permitiu aceitar as duas setas: elas têm razão de existir sem a métrica.
- **Limites confirmados.** A régua não viu nenhum dos problemas reais do piloto:
  - o gateway como dependência em execução;
  - o retry que mudou de dono;
  - a FF6 cega aos imports relativos.
  - Por isso o plano 1.1 acrescentou verificações fora da régua, sem mexer nela.
- **Status:** continua aceita, sem mudança na decisão.
