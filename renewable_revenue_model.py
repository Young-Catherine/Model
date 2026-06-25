from __future__ import annotations

import argparse
import csv
import json
import math
import warnings
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np


INPUT_SCHEMA_VERSION = "renewable_revenue_io_v1"
REQUIRED_FILES = {
    "generation_history": "generation_history.csv",
    "power_price": "power_price_scenario.csv",
    "green_premium": "green_premium_scenario.csv",
    "gec_price": "gec_price_scenario.csv",
}
GENERATION_CASES = {
    "p10": "generation_p10_mwh",
    "p50": "generation_p50_mwh",
    "p90": "generation_p90_mwh",
}
DEFAULT_GEC_ELIGIBLE_RATIO = 1.0
DEFAULT_GREEN_POWER_RATIO = 1.0
PALETTE = {
    "blue_main": "#0F4D92",
    "blue_secondary": "#3775BA",
    "green_2": "#AADCA9",
    "green_3": "#8BCF8B",
    "red_strong": "#B64342",
    "neutral": "#CFCECE",
    "dark": "#272727",
}
FACTOR_LABELS = {
    "power_price_and_generation": "发电量与电价",
    "green_power_premium": "绿电交易溢价",
    "gec_price": "绿证价格",
}


class RenewableInputs:
    def __init__(
        self,
        generation_history,
        power_price_scenarios,
        green_premium_scenarios,
        gec_price_scenarios,
        metadata,
    ):
        self.generation_history = generation_history
        self.power_price_scenarios = power_price_scenarios
        self.green_premium_scenarios = green_premium_scenarios
        self.gec_price_scenarios = gec_price_scenarios
        self.metadata = metadata


def read_csv_rows(path: Path) -> list[dict]:
    with Path(path).open("r", newline="", encoding="utf-8-sig") as f:
        return [{key: value.strip() for key, value in row.items()} for row in csv.DictReader(f)]


def parse_period(period: str) -> tuple[int, int]:
    try:
        year_text, month_text = period.split("-")
        year = int(year_text)
        month = int(month_text)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"period must use YYYY-MM format: {period}") from exc
    if month < 1 or month > 12:
        raise ValueError(f"period month must be 1-12: {period}")
    return year, month


def month_index(period: str) -> int:
    year, month = parse_period(period)
    return year * 12 + month


def coerce_float(row: dict, field: str, context: str, non_negative=True) -> float:
    try:
        value = float(row[field])
    except KeyError as exc:
        raise ValueError(f"{context} missing required column '{field}'") from exc
    except ValueError as exc:
        raise ValueError(f"{context} column '{field}' must be numeric") from exc
    if non_negative and value < 0:
        raise ValueError(f"{context} column '{field}' must be non-negative")
    return value


def coerce_int(row: dict, field: str, context: str) -> int:
    try:
        value = int(float(row[field]))
    except KeyError as exc:
        raise ValueError(f"{context} missing required column '{field}'") from exc
    except ValueError as exc:
        raise ValueError(f"{context} column '{field}' must be an integer") from exc
    return value


def validate_unique(rows: list[dict], key_fields: tuple[str, ...], context: str) -> None:
    seen = set()
    for row in rows:
        key = tuple(row[field] for field in key_fields)
        if key in seen:
            raise ValueError(f"{context} has duplicate key {dict(zip(key_fields, key))}")
        seen.add(key)


def validate_contiguous_periods(periods: list[str], context: str) -> None:
    ordered = sorted(set(periods), key=month_index)
    if not ordered:
        raise ValueError(f"{context} cannot be empty")
    for prev, cur in zip(ordered, ordered[1:]):
        if month_index(cur) - month_index(prev) != 1:
            raise ValueError(f"{context} periods must be monthly and contiguous")


