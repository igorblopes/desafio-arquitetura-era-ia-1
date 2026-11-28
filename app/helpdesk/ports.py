from typing import Protocol


class LanguageModelError(Exception):
    """A capacidade não produziu texto. Independe do gateway e do provider.

    `reason` é um de: "timeout", "rate_limited", "unavailable", "rejected".
    """

    def __init__(self, capability: str, reason: str) -> None:
        super().__init__(f"{capability}: {reason}")
        self.capability = capability
        self.reason = reason


class LanguageModel(Protocol):
    def complete(self, capability: str, prompt: str) -> str:
        """Executa a capacidade lógica sobre o prompt e devolve o texto gerado.

        Levanta LanguageModelError quando não consegue.
        """
        ...
