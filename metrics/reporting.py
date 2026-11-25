"""Responsabilidades 7 e 8: exportar o CSV e gerar o gráfico."""

from __future__ import annotations

import csv
from pathlib import Path

from metrics.calculations import ComponentMetrics

CSV_HEADER = ["component", "ca", "ce", "i", "a", "d"]


def write_csv(results: list[ComponentMetrics], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(CSV_HEADER)
        for m in sorted(results, key=lambda r: r.component):
            writer.writerow([m.component, m.ca, m.ce, f"{m.i:.2f}", f"{m.a:.2f}", f"{m.d:.2f}"])
    return path


def write_plot(results: list[ComponentMetrics], path: Path, title: str) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 9), dpi=100)

    # Zona de dor da régua: A<0,5, I<0,5, D>=0,5  <=>  triângulo A+I<=0,5
    ax.add_patch(Polygon([(0, 0), (0.5, 0), (0, 0.5)], closed=True, facecolor="#fca5a5",
                         edgecolor="#b91c1c", alpha=0.45, label="Zona de dor (régua: A<0,5, I<0,5, D≥0,5)"))
    # Zona de inutilidade: só conceitual, o desafio não define regra
    ax.add_patch(Polygon([(1, 1), (0.5, 1), (1, 0.5)], closed=True, facecolor="#e5e7eb",
                         edgecolor="#6b7280", alpha=0.6, hatch="//",
                         label="Zona de inutilidade (conceitual, sem regra)"))
    ax.plot([0, 1], [1, 0], color="#2563eb", linewidth=2, label="Main Sequence (A + I = 1)")

    groups: dict[tuple, list[ComponentMetrics]] = {}
    for m in sorted(results, key=lambda r: r.component):
        groups.setdefault((float(m.i), float(m.a)), []).append(m)
    # Rótulos: estimativa da caixa de cada rótulo; se colidir com outra já
    # posicionada, sobe uma "faixa". Pontos com as mesmas coordenadas viram
    # um único marcador com todos os nomes.
    boxes: list[tuple[float, float, float, float]] = []
    for (x, y), members in sorted(groups.items()):
        pain = any(m.pain_zone for m in members)
        ax.scatter([x], [y], s=70 + 25 * (len(members) - 1), zorder=5,
                   color="#b91c1c" if pain else "#111827", edgecolor="white", linewidth=1)
        lines = [f"{m.component} (D={m.d:.2f})" for m in members]
        width = 0.0105 * max(len(t) for t in lines) + 0.02
        height = 0.028 * len(lines) + 0.015
        right = x + 0.03 + width > 1.0
        tx = x - 0.03 if right else x + 0.03
        x0, x1 = (tx - width, tx) if right else (tx, tx + width)
        up = y < 0.75
        lane = 0
        while True:
            base = y + 0.06 + 0.07 * lane if up else y - 0.06 - 0.07 * lane
            y0, y1 = (base, base + height) if up else (base - height, base)
            if not any(x0 < bx1 and bx0 < x1 and y0 < by1 and by0 < y1 for bx0, bx1, by0, by1 in boxes):
                break
            lane += 1
        boxes.append((x0, x1, y0, y1))
        ax.annotate("\n".join(lines), (x, y), xytext=(tx, (y0 + y1) / 2), fontsize=8, zorder=6,
                    ha="right" if right else "left", va="center",
                    arrowprops=dict(arrowstyle="-", color="#6b7280", lw=0.7),
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="#d1d5db", alpha=0.95))

    ax.set_xlim(-0.03, 1.03)
    ax.set_ylim(-0.03, 1.03)
    ax.set_xlabel("I — Instabilidade = Ce / (Ca + Ce)")
    ax.set_ylabel("A — Abstração = abstratas / total de classes")
    ax.set_title(f"Main Sequence — {title} ({len(results)} componentes)")
    ax.grid(True, linestyle=":", alpha=0.6)
    ax.set_aspect("equal")
    ax.legend(loc="upper right", fontsize=8, framealpha=0.95)
    fig.tight_layout()
    fig.savefig(path, format="png", metadata={"Software": None})
    plt.close(fig)
    return path