def load_inputs(input_dir: str | Path) -> RenewableInputs:
    base = Path(input_dir)
    files = {name: base / filename for name, filename in REQUIRED_FILES.items()}
    missing = [str(path) for path in files.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing renewable revenue input files: " + ", ".join(missing))

    generation_history = []
    for row in read_csv_rows(files["generation_history"]):
        context = "generation_history.csv"
        period = row.get("period", "")
        parse_period(period)
        generation_history.append(
            {
                "period": period,
                "asset_id": row.get("asset_id", ""),
                "technology": row.get("technology", ""),
                "installed_capacity_mw": coerce_float(row, "installed_capacity_mw", context),
                "generation_mwh": coerce_float(row, "generation_mwh", context),
            }
        )
    if not generation_history:
        raise ValueError("generation_history.csv cannot be empty")
    validate_contiguous_periods([row["period"] for row in generation_history], "generation_history.csv")

    power_price_scenarios = []
    for row in read_csv_rows(files["power_price"]):
        context = "power_price_scenario.csv"
        period = row.get("period", "")
        parse_period(period)
        power_price_scenarios.append(
            {
                "period": period,
                "scenario": row.get("scenario", ""),
                "power_price_yuan_per_mwh": coerce_float(row, "power_price_yuan_per_mwh", context),
            }
        )
    validate_unique(power_price_scenarios, ("period", "scenario"), "power_price_scenario.csv")

    green_premium_scenarios = []
    for row in read_csv_rows(files["green_premium"]):
        context = "green_premium_scenario.csv"
        period = row.get("period", "")
        parse_period(period)
        green_premium_scenarios.append(
            {
                "period": period,
                "scenario": row.get("scenario", ""),
                "premium_yuan_per_mwh": coerce_float(row, "premium_yuan_per_mwh", context),
            }
        )
    validate_unique(green_premium_scenarios, ("period", "scenario"), "green_premium_scenario.csv")

    gec_price_scenarios = []
    for row in read_csv_rows(files["gec_price"]):
        context = "gec_price_scenario.csv"
        period = row.get("period", "")
        parse_period(period)
        gec_price_scenarios.append(
            {
                "period": period,
                "scenario": row.get("scenario", ""),
                "production_year": coerce_int(row, "production_year", context),
                "gec_price_yuan_per_certificate": coerce_float(row, "gec_price_yuan_per_certificate", context),
            }
        )
    validate_unique(gec_price_scenarios, ("period", "scenario", "production_year"), "gec_price_scenario.csv")

    for context, rows in [
        ("power_price_scenario.csv", power_price_scenarios),
        ("green_premium_scenario.csv", green_premium_scenarios),
        ("gec_price_scenario.csv", gec_price_scenarios),
    ]:
        if not rows:
            raise ValueError(f"{context} cannot be empty")
        validate_contiguous_periods([row["period"] for row in rows], context)

    return RenewableInputs(
        generation_history=generation_history,
        power_price_scenarios=power_price_scenarios,
        green_premium_scenarios=green_premium_scenarios,
        gec_price_scenarios=gec_price_scenarios,
        metadata={
            "schema_version": INPUT_SCHEMA_VERSION,
            "input_dir": str(base),
            "input_files": {name: str(path) for name, path in files.items()},
        },
    )


def forecast_generation(generation_history: list[dict], target_periods: list[str]) -> list[dict]:
    by_month = defaultdict(list)
    all_generation = []
    asset_ids = sorted({row["asset_id"] for row in generation_history if row["asset_id"]})
    technologies = sorted({row["technology"] for row in generation_history if row["technology"]})
    period_totals = defaultdict(float)
    period_capacities = defaultdict(float)
    for row in generation_history:
        period_totals[row["period"]] += row["generation_mwh"]
        period_capacities[row["period"]] += row["installed_capacity_mw"]

    for period, generation_mwh in period_totals.items():
        _, month = parse_period(period)
        by_month[month].append(generation_mwh)
        all_generation.append(generation_mwh)

    global_mean = float(np.mean(all_generation))
    global_std = float(np.std(all_generation, ddof=1)) if len(all_generation) > 1 else max(global_mean * 0.08, 1.0)
    portfolio_capacity = max(period_capacities.values()) if period_capacities else 0.0
    forecast = []
    for period in sorted(target_periods, key=month_index):
        _, month = parse_period(period)
        month_values = by_month.get(month, [])
        p50 = float(np.mean(month_values)) if month_values else global_mean
        if len(month_values) > 1:
            error_std = float(np.std(month_values, ddof=1))
        else:
            error_std = max(global_std * 0.5, p50 * 0.08, 1.0)
        p10 = max(0.0, p50 - 1.2815515655446004 * error_std)
        p90 = p50 + 1.2815515655446004 * error_std
        forecast.append(
            {
                "period": period,
                "asset_id": asset_ids[0] if len(asset_ids) == 1 else "portfolio",
                "technology": technologies[0] if len(technologies) == 1 else "portfolio",
                "installed_capacity_mw": float(portfolio_capacity),
                "generation_p10_mwh": p10,
                "generation_p50_mwh": p50,
                "generation_p90_mwh": p90,
                "generation_error_std_mwh": error_std,
            }
        )
    return forecast


def scenario_lookup(rows: list[dict], value_field: str) -> dict:
    return {(row["period"], row["scenario"]): row[value_field] for row in rows}


def build_scenario_inputs(inputs: RenewableInputs) -> list[dict]:
    target_periods = sorted({row["period"] for row in inputs.power_price_scenarios}, key=month_index)
    forecast_rows = forecast_generation(inputs.generation_history, target_periods)
    forecast_by_period = {row["period"]: row for row in forecast_rows}
    power_lookup = scenario_lookup(inputs.power_price_scenarios, "power_price_yuan_per_mwh")
    premium_lookup = scenario_lookup(inputs.green_premium_scenarios, "premium_yuan_per_mwh")
    gec_lookup = {
        (row["period"], row["scenario"], row["production_year"]): row["gec_price_yuan_per_certificate"]
        for row in inputs.gec_price_scenarios
    }

    market_keys = set(power_lookup) & set(premium_lookup)
    gec_keys = {(period, scenario) for period, scenario, _production_year in gec_lookup}
    common_keys = sorted(market_keys & gec_keys, key=lambda key: (month_index(key[0]), key[1]))
    if not common_keys:
        raise ValueError("No common period + scenario keys across market scenario inputs")

    scenarios = []
    for period, scenario in common_keys:
        production_years = sorted(
            production_year
            for gec_period, gec_scenario, production_year in gec_lookup
            if gec_period == period and gec_scenario == scenario
        )
        for generation_case, generation_field in GENERATION_CASES.items():
            forecast = forecast_by_period[period]
            for production_year in production_years:
                scenarios.append(
                    {
                        "period": period,
                        "scenario": scenario,
                        "generation_case": generation_case,
                        "asset_id": forecast["asset_id"],
                        "technology": forecast["technology"],
                        "installed_capacity_mw": forecast["installed_capacity_mw"],
                        "generation_mwh": forecast[generation_field],
                        "power_price_yuan_per_mwh": power_lookup[(period, scenario)],
                        "premium_yuan_per_mwh": premium_lookup[(period, scenario)],
                        "gec_price_yuan_per_certificate": gec_lookup[(period, scenario, production_year)],
                        "production_year": production_year,
                        "gec_eligible_ratio": DEFAULT_GEC_ELIGIBLE_RATIO,
                        "green_power_ratio": DEFAULT_GREEN_POWER_RATIO,
                    }
                )
    return scenarios


def calculate_revenue_scenarios(scenarios: list[dict]) -> list[dict]:
    results = []
    for row in scenarios:
        generation_mwh = float(row["generation_mwh"])
        power_price = float(row["power_price_yuan_per_mwh"])
        premium = float(row["premium_yuan_per_mwh"])
        gec_price = float(row["gec_price_yuan_per_certificate"])
        gec_eligible_ratio = float(row.get("gec_eligible_ratio", DEFAULT_GEC_ELIGIBLE_RATIO))
        green_power_ratio = float(row.get("green_power_ratio", DEFAULT_GREEN_POWER_RATIO))
        if green_power_ratio + gec_eligible_ratio > 1.0 + 1e-9:
            warnings.warn(
                "Potential green power premium and GEC double counting: "
                f"period={row.get('period')}, scenario={row.get('scenario')}, "
                f"green_power_ratio={green_power_ratio}, gec_eligible_ratio={gec_eligible_ratio}. "
                "Domestic green power trades transfer bundled GECs with the electricity; "
                "use green_power_ratio + gec_eligible_ratio <= 1.0 for non-overlapping settlement.",
                UserWarning,
                stacklevel=2,
            )

        power_revenue = generation_mwh * power_price
        green_premium_revenue = generation_mwh * green_power_ratio * premium
        gec_certificates = generation_mwh * gec_eligible_ratio
        gec_revenue = gec_certificates * gec_price
        total_revenue = power_revenue + green_premium_revenue + gec_revenue
        results.append(
            {
                **row,
                "gec_certificates": gec_certificates,
                "power_revenue_yuan": power_revenue,
                "green_premium_revenue_yuan": green_premium_revenue,
                "gec_revenue_yuan": gec_revenue,
                "total_revenue_yuan": total_revenue,
            }
        )
    return results


def percentile(values: list[float], pct: float) -> float:
    return float(np.percentile(np.array(values, dtype=float), pct))


def summarize_results(results: list[dict], metadata: dict) -> dict:
    totals = [row["total_revenue_yuan"] for row in results]
    sorted_totals = sorted(totals)
    var_10 = percentile(totals, 10)
    cvar_10_values = [value for value in sorted_totals if value <= var_10]
    component_totals = {
        "power_revenue_yuan": sum(row["power_revenue_yuan"] for row in results),
        "green_premium_revenue_yuan": sum(row["green_premium_revenue_yuan"] for row in results),
        "gec_revenue_yuan": sum(row["gec_revenue_yuan"] for row in results),
    }
    total_components = sum(component_totals.values()) or 1.0
    sensitivity = [
        {
            "factor": "power_price_and_generation",
            "contribution_ratio": component_totals["power_revenue_yuan"] / total_components,
        },
        {
            "factor": "green_power_premium",
            "contribution_ratio": component_totals["green_premium_revenue_yuan"] / total_components,
        },
        {
            "factor": "gec_price",
            "contribution_ratio": component_totals["gec_revenue_yuan"] / total_components,
        },
    ]
    sensitivity.sort(key=lambda row: row["contribution_ratio"], reverse=True)

    periods = sorted({row["period"] for row in results}, key=month_index)
    scenarios = sorted({row["scenario"] for row in results})
    return {
        "schema_version": INPUT_SCHEMA_VERSION,
        "metadata": metadata,
        "scenario_count": len(results),
        "periods": periods,
        "scenarios": scenarios,
        "metrics": {
            "expected_total_revenue_yuan": float(np.mean(totals)),
            "p10_total_revenue_yuan": percentile(totals, 10),
            "p50_total_revenue_yuan": percentile(totals, 50),
            "p90_total_revenue_yuan": percentile(totals, 90),
            "var_10_total_revenue_yuan": var_10,
            "cvar_10_total_revenue_yuan": float(np.mean(cvar_10_values)) if cvar_10_values else var_10,
            "total_revenue_std_yuan": float(np.std(totals, ddof=1)) if len(totals) > 1 else 0.0,
            "power_revenue_share": component_totals["power_revenue_yuan"] / total_components,
            "green_premium_revenue_share": component_totals["green_premium_revenue_yuan"] / total_components,
            "gec_revenue_share": component_totals["gec_revenue_yuan"] / total_components,
        },
        "sensitivity_rank": sensitivity,
        "assumptions": {
            "time_granularity": "monthly",
            "gec_certificate_rule": "1 certificate per 1 MWh renewable generation",
            "green_power_premium_and_gec_revenue_are_non_overlapping_only_when_ratios_sum_to_at_most_one": True,
            "gec_eligible_ratio": DEFAULT_GEC_ELIGIBLE_RATIO,
            "green_power_ratio": DEFAULT_GREEN_POWER_RATIO,
            "double_counting_warning_rule": "Warn when green_power_ratio + gec_eligible_ratio > 1.0",
        },
    }


def write_results_csv(path: Path, results: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "period",
        "scenario",
        "generation_case",
        "asset_id",
        "technology",
        "installed_capacity_mw",
        "generation_mwh",
        "power_price_yuan_per_mwh",
        "premium_yuan_per_mwh",
        "gec_price_yuan_per_certificate",
        "gec_certificates",
        "power_revenue_yuan",
        "green_premium_revenue_yuan",
        "gec_revenue_yuan",
        "total_revenue_yuan",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in fieldnames} for row in results)


