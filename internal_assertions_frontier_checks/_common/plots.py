import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

VARIANT_LABELS = {
    "miter": "Plain miter (MI)",
    "internal_asserts": "Internal asserts (IA)",
}

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
NODATA = "#eceae1"

COLOR_MITER = "#2a78d6"
COLOR_INTERNAL_ASSERTS = "#eb6834"

TIE_RATIO = 1.05


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


def _facet_layout(n: int) -> tuple[int, int]:
    if n <= 0:
        return (1, 1)
    ncols = min(max(math.ceil(math.sqrt(n)), 1), 5)
    nrows = math.ceil(n / ncols)
    return nrows, ncols


def _facet_grid(
    n: int,
    panel_w: float = 3.4,
    panel_h: float = 3.0,
    sharex: bool = True,
    sharey: bool = True,
) -> tuple[plt.Figure, list[plt.Axes], list[plt.Axes]]:
    nrows, ncols = _facet_layout(n)
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(panel_w * ncols, panel_h * nrows),
        sharex=sharex,
        sharey=sharey,
        squeeze=False,
    )
    flat = list(axes.flatten())
    used, spare = flat[:n], flat[n:]
    for ax in spare:
        ax.axis("off")
    return fig, used, spare


def _place_legend(
    fig: plt.Figure, spare: list[plt.Axes], handles: list, **kwargs
) -> None:
    common = dict(frameon=False, labelcolor=INK_SECONDARY, fontsize=9)
    common.update(kwargs)
    if spare:
        spare[0].legend(handles=handles, loc="center", **common)
    else:
        fig.legend(
            handles=handles,
            loc="lower center",
            ncols=len(handles),
            bbox_to_anchor=(0.5, -0.035),
            **common,
        )


def _mi_ia_points(results: pl.DataFrame, group_col: str) -> pl.DataFrame:
    mi = _max_solved_cells(results, "miter", group_col=group_col)
    ia = _max_solved_cells(results, "internal_asserts", group_col=group_col)
    return (
        mi.join(ia, on=[group_col, "task"], how="full", coalesce=True)
        .with_columns(
            pl.col("max_cells_miter").fill_null(0),
            pl.col("max_cells_internal_asserts").fill_null(0),
        )
        .filter(
            (pl.col("max_cells_miter") > 0) | (pl.col("max_cells_internal_asserts") > 0)
        )
    )


