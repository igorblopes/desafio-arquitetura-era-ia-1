from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import classification, extraction, report, suggestion
from .adapters.gateway import GatewayLanguageModel
from .ports import LanguageModelError
from .schemas import (Classification, OrderData, PeriodInput, ReplySuggestion, TicketInput,
                      TopicsReport)

# Composition Root: uma única instância do adapter, criada no carregamento do módulo.
language_model = GatewayLanguageModel()

app = FastAPI(title="Helpdesk")


# Status e mensagem por motivo (ADR 0005). 503: vale tentar mais tarde. 502: precisa de
# correção. O 504 fica só para a borda, para não confundir as duas origens.
MODEL_ERRORS = {
    "timeout": (503, "O modelo não respondeu dentro do prazo."),
    "rate_limited": (503, "O modelo está limitando requisições."),
    "unavailable": (503, "O modelo está indisponível."),
    "rejected": (502, "A requisição ao modelo foi recusada."),
}


@app.exception_handler(LanguageModelError)
def model_error(request: Request, error: LanguageModelError) -> JSONResponse:
    status, detail = MODEL_ERRORS[error.reason]
    return JSONResponse(status_code=status,
                        content={"detail": detail, "code": f"model_{error.reason}"})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/tickets/classification")
def classify_ticket(ticket: TicketInput) -> Classification:
    return classification.classify(ticket, language_model)


@app.post("/tickets/reply-suggestion")
def suggest_reply(ticket: TicketInput) -> ReplySuggestion:
    return suggestion.suggest(ticket, language_model)


@app.post("/tickets/extraction")
def extract_order_data(ticket: TicketInput) -> OrderData:
    return extraction.extract(ticket, language_model)


@app.post("/reports/topics")
def topics_report(period: PeriodInput) -> TopicsReport:
    return report.topics(period, language_model)