def write_summary_json(path: Path, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


def apply_plot_style() -> None:
    plt.rcParams.update(
        {
            "font.family": ["Microsoft YaHei", "SimHei", "Arial", "DejaVu Sans", "sans-serif"],
            "font.size": 12,
            "axes.spines.right": False,
            "axes.spines.top": False,
            "axes.linewidth": 2.0,
            "legend.frameon": False,
            "axes.unicode_minus": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
        }
    )


def make_dashboard(results: list[dict], summary: dict, output_path: Path) -> None:
    apply_plot_style()
    p50_rows = [row for row in results if row["generation_case"] == "p50"]
    periods = sorted(summary["periods"], key=month_index)
    base_rows = [row for row in p50_rows if row["scenario"] == "base"]
    if not base_rows:
        base_rows = p50_rows
    base_by_period = {row["period"]: row for row in base_rows}

    fig, axes = plt.subplots(2, 2, figsize=(16, 10))

    x = np.arange(len(periods))
    power = [base_by_period[p]["power_revenue_yuan"] / 10000 for p in periods if p in base_by_period]
    premium = [base_by_period[p]["green_premium_revenue_yuan"] / 10000 for p in periods if p in base_by_period]
    gec = [base_by_period[p]["gec_revenue_yuan"] / 10000 for p in periods if p in base_by_period]
    x0 = np.arange(len(power))
    axes[0, 0].bar(x0, power, color=PALETTE["blue_main"], edgecolor="black", label="电能量收入")
    axes[0, 0].bar(x0, premium, bottom=power, color=PALETTE["green_3"], edgecolor="black", label="绿电溢价收入")
    axes[0, 0].bar(x0, gec, bottom=np.array(power) + np.array(premium), color=PALETTE["green_2"], edgecolor="black", label="绿证收入")
    axes[0, 0].set_ylabel("收益（万元）")
    axes[0, 0].set_xticks(x0)
    axes[0, 0].set_xticklabels([p.replace("-", ".") for p in periods if p in base_by_period], rotation=30, ha="right")
    axes[0, 0].grid(axis="y", alpha=0.2)
    axes[0, 0].legend(loc="upper left", ncol=1)

    totals = [row["total_revenue_yuan"] / 10000 for row in results]
    axes[0, 1].hist(totals, bins=min(12, max(4, int(math.sqrt(len(totals))))), color=PALETTE["blue_secondary"], edgecolor="black")
    axes[0, 1].axvline(summary["metrics"]["p10_total_revenue_yuan"] / 10000, color=PALETTE["red_strong"], linewidth=2.2, label="P10")
    axes[0, 1].axvline(summary["metrics"]["p50_total_revenue_yuan"] / 10000, color=PALETTE["dark"], linewidth=2.2, label="P50")
    axes[0, 1].axvline(summary["metrics"]["p90_total_revenue_yuan"] / 10000, color=PALETTE["green_3"], linewidth=2.2, label="P90")
    axes[0, 1].set_xlabel("总收益（万元）")
    axes[0, 1].set_ylabel("情景数量")
    axes[0, 1].legend(loc="upper right")
    axes[0, 1].grid(axis="y", alpha=0.2)

    forecast_by_case = defaultdict(dict)
    for row in results:
        if row["scenario"] == "base":
            forecast_by_case[row["generation_case"]][row["period"]] = row["total_revenue_yuan"] / 10000
    for case, color, label in [("p10", PALETTE["red_strong"], "P10"), ("p50", PALETTE["dark"], "P50"), ("p90", PALETTE["green_3"], "P90")]:
        y = [forecast_by_case[case].get(period, np.nan) for period in periods]
        axes[1, 0].plot(x, y, marker="o", linewidth=2.4, color=color, label=label)
    axes[1, 0].set_ylabel("总收益（万元）")
    axes[1, 0].set_xticks(x)
    axes[1, 0].set_xticklabels([p.replace("-", ".") for p in periods], rotation=30, ha="right")
    axes[1, 0].legend(loc="upper left", ncol=3)
    axes[1, 0].grid(axis="y", alpha=0.2)

    factors = [FACTOR_LABELS.get(row["factor"], row["factor"]) for row in summary["sensitivity_rank"]]
    ratios = [row["contribution_ratio"] for row in summary["sensitivity_rank"]]
    axes[1, 1].barh(factors, ratios, color=[PALETTE["blue_main"], PALETTE["green_3"], PALETTE["green_2"]], edgecolor="black")
    axes[1, 1].set_xlabel("收益贡献占比")
    axes[1, 1].set_xlim(0, max(1.0, max(ratios) * 1.15))
    axes[1, 1].xaxis.set_major_formatter(lambda value, _pos: f"{value:.0%}")
    axes[1, 1].grid(axis="x", alpha=0.2)
    for idx, value in enumerate(ratios):
        axes[1, 1].text(value + 0.01, idx, f"{value:.1%}", va="center", fontsize=10)

    fig.suptitle("新能源侧概率收益模型", x=0.02, ha="left", fontsize=20, fontweight="bold")
    fig.text(
        0.02,
        0.94,
        f"期望总收益 {summary['metrics']['expected_total_revenue_yuan'] / 10000:,.1f} 万元；"
        f"P10/P50/P90 = {summary['metrics']['p10_total_revenue_yuan'] / 10000:,.1f}/"
        f"{summary['metrics']['p50_total_revenue_yuan'] / 10000:,.1f}/"
        f"{summary['metrics']['p90_total_revenue_yuan'] / 10000:,.1f} 万元",
        ha="left",
        fontsize=12,
        color=PALETTE["dark"],
    )
    fig.tight_layout(rect=[0, 0, 1, 0.9], pad=1.6)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=300, bbox_inches="tight", pad_inches=0.08)
    fig.savefig(output_path.with_suffix(".pdf"), bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)


