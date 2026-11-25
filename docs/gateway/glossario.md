# Glossário do Passo 07 (AI Gateway)

| Conceito | Significado | No projeto |
|---|---|---|
| AI Gateway | Serviço entre a aplicação e os providers de modelos. Oferece uma API única, nomes lógicos, credenciais centralizadas e políticas (retry, fallback, custo, limites). | Serviço `gateway` (LiteLLM Proxy) na porta 4000. |
| API Gateway | Entrada de APIs para clientes: roteamento por rota, autenticação, cotas. | Não existe no projeto. O `edge` faz só o papel de borda. |
| Reverse Proxy | Repassa HTTP a um upstream sem interpretar o conteúdo. | `edge` (nginx), com `proxy_read_timeout 30s`. |
| Load Balancer | Distribui requisições entre instâncias equivalentes de um serviço. | Não há. Cada serviço tem uma instância. |
| LiteLLM Proxy | AI Gateway open source, configurado por YAML, com API compatível com a OpenAI. | `ghcr.io/berriai/litellm:v1.102.1` + `gateway/config.yaml`. |
| Provider | Fornecedor de modelos, com API e credenciais próprias. | `openai` e `anthropic` simulados pelo `provider-fake`. |
| Modelo físico | O modelo que de fato executa. | `gpt-fake-large`, `claude-fake-large`. |
| Capacidade lógica | Nome da intenção de negócio pedida ao gateway. | `ticket-classification`, `reply-suggestion`, `topics-report`, `order-extraction`. |
| Model Routing | Escolha, a cada requisição, do destino que atende um nome lógico. | `ticket-classification` → `openai/gpt-fake-large`. |
| Model Group | Conjunto de deployments com o mesmo `model_name`, entre os quais o LiteLLM roteia. Base para fallback e balanceamento. | Cada capacidade é um group de um deployment. Os erros citam `Received Model Group=...`. |
| Normalização de interfaces | Expor formatos diferentes como um formato só. | Destinos Anthropic também respondem em `choices[0].message.content` e `finish_reason: stop`. |
| API Key | Credencial que identifica quem chama. | `Authorization: Bearer` no gateway; `x-api-key` no Anthropic nativo. |
| Master Key | Chave administrativa do LiteLLM, com acesso total. | `GATEWAY_MASTER_KEY`. É provisória como chave de consumo. |
| Virtual Key | Chave por consumidor, com orçamento e limites, guardada em banco. | Passo 12. Sem banco, outra chave recebe 400 `No connected db.` |
| Service Discovery | Encontrar um serviço pelo nome, não pelo IP. | `provider-fake` e `gateway` resolvidos pelo DNS do Compose. |
| Docker Network | Rede virtual que liga containers. | `desafio-arquitetura-era-ia-1_default` (bridge). |
| DNS interno | Resolução de nomes de serviço dentro da rede do Compose. | `http://provider-fake:8090` só funciona dentro dos containers. |
| Port Mapping | Publicar uma porta do container no host. | `4000:4000`, `8090:8090`, `8000:80`. |
| Bind Mount | Montar um arquivo ou pasta do host no container. | `./gateway/config.yaml:/app/config.yaml:ro`. |
| Healthcheck | Comando que o Docker usa para saber se o serviço está pronto. | `GET /health/readiness` no gateway. |
| Startup Readiness | Diferença entre processo iniciado e serviço pronto para atender. | `--wait` só retorna quando todos estão `healthy`. A primeira chamada após um restart ainda leva 1,3 a 1,7 s. |
| Configuration Management | Manter configuração versionada, separada do código e dos segredos. | `config.yaml` versionado com `os.environ/...`; valores no `.env`, que não é versionado. |
| Vendor Lock-in | Dependência difícil de desfazer de um fornecedor. | O gateway reduz o lock-in a providers, mas cria dependência do LiteLLM. |
| Overhead de rede | Tempo extra de um salto intermediário. | +6 ms nas medianas. |
| Server-Sent Events | Respostas HTTP em eventos `data:` enviados aos poucos. | O gateway entrega `chat.completion.chunk` e termina com `[DONE]`. Primeiro conteúdo em 0,82 s. |
| Centralização de políticas | Um único lugar para retry, fallback, limites e custo. | Observado: o retry padrão (2) já está lá. Os demais entram nos Passos 10 a 12. |
