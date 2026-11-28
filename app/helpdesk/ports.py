from typing import Protocol


class LanguageModelError(Exception):
    """A capacidade não produziu texto. Independe do gateway e do provider.

    `reason` é um de:
    - "timeout", "rate_limited", "unavailable": falha do modelo, pode passar sozinha;
    - "rejected": pedido, credencial ou permissão recusados; precisa de correção;
    - "throttled": a política de consumo deste serviço limitou a frequência (governança);
    - "budget_exceeded": o orçamento de consumo deste serviço acabou (governança).

    `retry_after` (segundos), quando conhecido, diz quando vale tentar de novo.
    """

    def __init__(self, capability: str, reason: str, retry_after: int | None = None) -> None:
        super().__init__(f"{capability}: {reason}")
        self.capability = capability
        self.reason = reason
        self.retry_after = retry_after


class LanguageModel(Protocol):
    def complete(self, capability: str, prompt: str) -> str:
        """Executa a capacidade lógica sobre o prompt e devolve o texto gerado.

        Levanta LanguageModelError quando não consegue.
        """
        ...
