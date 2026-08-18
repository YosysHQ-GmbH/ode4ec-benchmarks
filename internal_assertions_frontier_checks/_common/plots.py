import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import polars as pl

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"

COLOR_MITER = "#2a78d6"
COLOR_INTERNAL_ASSERTS = "#eb6834"

VARIANT_LABELS = {
    "miter": "Plain miter (MI)",
    "internal_asserts": "Internal asserts (IA)",
}
VARIANT_COLORS = {"miter": COLOR_MITER, "internal_asserts": COLOR_INTERNAL_ASSERTS}


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _apply_chrome(fig: plt.Figure, ax: plt.Axes) -> None:
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.xaxis.label.set_color(INK_SECONDARY)
    ax.yaxis.label.set_color(INK_SECONDARY)
    ax.title.set_color(INK)


def _max_solved_cells(results: pl.DataFrame, variant: str) -> pl.DataFrame:
    return (
        results.filter(pl.col(f"result_{variant}") == "PASS")
        .group_by("benchmark", "task")
        .agg(pl.col(f"cells_{variant}").max().alias(f"max_cells_{variant}"))
    )


def _categorical_colors(labels: list[str]) -> dict[str, tuple]:
    validated_slots = [
        "#2a78d6",  # blue
        "#eb6834",  # orange
        "#1baf7a",  # aqua
        "#eda100",  # yellow
        "#e87ba4",  # magenta
        "#008300",  # green
        "#4a3aa7",  # violet
        "#e34948",  # red
    ]
    overflow_cmap = plt.get_cmap("tab20")
    colors: dict[str, tuple] = {}
    for i, label in enumerate(labels):
        if i < len(validated_slots):
            colors[label] = validated_slots[i]
        else:
            colors[label] = overflow_cmap((i - len(validated_slots)) % overflow_cmap.N)
    return colors


