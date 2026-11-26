from openai import OpenAI

from .. import config
from ..ports import LanguageModel


class GatewayLanguageModel(LanguageModel):
    """LanguageModel servido pelo AI Gateway (API compatível com OpenAI)."""

    def __init__(self) -> None:
        # max_retries=0: o gateway já faz as retentativas; o SDK não as multiplica.
        self._client = OpenAI(
            base_url=f"{config.GATEWAY_URL}/v1",
            api_key=config.GATEWAY_API_KEY,
            max_retries=0,
        )

    def complete(self, capability: str, prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=capability,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content
