"""Responsabilidade 2: ler e fazer o parsing dos arquivos (AST).

Só extrai fatos sintáticos: os imports declarados (em qualquer lugar do
arquivo, inclusive dentro de funções, classes, if/try) e as classes com as
suas bases. Não resolve nada e não executa nada.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


class AnalysisError(Exception):
    """Arquivo que não pôde ser lido ou analisado. A medição é abortada."""


@dataclass(frozen=True)
class ImportRef:
    """Um import como escrito no código.

    kind="import": `import a.b as c` -> module="a.b", names=(), level=0
    kind="from":   `from ..a import b, c` -> module="a", names=("b","c"), level=2
    """
    kind: str
    module: str | None
    names: tuple[str, ...] = ()
    level: int = 0
    lineno: int = 0


def read_tree(path: Path) -> ast.Module:
    try:
        source = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise AnalysisError(f"Não foi possível ler {path}: {exc}") from exc
    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise AnalysisError(f"Erro de sintaxe em {path}:{exc.lineno}: {exc.msg}") from exc


def extract_imports(tree: ast.Module) -> list[ImportRef]:
    refs = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                refs.append(ImportRef("import", alias.name, (), 0, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            names = tuple(alias.name for alias in node.names)
            refs.append(ImportRef("from", node.module, names, node.level, node.lineno))
    return sorted(refs, key=lambda r: (r.lineno, r.kind, r.module or "", r.names))
