"""Responsabilidade 1: descobrir os componentes.

Componente = cada arquivo .py dentro do diretório analisado (recursivo),
exceto __init__.py. O identificador é o caminho relativo com pontos:
adapters/gateway.py -> "adapters.gateway".
"""

from __future__ import annotations

from pathlib import Path


def component_id(source: Path, file: Path) -> str:
    """Converte o caminho de um módulo no identificador com pontos."""
    relative = file.relative_to(source).with_suffix("")
    return ".".join(relative.parts)


def discover_components(source: Path) -> dict[str, Path]:
    """Mapa {componente: arquivo}, em ordem alfabética (determinística)."""
    source = Path(source)
    if not source.is_dir():
        raise NotADirectoryError(f"Diretório de código não encontrado: {source}")
    found = {}
    for file in source.rglob("*.py"):
        if file.name == "__init__.py" or not file.is_file():
            continue
        found[component_id(source, file)] = file
    return dict(sorted(found.items()))


def is_package_dir(source: Path, dotted: str) -> bool:
    """O nome interno (relativo ao diretório analisado) é um diretório?"""
    path = Path(source).joinpath(*dotted.split(".")) if dotted else Path(source)
    return path.is_dir()
