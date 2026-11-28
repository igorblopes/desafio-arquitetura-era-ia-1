import json

from fastapi import HTTPException

from .ports import LanguageModel
from .schemas import Classification, TicketInput

CAPABILITY = "ticket-classification"

CATEGORIES = {"delivery", "payment", "exchange_return", "product_defect", "other"}
PRIORITIES = {"low", "medium", "high"}


def classify(ticket: TicketInput, model: LanguageModel) -> Classification:
    text = model.complete(CAPABILITY, f"TASK: classify\n{ticket.text}")
    data = _json_object(text)
    category, priority = data.get("category"), data.get("priority")
    # isinstance antes do `in`: uma lista no lugar da string não pode virar erro 500.
    if not (isinstance(category, str) and category in CATEGORIES
            and isinstance(priority, str) and priority in PRIORITIES):
        raise HTTPException(status_code=502, detail="Classificação fora dos valores permitidos")
    # Campos explícitos: o ticket_id é sempre o da requisição, nunca um que o modelo devolva.
    return Classification(ticket_id=ticket.ticket_id, category=category, priority=priority)


def _json_object(text: str | None) -> dict:
    """Saída do modelo como objeto JSON; fora disso é resposta inválida do upstream (502)."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        data = None
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Resposta do modelo fora do formato esperado")
    return data
