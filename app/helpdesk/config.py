import os

# AI Gateway: endereço e chave própria do gateway, vindos do ambiente.
# Usados só pelo adapter do gateway; modelo, provider, tentativas e backoff ficam no gateway.
GATEWAY_URL = os.environ["GATEWAY_URL"]
GATEWAY_API_KEY = os.environ["GATEWAY_API_KEY"]

# Limite de espera da app por chamada ao gateway, em segundos (ADR 0005). Cobre todas as
# tentativas e pausas do gateway e fica abaixo dos 30 s da borda. Na F3 vale por lote.
GATEWAY_CONNECT_TIMEOUT_SECONDS = 2.0
GATEWAY_DEADLINE_SECONDS = {
    "ticket-classification": 14.0,
    "order-extraction": 14.0,
    "topics-report": 14.0,
    "reply-suggestion": 25.0,
}

# Relatório de temas: arquivo de tickets e tamanho do lote por chamada.
TICKETS_FILE = "/data/tickets.jsonl"
TICKETS_PER_CALL = 150
