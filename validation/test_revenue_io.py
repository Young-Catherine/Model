import importlib.util
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = REPO_ROOT / "Revenue model.py"
INPUT_DIR = REPO_ROOT / "inputs" / "revenue_model"


def load_revenue_model():
    spec = importlib.util.spec_from_file_location("revenue_model", MODEL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RevenueModelIOTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_revenue_model()

    def test_template_inputs_match_embedded_default_scenario(self):
        default = self.model.default_scenario()
        from_csv = self.model.load_scenario(INPUT_DIR)

        for section in ("unit_params", "cost_params", "carbon_params"):
            self.assertEqual(default[section], from_csv[section])
        self.assertEqual(default["lambda_e"], from_csv["lambda_e"])
        self.assertEqual(default["H_demand"], from_csv["H_demand"])
        self.assertEqual(from_csv["time_periods"], 24)
        self.assertEqual(from_csv["metadata"]["source"], "csv")

    def test_validate_scenario_rejects_mismatched_series_lengths(self):
        scenario = self.model.default_scenario()
        scenario["H_demand"] = scenario["H_demand"][:-1]

        with self.assertRaises(ValueError):
            self.model.validate_scenario(scenario)


if __name__ == "__main__":
    unittest.main()
