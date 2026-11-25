"""Responsabilidade 5: identificar classes abstratas (régua do desafio).

Abstrata = classe que herda DIRETAMENTE de `typing.Protocol` ou `abc.ABC`,
identificadas pela origem do nome (imports, aliases, referências
qualificadas e Protocol[T]). Um `Protocol`/`ABC` definido localmente ou
vindo de outro módulo não conta. Pydantic, ABCMeta via metaclass,
typing_extensions e herança indireta NÃO ampliam a régua.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

ABSTRACT_ROOTS = {("typing", "Protocol"), ("abc", "ABC")}
ROOT_MODULES = {"typing", "abc"}


@dataclass(frozen=True)
class ClassInfo:
    name: str
    lineno: int
    abstract: bool


class _Bindings:
    """Nomes visíveis no módulo: símbolo abstrato ou módulo typing/abc."""

    def __init__(self):
        self.symbols: dict[str, tuple[str, str] | None] = {}
        self.modules: dict[str, str | None] = {}

    def learn_import(self, node: ast.AST) -> None:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    self.modules[alias.asname] = alias.name if alias.name in ROOT_MODULES else None
                    self.symbols.pop(alias.asname, None)
                else:
                    top = alias.name.split(".")[0]
                    self.modules[top] = top if top in ROOT_MODULES else None
                    self.symbols.pop(top, None)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            for alias in node.names:
                bound = alias.asname or alias.name
                origin = (node.module, alias.name)
                self.symbols[bound] = origin if origin in ABSTRACT_ROOTS else None
                self.modules.pop(bound, None)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound = alias.asname or alias.name
                self.symbols[bound] = None
                self.modules.pop(bound, None)

    def shadow(self, name: str) -> None:
        self.symbols[name] = None
        self.modules.pop(name, None)

    def is_abstract_base(self, base: ast.expr) -> bool:
        if isinstance(base, ast.Subscript):          # Protocol[T]
            base = base.value
        if isinstance(base, ast.Name):
            return self.symbols.get(base.id) is not None
        if isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name):
            module = self.modules.get(base.value.id)
            return module is not None and (module, base.attr) in ABSTRACT_ROOTS
        return False


def _bound_names(stmt: ast.stmt) -> list[str]:
    if isinstance(stmt, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        return [stmt.name]
    targets = []
    if isinstance(stmt, ast.Assign):
        targets = stmt.targets
    elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
        targets = [stmt.target]
    return [n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)]


def analyze_classes(tree: ast.Module) -> list[ClassInfo]:
    """Todas as classes do módulo (inclusive aninhadas), em ordem de linha."""
    bindings = _Bindings()
    classes: list[ClassInfo] = []
    for stmt in tree.body:
        for node in ast.walk(stmt):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                bindings.learn_import(node)
        for node in ast.walk(stmt):
            if isinstance(node, ast.ClassDef):
                abstract = any(bindings.is_abstract_base(b) for b in node.bases)
                classes.append(ClassInfo(node.name, node.lineno, abstract))
        for name in _bound_names(stmt):
            bindings.shadow(name)
    return sorted(classes, key=lambda c: (c.lineno, c.name))
