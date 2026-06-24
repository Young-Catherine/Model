from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Polygon


PALETTE = {
    "blue_main": "#0F4D92",
    "blue_secondary": "#3775BA",
    "green_3": "#8BCF8B",
    "red_strong": "#B64342",
    "red_2": "#E9A6A1",
    "neutral": "#CFCECE",
    "teal": "#42949E",
    "violet": "#9A4D8E",
}


CHP_FOR = {
    "Unit 2": [(44.0, 0.0), (44.0, 15.9), (40.0, 75.0), (110.2, 135.6), (125.8, 32.4), (125.8, 0.0)],
    "Unit 3": [(20.0, 0.0), (10.0, 40.0), (45.0, 55.0), (60.0, 0.0)],
    "Unit 4": [(35.0, 0.0), (35.0, 20.0), (90.0, 45.0), (90.0, 25.0), (105.0, 0.0)],
}


def apply_publication_style():
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 13,
            "axes.spines.right": False,
            "axes.spines.top": False,
            "axes.linewidth": 2.0,
            "legend.frameon": False,
            "svg.fonttype": "none",
            "figure.facecolor": "white",
            "axes.facecolor": "white",
        }
    )


def load_results(path):
    df = pd.read_csv(path)
    df["short_case"] = df["case"].replace(
        {
            "Paper JAYA": "JAYA",
            "Paper Rao-3": "Rao-3",
            "Paper Hybrid CHPED": "Hybrid",
            "This reproduction": "Reproduction",
        }
    )
    return df


def plot_cost_panel(ax, df):
    colors = [PALETTE["neutral"], PALETTE["neutral"], PALETTE["red_2"], PALETTE["blue_main"]]
    bars = ax.bar(df["short_case"], df["recalculated_cost"], color=colors, edgecolor="black", linewidth=1.5)
    paper_hybrid = df.loc[df["short_case"] == "Hybrid", "reported_min_cost"].iloc[0]
    ax.axhline(paper_hybrid, color=PALETTE["red_strong"], linewidth=2.5, linestyle="--", label="Paper reported min")
    ax.set_ylabel("Cost ($/h)")
    ax.set_title("A. Cost Recalculation vs Reproduction", loc="left", fontweight="bold")
    y_min = df["recalculated_cost"].min() - 120
    y_max = max(df["recalculated_cost"].max(), paper_hybrid) + 120
    ax.set_ylim(y_min, y_max)
    ax.tick_params(axis="x", rotation=20)
    for bar in bars:
        value = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + 15,
            f"{value:,.1f}",
            ha="center",
            va="bottom",
            fontsize=10,
        )
    ax.legend(loc="upper right")


def plot_dispatch_panel(ax, df, prefix, units, title, ylabel):
    x = np.arange(len(units))
    width = 0.18
    cases = ["JAYA", "Rao-3", "Hybrid", "Reproduction"]
    colors = [PALETTE["neutral"], PALETTE["teal"], PALETTE["red_2"], PALETTE["blue_main"]]
    hatches = ["", "\\\\", "//", ""]
    for idx, case in enumerate(cases):
        row = df[df["short_case"] == case].iloc[0]
        values = [row[f"{prefix}{unit}"] for unit in units]
        ax.bar(
            x + (idx - 1.5) * width,
            values,
            width,
            label=case,
            color=colors[idx],
            edgecolor="black",
            linewidth=1.0,
            hatch=hatches[idx],
        )
    ax.set_xticks(x)
    ax.set_xticklabels([f"{prefix}{unit}" for unit in units])
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left", fontweight="bold")
    ax.grid(axis="y", alpha=0.25, linewidth=0.8)


def plot_for_panel(ax, df):
    unit_colors = {
        "Unit 2": PALETTE["green_3"],
        "Unit 3": PALETTE["teal"],
        "Unit 4": PALETTE["violet"],
    }
    for unit_name, points in CHP_FOR.items():
        patch = Polygon(
            points,
            closed=True,
            facecolor=unit_colors[unit_name],
            edgecolor="black",
            linewidth=1.4,
            alpha=0.22,
            label=f"{unit_name} FOR",
        )
        ax.add_patch(patch)
        pts = np.array(points + [points[0]])
        ax.plot(pts[:, 0], pts[:, 1], color="black", linewidth=1.2, alpha=0.65)

    marker_styles = {
        "Hybrid": {"marker": "o", "color": PALETTE["red_strong"], "label": "Paper Hybrid"},
        "Reproduction": {"marker": "s", "color": PALETTE["blue_main"], "label": "Reproduction"},
    }
    unit_ids = [2, 3, 4]
    for case, style in marker_styles.items():
        row = df[df["short_case"] == case].iloc[0]
        for unit_id in unit_ids:
            ax.scatter(
                row[f"P{unit_id}"],
                row[f"H{unit_id}"],
                s=95,
                marker=style["marker"],
                color=style["color"],
                edgecolor="black",
                linewidth=1.1,
                zorder=5,
                label=style["label"] if unit_id == 2 else None,
            )
            ax.annotate(
                f"U{unit_id}",
                (row[f"P{unit_id}"], row[f"H{unit_id}"]),
                textcoords="offset points",
                xytext=(5, 5),
                fontsize=9,
            )
    ax.set_xlabel("Power output P (MW)")
    ax.set_ylabel("Heat output H (MWth)")
    ax.set_title("D. CHP Feasible Operating Regions", loc="left", fontweight="bold")
    ax.set_xlim(0, 135)
    ax.set_ylim(0, 150)
    ax.grid(alpha=0.2, linewidth=0.8)
    ax.legend(loc="upper right", fontsize=9)


def make_figure(csv_path, out_dir):
    apply_publication_style()
    df = load_results(csv_path)

    fig = plt.figure(figsize=(16, 10), constrained_layout=True)
    gs = fig.add_gridspec(2, 2)
    ax_cost = fig.add_subplot(gs[0, 0])
    ax_power = fig.add_subplot(gs[0, 1])
    ax_heat = fig.add_subplot(gs[1, 0])
    ax_for = fig.add_subplot(gs[1, 1])

    plot_cost_panel(ax_cost, df)
    plot_dispatch_panel(ax_power, df, "P", [1, 2, 3, 4], "B. Electric Dispatch Comparison", "Power (MW)")
    plot_dispatch_panel(ax_heat, df, "H", [2, 3, 4, 5], "C. Heat Dispatch Comparison", "Heat (MWth)")
    plot_for_panel(ax_for, df)

    handles, labels = ax_power.get_legend_handles_labels()
    ax_power.legend(handles, labels, loc="upper right", ncol=2, fontsize=9)
    ax_heat.legend().remove()

    out_dir.mkdir(parents=True, exist_ok=True)
    png_path = out_dir / "mdpi_energies_2023_reproduction_summary.png"
    pdf_path = out_dir / "mdpi_energies_2023_reproduction_summary.pdf"
    fig.savefig(png_path, dpi=300, bbox_inches="tight", pad_inches=0.08)
    fig.savefig(pdf_path, bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)
    return png_path, pdf_path


def main():
    csv_path = Path("validation_outputs") / "mdpi_energies_2023" / "mdpi_energies_2023_reproduction.csv"
    out_dir = Path("figures") / "mdpi_energies_2023"
    png_path, pdf_path = make_figure(csv_path, out_dir)
    print(f"Saved {png_path}")
    print(f"Saved {pdf_path}")


if __name__ == "__main__":
    main()