def _plot_cell_diff_bar(results: pl.DataFrame, out_path: Path) -> Path | None:
    benchmark_order = results["benchmark"].unique(maintain_order=True).to_list()

    mi = _max_solved_cells(results, "miter")
    ia = _max_solved_cells(results, "internal_asserts")
    joined = mi.join(ia, on=["benchmark", "task"], how="inner").filter(
        pl.col("max_cells_miter") > 0
    )
    if joined.is_empty():
        return None

    joined = joined.with_columns(
        (
            (pl.col("max_cells_internal_asserts") - pl.col("max_cells_miter"))
            / pl.col("max_cells_miter")
            * 100
        ).alias("pct_diff")
    )

    present = set(joined["benchmark"].unique().to_list())
    benchmarks = [b for b in benchmark_order if b in present]
    colors = _categorical_colors(benchmarks)

    task_order = (
        joined.group_by("task")
        .agg(pl.col("pct_diff").mean().alias("mean_diff"))
        .sort("mean_diff")["task"]
        .to_list()
    )
    task_index = {task: i for i, task in enumerate(task_order)}

    n_benchmarks = len(benchmarks)
    group_height = 0.8
    bar_height = group_height / n_benchmarks
    span = max(joined["pct_diff"].abs().max(), 1)

    fig, ax = plt.subplots(figsize=(11, max(3.5, 0.6 * len(task_order) + 1.5)))
    _apply_chrome(fig, ax)

    for bi, benchmark in enumerate(benchmarks):
        rows = joined.filter(pl.col("benchmark") == benchmark)
        ys = [
            task_index[task] + (bi - (n_benchmarks - 1) / 2) * bar_height
            for task in rows["task"].to_list()
        ]
        xs = rows["pct_diff"].to_list()
        ax.barh(
            ys,
            xs,
            height=bar_height * 0.9,
            color=colors[benchmark],
            label=benchmark,
            zorder=3,
        )
        for y, v in zip(ys, xs):
            ax.text(
                v + (span * 0.02 if v >= 0 else -span * 0.02),
                y,
                f"{v:+.0f}%",
                va="center",
                ha="left" if v >= 0 else "right",
                fontsize=6.5,
                color=INK_SECONDARY,
                zorder=4,
            )

    ax.set_yticks(range(len(task_order)), task_order, fontsize=9, color=INK_SECONDARY)
    ax.axvline(0, color=AXIS, linewidth=1)
    ax.grid(axis="x", color=GRID, linewidth=0.6, zorder=0)
    ax.set_xlim(-span * 1.3, span * 1.3)

    ax.set_xlabel("Max solvable cell count, IA vs. MI (%)")
    ax.set_title("Cell-count headroom from internal asserts, per task (all benchmarks)")
    ax.legend(
        frameon=False,
        labelcolor=INK_SECONDARY,
        fontsize=8.5,
        title="Benchmark",
        title_fontsize=9,
        loc="upper left",
        bbox_to_anchor=(1.02, 1.0),
        borderaxespad=0,
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _plot_scatter(results: pl.DataFrame, out_path: Path) -> Path | None:
    benchmark_order = results["benchmark"].unique(maintain_order=True).to_list()
    mi = _max_solved_cells(results, "miter")
    ia = _max_solved_cells(results, "internal_asserts")
    points = (
        mi.join(ia, on=["benchmark", "task"], how="full", coalesce=True)
        .fill_null(0)
        .with_columns(
            pl.col("max_cells_miter").clip(lower_bound=1),
            pl.col("max_cells_internal_asserts").clip(lower_bound=1),
        )
        .sort(["benchmark", "task"])
    )
    if points.is_empty():
        return None

    present = set(points["benchmark"].unique().to_list())
    benchmarks = [b for b in benchmark_order if b in present]
    colors = _categorical_colors(benchmarks)

    fig, ax = plt.subplots(figsize=(9.5, 9.5))
    _apply_chrome(fig, ax)

    for benchmark in benchmarks:
        rows = points.filter(pl.col("benchmark") == benchmark)
        ax.scatter(
            rows["max_cells_miter"],
            rows["max_cells_internal_asserts"],
            s=60,
            color=colors[benchmark],
            alpha=0.85,
            edgecolors=SURFACE,
            linewidths=0.6,
            label=benchmark,
            zorder=3,
        )

    lo = (
        min(points["max_cells_miter"].min(), points["max_cells_internal_asserts"].min())
        * 0.7
    )
    hi = (
        max(points["max_cells_miter"].max(), points["max_cells_internal_asserts"].max())
        * 1.4
    )
    ax.plot([lo, hi], [lo, hi], color=AXIS, linewidth=1, linestyle="--", zorder=2)
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, which="both", color=GRID, linewidth=0.6, zorder=0)
    ax.set_xlabel("Miter (MI): max cells solved (log scale)")
    ax.set_ylabel("Internal asserts (IA): max cells solved (log scale)")
    ax.set_title("MI vs. IA max cells solved, per task (all benchmarks)")
    ax.legend(
        frameon=False,
        labelcolor=INK_SECONDARY,
        fontsize=8.5,
        title="Benchmark",
        title_fontsize=9,
        loc="upper left",
        bbox_to_anchor=(1.02, 1.0),
        borderaxespad=0,
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _cactus_curve(
    benchmark_df: pl.DataFrame, variant: str
) -> tuple[list[float], list[int]]:
    sub = (
        benchmark_df.filter(pl.col(f"result_{variant}") == "PASS")
        .select(
            pl.col(f"process_secs_{variant}").alias("secs"),
            pl.col(f"cells_{variant}").alias("cells"),
        )
        .drop_nulls()
        .sort("secs")
    )
    if sub.is_empty():
        return [], []
    secs = sub["secs"].to_list()
    cummax = sub.select(pl.col("cells").cum_max()).to_series().to_list()
    return secs, cummax


def _plot_cactus(
    benchmark_df: pl.DataFrame, benchmark: str, out_path: Path
) -> Path | None:
    fig, ax = plt.subplots(figsize=(10, 7))
    _apply_chrome(fig, ax)

    any_points = False
    for variant in ("miter", "internal_asserts"):
        secs, cells = _cactus_curve(benchmark_df, variant)
        if not secs:
            continue
        any_points = True
        secs = [max(secs[0], 0.01) * 0.5, *[max(s, 0.01) for s in secs]]
        cells = [cells[0], *cells]
        ax.step(
            secs,
            cells,
            where="post",
            color=VARIANT_COLORS[variant],
            linewidth=2,
            label=VARIANT_LABELS[variant],
            zorder=3,
        )

    if not any_points:
        plt.close(fig)
        return None

    ax.set_xscale("log")
    ax.grid(True, which="both", color=GRID, linewidth=0.6, zorder=0)
    ax.set_xlabel("Time budget (s, log scale)")
    ax.set_ylabel("Largest provable cell count")
    ax.set_title(f"{benchmark}: cactus plot (cells over time)")
    ax.legend(frameon=False, labelcolor=INK_SECONDARY, fontsize=9, loc="upper left")
    fig.tight_layout()
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    return out_path


def generate_plots(results: pl.DataFrame, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    combined_plots = [
        (_plot_cell_diff_bar, "all_benchmarks_cell_diff_bar.png"),
        (_plot_scatter, "all_benchmarks_scatter.png"),
    ]
    for plot_fn, filename in combined_plots:
        result = plot_fn(results, out_dir / filename)
        if result is not None:
            written.append(result)

    for benchmark in results["benchmark"].unique(maintain_order=True):
        benchmark_df = results.filter(pl.col("benchmark") == benchmark)
        slug = _slugify(benchmark)
        result = _plot_cactus(benchmark_df, benchmark, out_dir / f"{slug}_cactus.png")
        if result is not None:
            written.append(result)

    return written
