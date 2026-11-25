"""Mede Ca, Ce, I, A e D dos componentes de um diretório de código Python.

Uso:
    python metrics/measure.py --source ../helpdesk-v1/app/helpdesk --name v1-coupled

Gera <output-dir>/<name>.csv (component,ca,ce,i,a,d) e <output-dir>/<name>.png.
Análise 100% estática (AST): o código analisado nunca é importado nem executado.

Códigos de saída: 0 sucesso; 1 erro de análise (arquivo ilegível ou com erro
de sintaxe; a medição não é gerada pela metade); 2 argumentos inválidos.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from metrics.abstraction import analyze_classes  # noqa: E402
from metrics.calculations import ComponentMetrics, compute  # noqa: E402
from metrics.dependencies import Graph, build_graph  # noqa: E402
from metrics.discovery import discover_components  # noqa: E402
from metrics.parsing import AnalysisError, read_tree  # noqa: E402
from metrics.reporting import write_csv, write_plot  # noqa: E402

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "results"
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def analyze(source: Path, root_package: str | None = None) -> tuple[list[ComponentMetrics], Graph]:
    """Pipeline completo, sem efeitos colaterais: devolve métricas e grafo."""
    source = Path(source)
    root = root_package or source.resolve().name
    components = discover_components(source)
    trees = {comp: read_tree(path) for comp, path in components.items()}
    graph = build_graph(source, components, root, trees)
    results = []
    for comp in components:
        classes = analyze_classes(trees[comp])
        results.append(compute(comp, len(graph.in_edges[comp]), len(graph.out_edges[comp]),
                               sum(c.abstract for c in classes), len(classes)))
    return results, graph


def summary(results: list[ComponentMetrics], graph: Graph) -> str:
    lines = [f"{'component':<28} {'ca':>3} {'ce':>3} {'i':>5} {'a':>5} {'d':>5}  classes  zona-de-dor"]
    for m in results:
        flag = "SIM" if m.pain_zone else "-"
        if m.borderline:
            flag += " (limite: o valor exato classificaria diferente)"
        lines.append(f"{m.component:<28} {m.ca:>3} {m.ce:>3} {m.i:>5} {m.a:>5} {m.d:>5}  "
                     f"{m.abstract_classes}/{m.total_classes:<5}  {flag}")
    lines.append("")
    lines.append(f"arestas ({len(graph.edges)}):")
    lines.extend(f"  {a} -> {b}" for a, b in graph.edges)
    total_ca = sum(m.ca for m in results)
    total_ce = sum(m.ce for m in results)
    lines.append(f"soma Ca = {total_ca}, soma Ce = {total_ce} ({'ok' if total_ca == total_ce else 'INCONSISTENTE'})")
    if graph.unresolved:
        lines.append("imports internos não resolvidos (não contabilizados):")
        lines.extend(f"  {u}" for u in graph.unresolved)
    return "\n".join(lines)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="measure.py",
        description="Métricas de acoplamento (Ca, Ce, I, A, D) por análise estática.")
    parser.add_argument("--source", required=True, type=Path,
                        help="diretório do pacote analisado (ex.: ../helpdesk-v1/app/helpdesk)")
    parser.add_argument("--name", required=True,
                        help="nome da medição; vira o nome dos arquivos (ex.: v1-coupled)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT,
                        help=f"onde gravar CSV e PNG (padrão: {DEFAULT_OUTPUT.name}/ ao lado do script)")
    parser.add_argument("--root-package", default=None,
                        help="nome do pacote raiz nos imports absolutos (padrão: nome do diretório --source)")
    parser.add_argument("--no-plot", action="store_true", help="não gera o PNG")
    args = parser.parse_args(argv)
    if not args.source.is_dir():
        parser.error(f"--source não é um diretório: {args.source}")
    if not NAME_PATTERN.match(args.name):
        parser.error(f"--name inválido: {args.name!r} (use letras, números, '.', '_' ou '-')")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        results, graph = analyze(args.source, args.root_package)
    except AnalysisError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1
    if not results:
        print(f"erro: nenhum componente .py encontrado em {args.source}", file=sys.stderr)
        return 1
    csv_path = write_csv(results, args.output_dir / f"{args.name}.csv")
    print(summary(results, graph))
    print(f"\nCSV: {csv_path}")
    if not args.no_plot:
        png_path = write_plot(results, args.output_dir / f"{args.name}.png", args.name)
        print(f"PNG: {png_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
