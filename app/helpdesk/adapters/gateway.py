import logging

import openai
from openai import OpenAI

from .. import config
from ..ports import LanguageModel, LanguageModelError

logger = logging.getLogger("uvicorn.error")


class GatewayLanguageModel(LanguageModel):
    """LanguageModel servido pelo AI Gateway (API compatível com OpenAI)."""

    def __init__(self) -> None:
        # max_retries=0: só o gateway retenta (gateway/config.yaml); o SDK não multiplica.
        self._client = OpenAI(
            base_url=f"{config.GATEWAY_URL}/v1",
            api_key=config.GATEWAY_API_KEY,
            max_retries=0,
        )

    def complete(self, capability: str, prompt: str) -> str:
        # Sem streaming o gateway só envia bytes no fim, então o timeout de leitura
        # limita a espera total desta chamada.
        timeout = openai.Timeout(config.GATEWAY_DEADLINE_SECONDS[capability],
                                 connect=config.GATEWAY_CONNECT_TIMEOUT_SECONDS)
        try:
            raw = self._client.chat.completions.with_raw_response.create(
                model=capability,
                messages=[{"role": "user", "content": prompt}],
                timeout=timeout,
            )
        except openai.APIError as error:
            reason = _reason(error)
            # Só o tipo do erro do gateway vai ao log: a mensagem pode trazer hash de chave.
            logger.warning("modelo indisponível: capacidade=%s motivo=%s erro=%s status=%s tipo=%s",
                           capability, reason, type(error).__name__,
                           getattr(error, "status_code", None), _error_type(error))
            raise LanguageModelError(capability, reason, _retry_after(error)) from error
        _log_fallback(capability, raw.headers)
        return raw.parse().choices[0].message.content


def _log_fallback(capability: str, headers) -> None:
    """Registra quando o gateway respondeu por um destino que não é o primário (ADR 0006).

    O destino é o nome do grupo que o gateway devolve; a app não interpreta nem conhece a
    cadeia, só deixa o rastro para auditoria.
    """
    fallbacks = headers.get("x-litellm-attempted-fallbacks", "0")
    if fallbacks not in ("", "0"):
        logger.warning("capacidade atendida por fallback: capacidade=%s destino=%s saltos=%s",
                       capability, headers.get("x-litellm-model-group"), fallbacks)


# Recusas de governança do gateway (LiteLLM v1.102.1, ADR 0010). Acontecem na autenticação
# ou no limitador, ANTES do roteamento: nenhum provider foi chamado e repetir não adianta.
# O 429 do limitador e o 429 de um provider que esgotou a cadeia de fallback chegam com o
# mesmo status e o mesmo `type` (throttling_error); só o início da mensagem os separa.
GATEWAY_BUDGET_TYPE = "budget_exceeded"
GATEWAY_THROTTLE_TYPE = "throttling_error"
GATEWAY_THROTTLE_PREFIX = "Rate limit exceeded for"


def _error_body(error: openai.APIError) -> dict:
    body = getattr(error, "body", None)
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        return body["error"]
    return body if isinstance(body, dict) else {}


def _error_type(error: openai.APIError) -> str | None:
    return _error_body(error).get("type")


def _retry_after(error: openai.APIError) -> int | None:
    response = getattr(error, "response", None)
    value = response.headers.get("retry-after") if response is not None else None
    return int(value) if value and value.isdigit() else None


def _reason(error: openai.APIError) -> str:
    """Traduz a exceção do SDK para o vocabulário do contrato."""
    if isinstance(error, openai.APITimeoutError):  # a app desistiu de esperar
        return "timeout"
    status = getattr(error, "status_code", None)
    if status in (408, 504):  # o gateway desistiu do provider
        return "timeout"
    if status == 429:
        kind = _error_type(error)
        if kind == GATEWAY_BUDGET_TYPE:
            return "budget_exceeded"
        message = str(_error_body(error).get("message", ""))
        if kind == GATEWAY_THROTTLE_TYPE and message.startswith(GATEWAY_THROTTLE_PREFIX):
            return "throttled"
        return "rate_limited"  # 429 do provider depois de esgotar retry e fallback
    if status is not None and 400 <= status < 500:  # configuração, credencial ou pedido
        return "rejected"
    return "unavailable"
