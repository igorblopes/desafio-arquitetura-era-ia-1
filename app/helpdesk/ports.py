from typing import Protocol


class LanguageModel(Protocol):
    def complete(self, capability: str, prompt: str) -> str:
        """Executa a capacidade lógica sobre o prompt e devolve o texto gerado."""
        ...
