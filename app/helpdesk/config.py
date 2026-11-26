import os

# AI Gateway: endereço e chave própria do gateway, vindos do ambiente.
# Usados só pelo adapter do gateway; modelo, provider e limites ficam no gateway.
GATEWAY_URL = os.environ["GATEWAY_URL"]
GATEWAY_API_KEY = os.environ["GATEWAY_API_KEY"]

# Relatório de temas: arquivo de tickets e tamanho do lote por chamada.
TICKETS_FILE = "/data/tickets.jsonl"
TICKETS_PER_CALL = 150
