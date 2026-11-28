import json
import re

from fastapi import HTTPException

from .ports import LanguageModel
from .schemas import OrderData, TicketInput

CAPABILITY = "order-extraction"

# '#' e exatamente seis dígitos ASCII, nada antes nem depois (usado com fullmatch).
ORDER_FORMAT = re.compile(r"#[0-9]{6}")


def extract(ticket: TicketInput, model: LanguageModel) -> OrderData:
    text = model.complete(CAPABILITY, f"TASK: extract\n{ticket.text}")
    data = _json_object(text)
    # Os dois campos precisam vir na resposta, mesmo nulos: `null` é "o modelo procurou e
    # não achou". Campo ausente é saída fora do contrato e não pode virar um null fictício
    # numa automação sem revisão humana.
    if "order_number" not in data or "product" not in data:
        raise HTTPException(status_code=502, detail="Extração incompleta")
    order_number, product = data["order_number"], data["product"]
    if order_number is not None and not (isinstance(order_number, str)
                                         and ORDER_FORMAT.fullmatch(order_number)):
        raise HTTPException(status_code=502, detail="Número de pedido em formato inválido")
    if product is not None and not isinstance(product, str):
        raise HTTPException(status_code=502, detail="Produto em formato inválido")
    return OrderData(ticket_id=ticket.ticket_id, order_number=order_number, product=product)


def _json_object(text: str | None) -> dict:
    """Saída do modelo como objeto JSON; fora disso é resposta inválida do upstream (502)."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        data = None
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Resposta do modelo fora do formato esperado")
    return data
