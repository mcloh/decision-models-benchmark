"""Gráficos (SVG) a partir dos resumos coletados em reports/<etapa>/ (tarefa 74).

Paleta: slots 1 (azul, GPU) e 2 (laranja, CPU) da paleta categórica de referência, validados
(CVD ΔE 24,7; visão normal 33,6; contraste ≥ 3:1 sobre #fcfcfb). Uma série → sem legenda;
duas séries → legenda + rótulos diretos. Um único eixo y por gráfico.

Uso: python -m analysis.charts reports/pilot
"""
import json
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1"
GPU, CPU = "#2a78d6", "#eb6834"
NAMES = {"semif": "SemIf", "rizzo_flow": "Rizzo Flow", "laya": "Laya", "gliner": "GLiNER"}
P95_LIMIT_MS = 150

plt.rcParams.update({
    "svg.fonttype": "none", "font.family": "sans-serif", "font.size": 11,
    "axes.edgecolor": GRID, "axes.labelcolor": INK_2, "xtick.color": INK_2, "ytick.color": INK_2,
    "axes.facecolor": SURFACE, "figure.facecolor": SURFACE, "text.color": INK,
})


def save(fig, path: Path):
    fig.savefig(path)
    preview = os.environ.get("DMB_CHART_PREVIEW")  # PNG para inspeção visual, fora do repositório
    if preview:
        fig.savefig(Path(preview) / path.with_suffix(".png").name, dpi=110)


def load(dest: Path) -> dict:
    out = {}
    for f in dest.glob("summary-*.json"):
        s = json.loads(f.read_text())
        out[(s["candidate"]["name"], s["device"])] = s
    return out


def style(ax, grid_axis="x"):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis=grid_axis, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def accuracy_chart(data, dest):
    rows = sorted(((NAMES[c], s["quality"]["accuracy"] * 100) for (c, d), s in data.items() if d == "cuda"),
                  key=lambda r: r[1])
    fig, ax = plt.subplots(figsize=(7, 2.8))
    bars = ax.barh([r[0] for r in rows], [r[1] for r in rows], height=0.55, color=GPU)
    for bar, (_, v) in zip(bars, rows):
        ax.text(v + 1, bar.get_y() + bar.get_height() / 2, f"{v:.0f}%", va="center", color=INK, fontsize=11)
    ax.set_xlim(0, 105)
    ax.set_xlabel("Acurácia (%)")
    ax.set_title("Acurácia por candidato — piloto, 50 exemplos de dev", loc="left", fontsize=12, color=INK)
    style(ax)
    fig.tight_layout()
    save(fig, dest / "chart-acuracia.svg")
    plt.close(fig)


def latency_chart(data, dest):
    cands = sorted({c for c, _ in data}, key=lambda c: data[(c, "cuda")]["latency_ms"]["p50"])
    fig, ax = plt.subplots(figsize=(7, 3.0))
    for i, c in enumerate(cands):
        g = data[(c, "cuda")]["latency_ms"]["p50"]
        cpu = data.get((c, "cpu"), {}).get("latency_ms", {}).get("p50")
        if cpu:
            ax.plot([g, cpu], [i, i], color=GRID, linewidth=2, zorder=1)
            ax.scatter(cpu, i, s=70, color=CPU, edgecolor=SURFACE, linewidth=2, zorder=3,
                       label="CPU (8 OCPU)" if i == 0 else None)
            ax.text(cpu * 1.18, i, f"{cpu / 1000:.1f} s" if cpu >= 1000 else f"{cpu:.0f} ms",
                    va="center", color=INK, fontsize=10)
        ax.scatter(g, i, s=70, color=GPU, edgecolor=SURFACE, linewidth=2, zorder=3,
                   label="GPU (A10)" if i == 0 else None)
        ax.text(g / 1.18, i, f"{g:.0f} ms", va="center", ha="right", color=INK, fontsize=10)
    ax.set_xscale("log")
    ax.set_xlim(5, 200_000)
    ax.set_yticks(range(len(cands)), [NAMES[c] for c in cands])
    ax.set_ylim(-0.6, len(cands) - 0.4)
    ax.set_xlabel("Latência mediana por decisão (ms, escala log)")
    ax.set_title("Latência por decisão: GPU × CPU (lote 1)", loc="left", fontsize=12, color=INK)
    ax.legend(loc="lower right", frameon=False, fontsize=10)
    style(ax)
    fig.tight_layout()
    save(fig, dest / "chart-latencia.svg")
    plt.close(fig)


def tradeoff_chart(data, dest):
    fig, ax = plt.subplots(figsize=(7, 3.6))
    ax.axvline(P95_LIMIT_MS, color=INK_2, linewidth=1, linestyle=(0, (4, 3)))
    ax.text(P95_LIMIT_MS + 3, 102, f"limite p95 = {P95_LIMIT_MS} ms", color=INK_2, fontsize=9, va="top")
    for (c, d), s in data.items():
        if d != "cuda":
            continue
        x, y = s["latency_ms"]["p95"], s["quality"]["accuracy"] * 100
        ax.scatter(x, y, s=80, color=GPU, edgecolor=SURFACE, linewidth=2, zorder=3)
        ax.annotate(NAMES[c], (x, y), xytext=(8, -4), textcoords="offset points", color=INK, fontsize=10)
    ax.set_xlim(0, 220)
    ax.set_ylim(30, 104)
    ax.set_xlabel("Latência p95 por decisão em GPU A10 (ms)")
    ax.set_ylabel("Acurácia (%)")
    ax.set_title("Qualidade × latência em GPU — piloto", loc="left", fontsize=12, color=INK)
    style(ax, grid_axis="both")
    fig.tight_layout()
    save(fig, dest / "chart-qualidade-latencia.svg")
    plt.close(fig)


def main():
    dest = Path(sys.argv[1])
    data = load(dest)
    accuracy_chart(data, dest)
    latency_chart(data, dest)
    tradeoff_chart(data, dest)
    print(sorted(p.name for p in dest.glob("chart-*.svg")))


if __name__ == "__main__":
    main()
