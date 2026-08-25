import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import polars as pl
from matplotlib.lines import Line2D

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


def _max_solved_cells(
    results: pl.DataFrame, variant: str, group_col: str = "benchmark"
) -> pl.DataFrame:
    return (
        results.filter(pl.col(f"result_{variant}") == "PASS")
        .group_by(group_col, "task")
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


def _plot_cell_diff_bar(
    results: pl.DataFrame,
    out_path: Path,
    group_col: str = "benchmark",
    legend_title: str = "Benchmark",
    title_suffix: str = "(all benchmarks)",
) -> Path | None:
    benchmark_order = results[group_col].unique(maintain_order=True).to_list()

    mi = _max_solved_cells(results, "miter", group_col=group_col)
    ia = _max_solved_cells(results, "internal_asserts", group_col=group_col)
    joined = mi.join(ia, on=[group_col, "task"], how="inner").filter(
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

    present = set(joined[group_col].unique().to_list())
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
        rows = joined.filter(pl.col(group_col) == benchmark)
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
    ax.set_title(f"Cell-count headroom from internal asserts, per task {title_suffix}")
    ax.legend(
        frameon=False,
        labelcolor=INK_SECONDARY,
        fontsize=8.5,
        title=legend_title,
        title_fontsize=9,
        loc="upper left",
        bbox_to_anchor=(1.02, 1.0),
        borderaxespad=0,
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _plot_scatter(
    results: pl.DataFrame,
    out_path: Path,
    group_col: str = "benchmark",
    legend_title: str = "Benchmark",
    title_suffix: str = "(all benchmarks)",
) -> Path | None:
    benchmark_order = results[group_col].unique(maintain_order=True).to_list()
    mi = _max_solved_cells(results, "miter", group_col=group_col)
    ia = _max_solved_cells(results, "internal_asserts", group_col=group_col)
    points = (
        mi.join(ia, on=[group_col, "task"], how="full", coalesce=True)
        .fill_null(0)
        .with_columns(
            pl.col("max_cells_miter").clip(lower_bound=1),
            pl.col("max_cells_internal_asserts").clip(lower_bound=1),
        )
        .sort([group_col, "task"])
    )
    if points.is_empty():
        return None

    present = set(points[group_col].unique().to_list())
    benchmarks = [b for b in benchmark_order if b in present]
    colors = _categorical_colors(benchmarks)

    fig, ax = plt.subplots(figsize=(9.5, 9.5))
    _apply_chrome(fig, ax)

    for benchmark in benchmarks:
        rows = points.filter(pl.col(group_col) == benchmark)
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
    ax.set_title(f"MI vs. IA max cells solved, per task {title_suffix}")
    ax.legend(
        frameon=False,
        labelcolor=INK_SECONDARY,
        fontsize=8.5,
        title=legend_title,
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


def _plot_cactus_overlay(
    results: pl.DataFrame, group_col: str, out_path: Path
) -> Path | None:
    groups = results[group_col].unique(maintain_order=True).to_list()
    colors = _categorical_colors(groups)

    fig, axes = plt.subplots(1, 2, figsize=(16, 7.5), sharey=True)
    any_points = False
    for ax, variant in zip(axes, ("miter", "internal_asserts")):
        _apply_chrome(fig, ax)
        for group in groups:
            sub = results.filter(pl.col(group_col) == group)
            secs, cells = _cactus_curve(sub, variant)
            if not secs:
                continue
            any_points = True
            secs = [max(secs[0], 0.01) * 0.5, *[max(s, 0.01) for s in secs]]
            cells = [cells[0], *cells]
            ax.step(
                secs,
                cells,
                where="post",
                color=colors[group],
                linewidth=2,
                label=group,
                zorder=3,
            )
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.grid(True, which="both", color=GRID, linewidth=0.6, zorder=0)
        ax.set_xlabel("Time budget (s, log scale)")
        ax.set_title(VARIANT_LABELS[variant])

    if not any_points:
        plt.close(fig)
        return None

    axes[0].set_ylabel("Largest provable cell count (log scale)")
    axes[1].legend(
        frameon=False,
        labelcolor=INK_SECONDARY,
        fontsize=8.5,
        title="Benchmark",
        title_fontsize=9,
        loc="upper left",
        bbox_to_anchor=(1.02, 1.0),
        borderaxespad=0,
    )
    fig.suptitle(
        "Cross-benchmark cactus plot: cells solved vs. time budget", color=INK
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _plot_leaderboard(
    results: pl.DataFrame, group_col: str, out_path: Path
) -> Path | None:
    mi = (
        _max_solved_cells(results, "miter", group_col=group_col)
        .group_by(group_col)
        .agg(pl.col("max_cells_miter").max().alias("best_mi"))
    )
    ia = (
        _max_solved_cells(results, "internal_asserts", group_col=group_col)
        .group_by(group_col)
        .agg(pl.col("max_cells_internal_asserts").max().alias("best_ia"))
    )
    both = mi.join(ia, on=group_col, how="full", coalesce=True).fill_null(0)
    if both.is_empty():
        return None
    both = both.with_columns(
        pl.max_horizontal("best_mi", "best_ia").alias("sort_key")
    ).sort("sort_key")

    groups = both[group_col].to_list()
    mi_vals = both["best_mi"].to_list()
    ia_vals = both["best_ia"].to_list()
    ys = range(len(groups))

    fig, ax = plt.subplots(figsize=(9.5, max(3.5, 0.6 * len(groups) + 1.5)))
    _apply_chrome(fig, ax)
    positive = [v for v in (*mi_vals, *ia_vals) if v > 0]
    xlim_lo = min(positive) / 3 if positive else 1
    row_offset = 0.17
    for y, mi_v, ia_v in zip(ys, mi_vals, ia_vals):
        for value, color, dy in (
            (mi_v, COLOR_MITER, row_offset),
            (ia_v, COLOR_INTERNAL_ASSERTS, -row_offset),
        ):
            if value <= 0:
                continue
            yy = y + dy
            ax.hlines(yy, xlim_lo, value, color=color, linewidth=3, zorder=3)
            ax.scatter([value], [yy], color=color, s=55, zorder=4)
            ax.text(
                value * 1.03, yy, f"{value:,}", va="center", fontsize=7.5,
                color=INK_SECONDARY, zorder=4,
            )

    ax.set_yticks(list(ys), groups, fontsize=9, color=INK_SECONDARY)
    ax.set_xscale("log")
    ax.set_xlim(left=xlim_lo)
    ax.grid(axis="x", which="both", color=GRID, linewidth=0.6, zorder=0)
    ax.set_xlabel("Largest solved cell count, best task (log scale)")
    ax.set_title("Suite leaderboard: max cells solved, MI vs. IA")
    ax.legend(
        handles=[
            Line2D([0], [0], color=COLOR_MITER, lw=3, marker="o",
                   label=VARIANT_LABELS["miter"]),
            Line2D([0], [0], color=COLOR_INTERNAL_ASSERTS, lw=3, marker="o",
                   label=VARIANT_LABELS["internal_asserts"]),
        ],
        frameon=False,
        labelcolor=INK_SECONDARY,
        fontsize=8.5,
        loc="lower right",
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _split_synth_flavor(results: pl.DataFrame) -> pl.DataFrame:
    return results.with_columns(
        pl.when(pl.col("benchmark").str.ends_with("(ORFS)"))
        .then(pl.lit("ORFS"))
        .otherwise(pl.lit("Plain Yosys"))
        .alias("synth_flavor")
    )


def _plot_synth_flavor_scatter(results: pl.DataFrame, out_path: Path) -> Path | None:
    flavored = _split_synth_flavor(results)
    benchmark_order = flavored["benchmark_dir"].unique(maintain_order=True).to_list()
    colors = _categorical_colors(benchmark_order)

    fig, axes = plt.subplots(1, 2, figsize=(16.5, 8), sharex=True, sharey=True)
    any_points = False
    for ax, flavor in zip(axes, ("Plain Yosys", "ORFS")):
        _apply_chrome(fig, ax)
        ax.set_title(flavor)
        subset = flavored.filter(pl.col("synth_flavor") == flavor)
        if subset.is_empty():
            continue
        mi = _max_solved_cells(subset, "miter", group_col="benchmark_dir")
        ia = _max_solved_cells(subset, "internal_asserts", group_col="benchmark_dir")
        points = (
            mi.join(ia, on=["benchmark_dir", "task"], how="full", coalesce=True)
            .fill_null(0)
            .with_columns(
                pl.col("max_cells_miter").clip(lower_bound=1),
                pl.col("max_cells_internal_asserts").clip(lower_bound=1),
            )
        )
        if points.is_empty():
            continue

        for benchmark_dir in benchmark_order:
            rows = points.filter(pl.col("benchmark_dir") == benchmark_dir)
            if rows.is_empty():
                continue
            any_points = True
            ax.scatter(
                rows["max_cells_miter"],
                rows["max_cells_internal_asserts"],
                s=60,
                color=colors[benchmark_dir],
                alpha=0.85,
                edgecolors=SURFACE,
                linewidths=0.6,
                label=benchmark_dir,
                zorder=3,
            )
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.grid(True, which="both", color=GRID, linewidth=0.6, zorder=0)
        ax.set_xlabel("Miter (MI): max cells solved (log scale)")

    if not any_points:
        plt.close(fig)
        return None

    lo, hi = float("inf"), 0.0
    for ax in axes:
        for coll in ax.collections:
            offsets = coll.get_offsets()
            if len(offsets):
                lo = min(lo, offsets[:, 0].min(), offsets[:, 1].min())
                hi = max(hi, offsets[:, 0].max(), offsets[:, 1].max())
    lo, hi = lo * 0.7, hi * 1.4
    for ax in axes:
        ax.plot([lo, hi], [lo, hi], color=AXIS, linewidth=1, linestyle="--", zorder=2)
        ax.set_xlim(lo, hi)
        ax.set_ylim(lo, hi)
        ax.set_aspect("equal", adjustable="box")

    axes[0].set_ylabel("Internal asserts (IA): max cells solved (log scale)")
    axes[1].legend(
        frameon=False,
        labelcolor=INK_SECONDARY,
        fontsize=8.5,
        title="Design",
        title_fontsize=9,
        loc="upper left",
        bbox_to_anchor=(1.02, 1.0),
        borderaxespad=0,
    )
    fig.suptitle("MI vs. IA max cells solved, by synthesis flow", color=INK)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return out_path


def generate_cross_benchmark_plots(
    results: pl.DataFrame, out_dir: Path, group_col: str = "benchmark_dir"
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    result = _plot_cell_diff_bar(
        results,
        out_dir / "suite_cell_diff_bar.png",
        group_col=group_col,
        legend_title="Design",
        title_suffix="(whole suite)",
    )
    if result is not None:
        written.append(result)

    result = _plot_scatter(
        results,
        out_dir / "suite_scatter.png",
        group_col=group_col,
        legend_title="Design",
        title_suffix="(whole suite)",
    )
    if result is not None:
        written.append(result)

    result = _plot_cactus_overlay(results, group_col, out_dir / "suite_cactus.png")
    if result is not None:
        written.append(result)

    result = _plot_leaderboard(results, group_col, out_dir / "suite_leaderboard.png")
    if result is not None:
        written.append(result)

    result = _plot_synth_flavor_scatter(results, out_dir / "suite_synth_flavor.png")
    if result is not None:
        written.append(result)

    return written
