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
            logger.warning("modelo indisponível: capacidade=%s motivo=%s erro=%s status=%s",
                           capability, reason, type(error).__name__,
                           getattr(error, "status_code", None))
            raise LanguageModelError(capability, reason) from error
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


def _reason(error: openai.APIError) -> str:
    """Traduz a exceção do SDK para o vocabulário do contrato."""
    if isinstance(error, openai.APITimeoutError):  # a app desistiu de esperar
        return "timeout"
    status = getattr(error, "status_code", None)
    if status in (408, 504):  # o gateway desistiu do provider
        return "timeout"
    if status == 429:
        return "rate_limited"
    if status is not None and 400 <= status < 500:  # configuração, credencial ou pedido
        return "rejected"
    return "unavailable"
