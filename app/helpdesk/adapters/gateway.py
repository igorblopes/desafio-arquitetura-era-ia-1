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
            response = self._client.chat.completions.create(
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
        return response.choices[0].message.content


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
