import csv
import importlib.util
import json
import tempfile
import unittest
import warnings
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = REPO_ROOT / "renewable_revenue_model.py"


def load_model():
    spec = importlib.util.spec_from_file_location("renewable_revenue_model", MODEL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


class RenewableRevenueModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_model()

    def make_input_dir(self):
        tmp = tempfile.TemporaryDirectory()
        base = Path(tmp.name)
        generation_rows = []
        for year, factor in [(2024, 0.95), (2025, 1.05)]:
            for month in range(1, 13):
                generation_rows.append(
                    {
                        "period": f"{year}-{month:02d}",
                        "asset_id": "wind_base",
                        "technology": "wind",
                        "installed_capacity_mw": 100,
                        "generation_mwh": round((22000 + month * 100) * factor, 2),
                    }
                )
        write_csv(base / "generation_history.csv", generation_rows)
        write_csv(
            base / "power_price_scenario.csv",
            [
                {"period": "2026-01", "scenario": "low", "power_price_yuan_per_mwh": 280},
                {"period": "2026-01", "scenario": "base", "power_price_yuan_per_mwh": 320},
                {"period": "2026-01", "scenario": "high", "power_price_yuan_per_mwh": 360},
                {"period": "2026-02", "scenario": "low", "power_price_yuan_per_mwh": 285},
                {"period": "2026-02", "scenario": "base", "power_price_yuan_per_mwh": 325},
                {"period": "2026-02", "scenario": "high", "power_price_yuan_per_mwh": 365},
            ],
        )
        write_csv(
            base / "green_premium_scenario.csv",
            [
                {"period": "2026-01", "scenario": "low", "premium_yuan_per_mwh": 0},
                {"period": "2026-01", "scenario": "base", "premium_yuan_per_mwh": 20},
                {"period": "2026-01", "scenario": "high", "premium_yuan_per_mwh": 35},
                {"period": "2026-02", "scenario": "low", "premium_yuan_per_mwh": 0},
                {"period": "2026-02", "scenario": "base", "premium_yuan_per_mwh": 18},
                {"period": "2026-02", "scenario": "high", "premium_yuan_per_mwh": 32},
            ],
        )
        write_csv(
            base / "gec_price_scenario.csv",
            [
                {"period": "2026-01", "scenario": "low", "production_year": 2026, "gec_price_yuan_per_certificate": 4},
                {"period": "2026-01", "scenario": "base", "production_year": 2026, "gec_price_yuan_per_certificate": 6},
                {"period": "2026-01", "scenario": "high", "production_year": 2026, "gec_price_yuan_per_certificate": 8},
                {"period": "2026-02", "scenario": "low", "production_year": 2026, "gec_price_yuan_per_certificate": 4.2},
                {"period": "2026-02", "scenario": "base", "production_year": 2026, "gec_price_yuan_per_certificate": 6.2},
                {"period": "2026-02", "scenario": "high", "production_year": 2026, "gec_price_yuan_per_certificate": 8.2},
            ],
        )
        return tmp, base

    def test_validate_inputs_rejects_negative_market_values(self):
        tmp, base = self.make_input_dir()
        self.addCleanup(tmp.cleanup)
        with (base / "green_premium_scenario.csv").open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        rows[0]["premium_yuan_per_mwh"] = "-1"
        write_csv(base / "green_premium_scenario.csv", rows)

        with self.assertRaisesRegex(ValueError, "non-negative"):
            self.model.load_inputs(base)

    def test_validate_inputs_rejects_duplicate_period_scenario(self):
        tmp, base = self.make_input_dir()
        self.addCleanup(tmp.cleanup)
        with (base / "power_price_scenario.csv").open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        rows.append(dict(rows[0]))
        write_csv(base / "power_price_scenario.csv", rows)

        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.model.load_inputs(base)

    def test_generation_forecast_quantiles_are_ordered(self):
        tmp, base = self.make_input_dir()
        self.addCleanup(tmp.cleanup)
        inputs = self.model.load_inputs(base)

        forecast = self.model.forecast_generation(inputs.generation_history, ["2026-01", "2026-02"])

        self.assertEqual([row["period"] for row in forecast], ["2026-01", "2026-02"])
        for row in forecast:
            self.assertLessEqual(row["generation_p10_mwh"], row["generation_p50_mwh"])
            self.assertLessEqual(row["generation_p50_mwh"], row["generation_p90_mwh"])
            self.assertGreater(row["generation_error_std_mwh"], 0)

    def test_generation_forecast_sums_assets_before_monthly_average(self):
        generation_history = [
            {
                "period": "2025-01",
                "asset_id": "A",
                "technology": "wind",
                "installed_capacity_mw": 50,
                "generation_mwh": 100,
            },
            {
                "period": "2025-01",
                "asset_id": "B",
                "technology": "wind",
                "installed_capacity_mw": 50,
                "generation_mwh": 200,
            },
            {
                "period": "2025-02",
                "asset_id": "A",
                "technology": "wind",
                "installed_capacity_mw": 50,
                "generation_mwh": 110,
            },
            {
                "period": "2025-02",
                "asset_id": "B",
                "technology": "wind",
                "installed_capacity_mw": 50,
                "generation_mwh": 210,
            },
        ]

        forecast = self.model.forecast_generation(generation_history, ["2026-01", "2026-02"])

        self.assertEqual(forecast[0]["generation_p50_mwh"], 300)
        self.assertEqual(forecast[1]["generation_p50_mwh"], 320)
        self.assertEqual(forecast[0]["installed_capacity_mw"], 100)

    def test_build_scenario_inputs_keeps_distinct_gec_production_year_prices(self):
        inputs = self.model.RenewableInputs(
            generation_history=[
                {
                    "period": "2025-01",
                    "asset_id": "wind_base",
                    "technology": "wind",
                    "installed_capacity_mw": 100,
                    "generation_mwh": 1000,
                }
            ],
            power_price_scenarios=[
                {"period": "2026-01", "scenario": "base", "power_price_yuan_per_mwh": 300}
            ],
            green_premium_scenarios=[
                {"period": "2026-01", "scenario": "base", "premium_yuan_per_mwh": 20}
            ],
            gec_price_scenarios=[
                {
                    "period": "2026-01",
                    "scenario": "base",
                    "production_year": 2025,
                    "gec_price_yuan_per_certificate": 5,
                },
                {
                    "period": "2026-01",
                    "scenario": "base",
                    "production_year": 2026,
                    "gec_price_yuan_per_certificate": 8,
                },
            ],
            metadata={"schema_version": self.model.INPUT_SCHEMA_VERSION},
        )

        scenario_inputs = self.model.build_scenario_inputs(inputs)

        p50_rows = [row for row in scenario_inputs if row["generation_case"] == "p50"]
        prices_by_year = {
            row["production_year"]: row["gec_price_yuan_per_certificate"]
            for row in p50_rows
        }
        self.assertEqual(prices_by_year, {2025: 5, 2026: 8})

    def test_zero_green_markets_reduce_to_power_revenue(self):
        scenarios = [
            {
                "period": "2026-01",
                "scenario": "base",
                "generation_case": "p50",
                "generation_mwh": 1000,
                "power_price_yuan_per_mwh": 300,
                "premium_yuan_per_mwh": 0,
                "gec_price_yuan_per_certificate": 0,
                "gec_eligible_ratio": 1,
                "green_power_ratio": 0,
            }
        ]

        result = self.model.calculate_revenue_scenarios(scenarios)[0]

        self.assertEqual(result["power_revenue_yuan"], 300000)
        self.assertEqual(result["green_premium_revenue_yuan"], 0)
        self.assertEqual(result["gec_revenue_yuan"], 0)
        self.assertEqual(result["total_revenue_yuan"], 300000)

    def test_calculate_revenue_warns_when_green_power_and_gec_ratios_overlap(self):
        scenarios = [
            {
                "period": "2026-01",
                "scenario": "base",
                "generation_case": "p50",
                "generation_mwh": 1000,
                "power_price_yuan_per_mwh": 300,
                "premium_yuan_per_mwh": 20,
                "gec_price_yuan_per_certificate": 6,
                "gec_eligible_ratio": 1,
                "green_power_ratio": 1,
            }
        ]

        with self.assertWarnsRegex(UserWarning, "double counting"):
            self.model.calculate_revenue_scenarios(scenarios)

    def test_calculate_revenue_does_not_warn_when_green_power_and_gec_ratios_do_not_overlap(self):
        scenarios = [
            {
                "period": "2026-01",
                "scenario": "base",
                "generation_case": "p50",
                "generation_mwh": 1000,
                "power_price_yuan_per_mwh": 300,
                "premium_yuan_per_mwh": 20,
                "gec_price_yuan_per_certificate": 6,
                "gec_eligible_ratio": 0.4,
                "green_power_ratio": 0.6,
            }
        ]

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.model.calculate_revenue_scenarios(scenarios)

        self.assertEqual(caught, [])

    def test_revenue_increases_with_generation_gec_price_and_premium(self):
        base = {
            "period": "2026-01",
            "scenario": "base",
            "generation_case": "p50",
            "generation_mwh": 1000,
            "power_price_yuan_per_mwh": 300,
            "premium_yuan_per_mwh": 20,
            "gec_price_yuan_per_certificate": 6,
            "gec_eligible_ratio": 0.4,
            "green_power_ratio": 0.6,
        }
        higher_generation = dict(base, generation_mwh=1100)
        higher_gec = dict(base, gec_price_yuan_per_certificate=8)
        higher_premium = dict(base, premium_yuan_per_mwh=30)

        results = self.model.calculate_revenue_scenarios([base, higher_generation, higher_gec, higher_premium])

        self.assertGreater(results[1]["total_revenue_yuan"], results[0]["total_revenue_yuan"])
        self.assertGreater(results[2]["gec_revenue_yuan"], results[0]["gec_revenue_yuan"])
        self.assertGreater(results[2]["total_revenue_yuan"], results[0]["total_revenue_yuan"])
        self.assertGreater(results[3]["green_premium_revenue_yuan"], results[0]["green_premium_revenue_yuan"])
        self.assertGreater(results[3]["total_revenue_yuan"], results[0]["total_revenue_yuan"])

    def test_run_model_exports_csv_json_and_dashboard(self):
        tmp, base = self.make_input_dir()
        self.addCleanup(tmp.cleanup)
        out = base / "outputs"

        with self.assertWarnsRegex(UserWarning, "double counting"):
            result = self.model.run_model(base, out, make_plot=True)

        csv_path = out / "renewable_revenue_scenarios.csv"
        json_path = out / "renewable_revenue_summary.json"
        png_path = out / "renewable_revenue_dashboard.png"
        self.assertTrue(csv_path.exists())
        self.assertTrue(json_path.exists())
        self.assertTrue(png_path.exists())
        self.assertGreater(png_path.stat().st_size, 0)
        with csv_path.open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        with json_path.open(encoding="utf-8") as f:
            summary = json.load(f)
        self.assertEqual(len(rows), summary["scenario_count"])
        self.assertAlmostEqual(
            sum(float(row["total_revenue_yuan"]) for row in rows) / len(rows),
            summary["metrics"]["expected_total_revenue_yuan"],
            places=6,
        )
        self.assertLessEqual(summary["metrics"]["p10_total_revenue_yuan"], summary["metrics"]["p50_total_revenue_yuan"])
        self.assertLessEqual(summary["metrics"]["p50_total_revenue_yuan"], summary["metrics"]["p90_total_revenue_yuan"])
        self.assertEqual(result["summary"]["schema_version"], self.model.INPUT_SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
