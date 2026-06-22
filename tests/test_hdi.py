import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from common import load_all_teams
from convert_hdi import ALIASES
from seed_hdi import load_hdi


class HdiDatasetTests(unittest.TestCase):
    def test_normalized_dataset_and_team_mapping(self):
        values = load_hdi()
        self.assertEqual(len(values), 193)
        self.assertEqual(values["Norway"], 0.970)
        for team in load_all_teams():
            source_name = ALIASES.get(team["name"], team["name"])
            if team["slug"] == "curacao":
                self.assertNotIn(source_name, values)
            else:
                self.assertIn(source_name, values, team["name"])
                self.assertEqual(team["hdi"], values[source_name])
                self.assertEqual(team["hdi_year"], 2023)


if __name__ == "__main__":
    unittest.main()
