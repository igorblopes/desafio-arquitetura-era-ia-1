import os

# AI Gateway: endereço e chave VIRTUAL de consumo do helpdesk (helpdesk-app, ADR 0010),
# vindos do ambiente. Não é a master key: só consome as 4 capacidades, com orçamento e RPM.
# Usados só pelo adapter do gateway; modelo, provider, tentativas e backoff ficam no gateway.
GATEWAY_URL = os.environ["GATEWAY_URL"]
GATEWAY_API_KEY = os.environ["GATEWAY_API_KEY"]

# Limite de espera da app por chamada ao gateway, em segundos (ADR 0005, revisado no ADR
# 0006). É o deadline GLOBAL da cadeia inteira (primário, retry e fallback): uma só chamada
# HTTP, então trocar de destino no gateway não reinicia o prazo. Fica abaixo dos 30 s da
# borda. Na F3 vale por lote: 25 s cabem "primário travado (12 s) + equivalente (~10 s)".
GATEWAY_CONNECT_TIMEOUT_SECONDS = 2.0
GATEWAY_DEADLINE_SECONDS = {
    "ticket-classification": 14.0,
    "order-extraction": 14.0,
    "topics-report": 25.0,
    "reply-suggestion": 25.0,
}

# Relatório de temas: arquivo de tickets e tamanho do lote por chamada.
TICKETS_FILE = "/data/tickets.jsonl"
TICKETS_PER_CALL = 150
