"""Responsabilidade 3 e 4: resolver imports internos e montar o grafo.

Um import vira dependência quando resolve para OUTRO componente existente.
Externos e biblioteca padrão não resolvem para componente e são ignorados.

Regras de resolução (documentadas no ADR da métrica):
- Interno = nome absoluto que começa pelo pacote raiz (o nome do diretório
  analisado, ex. "helpdesk") ou import relativo.
- `import helpdesk.config [as x]`      -> config
- `from helpdesk import config`        -> config (submódulo)
- `from helpdesk.config import X`      -> config (símbolo; nunca "config.X")
- `from . import config` / `from .config import X` -> relativo ao pacote do módulo
- `from helpdesk.pkg import X`, X reexportado no pkg/__init__.py via
  `from .mod import X` -> pkg.mod (o __init__ não vira componente)
- Autorreferência é descartada; duplicatas viram uma aresta só (set).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from metrics.discovery import is_package_dir
from metrics.parsing import ImportRef, extract_imports, read_tree


@dataclass
class Graph:
    nodes: list[str]
    out_edges: dict[str, set[str]]
    in_edges: dict[str, set[str]]
    unresolved: list[str] = field(default_factory=list)

    @property
    def edges(self) -> list[tuple[str, str]]:
        return sorted((a, b) for a, targets in self.out_edges.items() for b in targets)


class Resolver:
    def __init__(self, source: Path, components: dict[str, Path], root_package: str):
        self.source = Path(source)
        self.components = components
        self.root = root_package
        self.unresolved: list[str] = []
        self._reexports: dict[str, dict[str, str]] = {}

    # ---------- nomes ----------
    def internal_name(self, absolute: str) -> str | None:
        """'helpdesk.adapters.x' -> 'adapters.x'; 'helpdesk' -> ''; externo -> None."""
        if absolute == self.root:
            return ""
        if absolute.startswith(self.root + "."):
            return absolute[len(self.root) + 1:]
        return None

    def relative_base(self, origin: str, level: int, module: str | None) -> str | None:
        """Nome interno da base de um import relativo, ou None se sair da árvore."""
        package_parts = origin.split(".")[:-1]
        up = level - 1
        if up > len(package_parts):
            return None
        base = package_parts[: len(package_parts) - up]
        if module:
            base = base + module.split(".")
        return ".".join(base)

    @staticmethod
    def join(base: str, name: str) -> str:
        return f"{base}.{name}" if base else name

    # ---------- reexportação em __init__.py ----------
    def reexports(self, package: str) -> dict[str, str]:
        """{símbolo: componente} reexportados pelo __init__.py do pacote."""
        if package in self._reexports:
            return self._reexports[package]
        mapping: dict[str, str] = {}
        init = (self.source.joinpath(*package.split(".")) if package else self.source) / "__init__.py"
        if init.is_file():
            tree = read_tree(init)
            origin = self.join(package, "__init__")
            for node in tree.body:
                if not isinstance(node, ast.ImportFrom):
                    continue
                if node.level:
                    base = self.relative_base(origin, node.level, node.module)
                else:
                    base = self.internal_name(node.module or "")
                if base is None:
                    continue
                for alias in node.names:
                    exported = alias.asname or alias.name
                    sub = self.join(base, alias.name)
                    if sub in self.components:
                        mapping[exported] = sub
                    elif base in self.components:
                        mapping[exported] = base
        self._reexports[package] = mapping
        return mapping

    # ---------- resolução ----------
    def resolve(self, origin: str, ref: ImportRef) -> set[str]:
        targets: set[str] = set()
        if ref.kind == "import":
            name = self.internal_name(ref.module or "")
            if name is None:
                return targets  # externo / biblioteca padrão
            if name in self.components:
                targets.add(name)
            elif not is_package_dir(self.source, name):
                self.unresolved.append(f"{origin}:{ref.lineno} import {ref.module}")
        else:
            if ref.level:
                base = self.relative_base(origin, ref.level, ref.module)
                if base is None:
                    self.unresolved.append(f"{origin}:{ref.lineno} import relativo fora da árvore")
                    return targets
            else:
                base = self.internal_name(ref.module or "")
                if base is None:
                    return targets  # externo / biblioteca padrão
            for name in ref.names:
                sub = self.join(base, name) if name != "*" else None
                if sub and sub in self.components:
                    targets.add(sub)                    # submódulo
                elif base in self.components:
                    targets.add(base)                   # símbolo do módulo
                elif is_package_dir(self.source, base):
                    found = self.reexports(base).get(name)
                    if found:
                        targets.add(found)              # símbolo reexportado
                    else:
                        self.unresolved.append(
                            f"{origin}:{ref.lineno} from {'.' * ref.level}{ref.module or ''} import {name}")
                else:
                    self.unresolved.append(
                        f"{origin}:{ref.lineno} from {'.' * ref.level}{ref.module or ''} import {name}")
        targets.discard(origin)  # autorreferência não é dependência
        return targets


def build_graph(source: Path, components: dict[str, Path], root_package: str,
                trees: dict[str, ast.Module] | None = None) -> Graph:
    resolver = Resolver(source, components, root_package)
    out_edges: dict[str, set[str]] = {c: set() for c in components}
    for comp, path in components.items():
        tree = trees[comp] if trees else read_tree(path)
        for ref in extract_imports(tree):
            out_edges[comp] |= resolver.resolve(comp, ref)
    in_edges: dict[str, set[str]] = {c: set() for c in components}
    for comp, targets in out_edges.items():
        for target in targets:
            in_edges[target].add(comp)
    return Graph(nodes=list(components), out_edges=out_edges, in_edges=in_edges,
                 unresolved=sorted(set(resolver.unresolved)))