def _win_loss_masks(
    mi: np.ndarray, ia: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    better = ia > mi * TIE_RATIO
    worse = ia * TIE_RATIO < mi
    return (~better) & (~worse), better, worse


def _geomean_max_cells(
    results: pl.DataFrame, variant: str, group_col: str
) -> pl.DataFrame:
    keys = list(dict.fromkeys([group_col, "task", "benchmark"]))
    per_axis = (
        results.filter(pl.col(f"result_{variant}") == "PASS")
        .group_by(*keys)
        .agg(pl.col(f"cells_{variant}").max().alias("m"))
        .filter(pl.col("m") > 0)
    )
    return per_axis.group_by(group_col, "task").agg(
        pl.col("m").log().mean().exp().alias(f"geo_cells_{variant}")
    )


def _plot_task_design_bars(
    results: pl.DataFrame,
    out_path: Path,
    group_col: str = "benchmark_dir",
    title_suffix: str = "(all benchmarks)",
) -> Path | None:
    mi = _geomean_max_cells(results, "miter", group_col)
    ia = _geomean_max_cells(results, "internal_asserts", group_col)
    data = mi.join(ia, on=[group_col, "task"], how="full", coalesce=True).with_columns(
        pl.col("geo_cells_miter").fill_null(0.0),
        pl.col("geo_cells_internal_asserts").fill_null(0.0),
    )
    if data.is_empty():
        return None

    tasks = sorted(data["task"].unique().to_list())
    order = (
        data.group_by(group_col)
        .agg(
            pl.max_horizontal("geo_cells_miter", "geo_cells_internal_asserts")
            .max()
            .alias("k")
        )
        .sort("k", descending=True)[group_col]
        .to_list()
    )
    x = np.arange(len(order))

    allvals = np.concatenate(
        [
            data["geo_cells_miter"].to_numpy(),
            data["geo_cells_internal_asserts"].to_numpy(),
        ]
    )
    allvals = allvals[allvals > 0]
    if allvals.size == 0:
        return None
    floor, ceil = allvals.min() / 2, allvals.max() * 1.6

    panel_w = min(8.0, max(4.0, 0.3 * len(order) + 1.5))
    fig, axes, spare = _facet_grid(len(tasks), panel_w=panel_w, panel_h=3.4)
    width = 0.4
    for ax, task in zip(axes, tasks):
        _apply_chrome(fig, ax)
        by_design = {
            d: (m, a)
            for d, m, a in data.filter(pl.col("task") == task)
            .select(group_col, "geo_cells_miter", "geo_cells_internal_asserts")
            .iter_rows()
        }
        mi_v = np.array([by_design.get(d, (0.0, 0.0))[0] for d in order])
        ia_v = np.array([by_design.get(d, (0.0, 0.0))[1] for d in order])
        for offset, vals, color in (
            (-width / 2, mi_v, COLOR_MITER),
            (width / 2, ia_v, COLOR_INTERNAL_ASSERTS),
        ):
            heights = np.where(vals > 0, vals, np.nan) - floor
            ax.bar(
                x + offset, heights, width=width, bottom=floor, color=color, zorder=3
            )
        ax.set_yscale("log")
        ax.set_ylim(floor, ceil)
        ax.set_xticks(x, order, rotation=40, ha="right", fontsize=7)
        ax.tick_params(labelbottom=True)
        ax.grid(axis="y", which="both", color=GRID, linewidth=0.5, zorder=0)
        ax.set_title(task, fontsize=9)

    handles = [
        Patch(color=COLOR_MITER, label=VARIANT_LABELS["miter"]),
        Patch(color=COLOR_INTERNAL_ASSERTS, label=VARIANT_LABELS["internal_asserts"]),
    ]
    fig.supylabel(
        "Geo-mean max solvable cells over synthesis axes (log scale)",
        color=INK_SECONDARY,
    )
    fig.suptitle(f"Max solvable cells per design, by engine {title_suffix}", color=INK)
    fig.tight_layout()
    _place_legend(fig, spare, handles)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _plot_cell_diff_heatmap(
    results: pl.DataFrame,
    out_path: Path,
    group_col: str = "benchmark",
    title_suffix: str = "(all benchmarks)",
) -> Path | None:
    pts = _mi_ia_points(results, group_col)
    if pts.is_empty():
        return None
    pts = pts.with_columns(
        (
            pl.col("max_cells_internal_asserts").clip(lower_bound=1).log(2)
            - pl.col("max_cells_miter").clip(lower_bound=1).log(2)
        ).alias("log2_ratio")
    )

    task_order = (
        pts.group_by("task")
        .agg(pl.col("log2_ratio").mean().alias("m"))
        .sort("m")["task"]
        .to_list()
    )
    group_order = (
        pts.group_by(group_col)
        .agg(pl.col("log2_ratio").mean().alias("m"))
        .sort("m", descending=True)[group_col]
        .to_list()
    )

    row_of = {t: r for r, t in enumerate(task_order)}
    col_of = {g: c for c, g in enumerate(group_order)}
    shape = (len(task_order), len(group_order))
    mat = np.full(shape, np.nan)
    mi_mat = np.zeros(shape)
    ia_mat = np.zeros(shape)
    for g, t, mi_raw, ia_raw, v in pts.select(
        group_col,
        "task",
        "max_cells_miter",
        "max_cells_internal_asserts",
        "log2_ratio",
    ).iter_rows():
        mat[row_of[t], col_of[g]] = v
        mi_mat[row_of[t], col_of[g]] = mi_raw
        ia_mat[row_of[t], col_of[g]] = ia_raw
    masked = np.ma.masked_invalid(mat)

    vmax = max(float(np.nanpercentile(np.abs(mat), 90)), 1.0)
    cmap = matplotlib.colormaps["RdBu_r"].copy()
    cmap.set_bad(NODATA)

    fig, ax = plt.subplots(
        figsize=(
            max(6.0, 0.55 * len(group_order) + 3.0),
            max(3.0, 0.55 * len(task_order) + 2.0),
        )
    )
    _apply_chrome(fig, ax)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_visible(False)
    im = ax.imshow(masked, cmap=cmap, vmin=-vmax, vmax=vmax, aspect="auto")

    ax.set_xticks(range(len(group_order)), group_order, rotation=40, ha="right")
    ax.set_yticks(range(len(task_order)), task_order)
    ax.set_xticks(np.arange(len(group_order) + 1) - 0.5, minor=True)
    ax.set_yticks(np.arange(len(task_order) + 1) - 0.5, minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=1.5)
    ax.tick_params(which="minor", length=0)
    ax.tick_params(which="major", length=0)

    if mat.size <= 140:
        for r in range(shape[0]):
            for c in range(shape[1]):
                v = mat[r, c]
                if np.isnan(v):
                    continue
                if ia_mat[r, c] == 0:
                    txt = "IA: 0"
                elif mi_mat[r, c] == 0:
                    txt = "MI: 0"
                else:
                    mult = ia_mat[r, c] / mi_mat[r, c]
                    if mult >= 9.5 or mult <= 0.105:
                        txt = f"{mult:.2g}×"
                    else:
                        txt = f"{(mult - 1) * 100:+.0f}%"
                ax.text(
                    c,
                    r,
                    txt,
                    ha="center",
                    va="center",
                    fontsize=6.5,
                    color="white" if abs(v) > vmax * 0.55 else INK,
                )

    cbar = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cbar.set_label(
        "log2(IA / MI) max solvable cells   (+1 → 2×, −1 → ½)",
        color=INK_SECONDARY,
        fontsize=8.5,
    )
    cbar.ax.tick_params(colors=MUTED, labelsize=8)
    cbar.outline.set_visible(False)

    ax.set_title(
        f"Cell-count headroom from internal asserts, per engine {title_suffix}"
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _plot_scatter_facets(
    results: pl.DataFrame,
    out_path: Path,
    group_col: str = "benchmark",
    title_suffix: str = "(all benchmarks)",
) -> Path | None:
    pts = _mi_ia_points(results, group_col).with_columns(
        pl.col("max_cells_miter").clip(lower_bound=1).alias("mi"),
        pl.col("max_cells_internal_asserts").clip(lower_bound=1).alias("ia"),
    )
    if pts.is_empty():
        return None

    tasks = sorted(pts["task"].unique().to_list())
    lo = min(pts["mi"].min(), pts["ia"].min()) * 0.7
    hi = max(pts["mi"].max(), pts["ia"].max()) * 1.4

    fig, axes, spare = _facet_grid(len(tasks), panel_w=3.6, panel_h=3.6)
    for ax, task in zip(axes, tasks):
        _apply_chrome(fig, ax)
        sub = pts.filter(pl.col("task") == task)
        mi = sub["mi"].to_numpy()
        ia = sub["ia"].to_numpy()
        for mask, color in zip(
            _win_loss_masks(mi, ia), (MUTED, COLOR_INTERNAL_ASSERTS, COLOR_MITER)
        ):
            ax.scatter(
                mi[mask],
                ia[mask],
                s=22,
                color=color,
                alpha=0.7,
                edgecolors=SURFACE,
                linewidths=0.4,
                zorder=3,
            )
        ax.plot([lo, hi], [lo, hi], color=AXIS, linewidth=1, linestyle="--", zorder=2)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlim(lo, hi)
        ax.set_ylim(lo, hi)
        ax.set_aspect("equal", adjustable="box")
        ax.grid(True, which="both", color=GRID, linewidth=0.5, zorder=0)
        ax.tick_params(labelbottom=True)
        ax.set_title(task, fontsize=9)

    handles = [
        Line2D(
            [0],
            [0],
            marker="o",
            ls="",
            color=COLOR_INTERNAL_ASSERTS,
            label="IA solves more",
        ),
        Line2D([0], [0], marker="o", ls="", color=COLOR_MITER, label="MI solves more"),
        Line2D([0], [0], marker="o", ls="", color=MUTED, label="within 5%"),
    ]
    fig.supxlabel("Miter (MI): max cells solved (log scale)", color=INK_SECONDARY)
    fig.supylabel(
        "Internal asserts (IA): max cells solved (log scale)", color=INK_SECONDARY
    )
    fig.suptitle(f"MI vs. IA max cells solved, per engine {title_suffix}", color=INK)
    fig.tight_layout()
    _place_legend(fig, spare, handles, fontsize=8.5)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return out_path


def generate_plots(results: pl.DataFrame, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    candidates = [
        _plot_cell_diff_heatmap(
            results,
            out_dir / "all_benchmarks_cell_diff_heatmap.png",
            group_col="benchmark",
        ),
        _plot_scatter_facets(
            results, out_dir / "all_benchmarks_scatter.png", group_col="benchmark"
        ),
        _plot_task_design_bars(
            results, out_dir / "all_benchmarks_cells_bars.png", group_col="benchmark"
        ),
    ]
    return [p for p in candidates if p is not None]


def generate_cross_benchmark_plots(
    results: pl.DataFrame, out_dir: Path, group_col: str = "benchmark_dir"
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    candidates = [
        _plot_cell_diff_heatmap(
            results,
            out_dir / "suite_cell_diff_heatmap.png",
            group_col=group_col,
            title_suffix="(whole suite)",
        ),
        _plot_scatter_facets(
            results,
            out_dir / "suite_scatter.png",
            group_col=group_col,
            title_suffix="(whole suite)",
        ),
        _plot_task_design_bars(
            results,
            out_dir / "suite_cells_bars.png",
            group_col=group_col,
            title_suffix="(whole suite)",
        ),
    ]
    return [p for p in candidates if p is not None]