def run_model(input_dir: str | Path, export_dir: str | Path, make_plot=True) -> dict:
    inputs = load_inputs(input_dir)
    scenario_inputs = build_scenario_inputs(inputs)
    results = calculate_revenue_scenarios(scenario_inputs)
    summary = summarize_results(results, inputs.metadata)

    export_path = Path(export_dir)
    csv_path = export_path / "renewable_revenue_scenarios.csv"
    json_path = export_path / "renewable_revenue_summary.json"
    write_results_csv(csv_path, results)
    write_summary_json(json_path, summary)
    png_path = None
    if make_plot:
        png_path = export_path / "renewable_revenue_dashboard.png"
        make_dashboard(results, summary, png_path)

    return {
        "results": results,
        "summary": summary,
        "outputs": {
            "csv": str(csv_path),
            "json": str(json_path),
            "dashboard_png": str(png_path) if png_path else None,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Renewable-side probabilistic revenue model")
    parser.add_argument("--input-dir", default="inputs/renewable_revenue", help="Renewable revenue input CSV directory")
    parser.add_argument("--export-dir", default="validation_outputs/renewable_revenue", help="Output directory")
    parser.add_argument("--no-plot", action="store_true", help="Skip dashboard rendering")
    args = parser.parse_args()
    result = run_model(args.input_dir, args.export_dir, make_plot=not args.no_plot)
    summary = result["summary"]
    print("Renewable-side probabilistic revenue model")
    print(f"Scenario count: {summary['scenario_count']}")
    print(f"Expected total revenue: {summary['metrics']['expected_total_revenue_yuan']:,.2f} yuan")
    print(f"Outputs: {result['outputs']}")


if __name__ == "__main__":
    main()
