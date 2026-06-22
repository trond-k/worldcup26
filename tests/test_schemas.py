import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from common import load_all_teams, load_json
from validate import _validate_schema


class SchemaTests(unittest.TestCase):
    def test_all_schemas_are_valid_draft_7(self):
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            self.skipTest(str(exc))
        for path in (ROOT / "schema").glob("*.json"):
            Draft7Validator.check_schema(load_json(path))

    def test_team_schema_rejects_unknown_and_out_of_range_fields(self):
        bad = copy.deepcopy(load_all_teams()[0])
        bad["unknown_field"] = True
        bad["hdi"] = 99
        errors = []
        _validate_schema(bad, "team.schema.json", "test-team", errors)
        self.assertTrue(any("unknown_field" in error for error in errors), errors)
        self.assertTrue(any("maximum of 1" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
