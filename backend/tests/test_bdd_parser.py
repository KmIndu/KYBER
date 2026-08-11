import json
import pytest
from pathlib import Path

from app.parsers.bdd_parser import parse_bdd_feature
from app.models.bdd import BDDMetadata


FIXTURES = Path(__file__).parent / "fixtures"


def _load_feature() -> str:
    return (FIXTURES / "sample_rules.feature").read_text(encoding="utf-8")


# ── Basic parsing ──────────────────────────────────────────────


class TestBDDParserBasic:
    def test_returns_bdd_metadata(self):
        result = parse_bdd_feature(_load_feature())
        assert isinstance(result, BDDMetadata)

    def test_extracts_feature_name(self):
        result = parse_bdd_feature(_load_feature())
        assert result.feature == "Insurance Registration Validation"

    def test_scenario_count(self):
        result = parse_bdd_feature(_load_feature())
        assert len(result.scenarios) == 13

    def test_empty_input(self):
        result = parse_bdd_feature("")
        assert result.scenarios == []

    def test_comments_ignored(self):
        result = parse_bdd_feature("# just a comment\n# another one")
        assert result.scenarios == []

    def test_tags_ignored(self):
        text = "@smoke\nScenario: Test\n  Given user age is below 18\n  Then registration should fail"
        result = parse_bdd_feature(text)
        assert len(result.scenarios) == 1


# ── Less than / greater than ──────────────────────────────────


class TestComparisonConditions:
    def test_less_than(self):
        result = parse_bdd_feature(_load_feature())
        scenario = next(s for s in result.scenarios if s.name == "Underage user registration")
        assert len(scenario.rules) == 1
        rule = scenario.rules[0]
        assert rule.field == "age"
        assert rule.condition == "<18"
        assert rule.result == "fail"

    def test_greater_than(self):
        result = parse_bdd_feature(_load_feature())
        scenario = next(s for s in result.scenarios if s.name == "Senior citizen policy")
        rule = scenario.rules[0]
        assert rule.field == "age"
        assert rule.condition == ">65"
        assert rule.result == "pass"

    def test_high_claim(self):
        result = parse_bdd_feature(_load_feature())
        scenario = next(s for s in result.scenarios if s.name == "High claim amount requires approval")
        rule = scenario.rules[0]
        assert rule.field == "claim_amount"
        assert rule.condition == ">50000"
        assert rule.result == "requires_approval"

    def test_equal_to(self):
        result = parse_bdd_feature(_load_feature())
        scenario = next(s for s in result.scenarios if s.name == "Exact age boundary")
        rule = scenario.rules[0]
        assert rule.field == "age"
        assert rule.condition == "==18"
        assert rule.result == "pass"


# ── Null conditions ───────────────────────────────────────────


class TestNullConditions:
    def test_null(self):
        result = parse_bdd_feature(_load_feature())
        scenario = next(s for s in result.scenarios if s.name == "Null email registration")
        rule = scenario.rules[0]
        assert rule.field == "email"
        assert rule.condition == "null"
        assert rule.result == "fail"

    def test_empty(self):
        result = parse_bdd_feature(_load_feature())
        scenario = next(s for s in result.scenarios if s.name == "Null phone allowed")
        rule = scenario.rules[0]
        assert rule.field == "phone"
        assert rule.condition == "null"
        assert rule.result == "pass"

    def test_not_null(self):
        result = parse_bdd_feature(_load_feature())
        scenario = next(s for s in result.scenarios if s.name == "Not null check")
        fields = [r.field for r in scenario.rules]
        assert "name" in fields
        assert "email" in fields
        assert all(r.condition == "not_null" for r in scenario.rules)


# ── Duplicate conditions ──────────────────────────────────────


class TestDuplicateConditions:
    def test_duplicate(self):
        result = parse_bdd_feature(_load_feature())
        scenario = next(s for s in result.scenarios if s.name == "Duplicate email registration")
        rule = scenario.rules[0]
        assert rule.field == "email"
        assert rule.condition == "duplicate"
        assert rule.result == "fail"


# ── Invalid format conditions ─────────────────────────────────


class TestFormatConditions:
    def test_invalid_format(self):
        result = parse_bdd_feature(_load_feature())
        scenario = next(s for s in result.scenarios if s.name == "Invalid email format")
        rule = scenario.rules[0]
        assert rule.field == "email"
        assert rule.condition == "invalid_format"
        assert rule.result == "fail"

    def test_valid_format(self):
        result = parse_bdd_feature(_load_feature())
        scenario = next(s for s in result.scenarios if s.name == "Valid email format")
        rule = scenario.rules[0]
        assert rule.field == "email"
        assert rule.condition == "valid_format"
        assert rule.result == "pass"


# ── Range / between conditions ────────────────────────────────


class TestRangeConditions:
    def test_between(self):
        result = parse_bdd_feature(_load_feature())
        scenario = next(s for s in result.scenarios if s.name == "Premium within valid range")
        rule = scenario.rules[0]
        assert rule.field == "premium"
        assert rule.condition == "between(100,99999)"
        assert rule.result == "pass"


# ── Length conditions ─────────────────────────────────────────


class TestLengthConditions:
    def test_length_less_than(self):
        result = parse_bdd_feature(_load_feature())
        scenario = next(s for s in result.scenarios if s.name == "Short password rejected")
        rule = scenario.rules[0]
        assert rule.field == "password"
        assert rule.condition == "length<8"
        assert rule.result == "fail"

    def test_length_greater_than(self):
        result = parse_bdd_feature(_load_feature())
        scenario = next(s for s in result.scenarios if s.name == "Long password rejected")
        rule = scenario.rules[0]
        assert rule.field == "password"
        assert rule.condition == "length>128"
        assert rule.result == "fail"


# ── Raw steps preserved ──────────────────────────────────────


class TestRawSteps:
    def test_raw_steps_captured(self):
        result = parse_bdd_feature(_load_feature())
        scenario = next(s for s in result.scenarios if s.name == "Underage user registration")
        assert len(scenario.raw_steps) == 2
        assert any("age" in step.lower() for step in scenario.raw_steps)

    def test_multi_step_scenario(self):
        result = parse_bdd_feature(_load_feature())
        scenario = next(s for s in result.scenarios if s.name == "Not null check")
        assert len(scenario.raw_steps) == 3  # Given, And, Then


# ── Serialization ─────────────────────────────────────────────


class TestSerialization:
    def test_model_dump_is_serializable(self):
        result = parse_bdd_feature(_load_feature())
        data = result.model_dump()
        output = json.dumps(data, indent=2)
        assert '"scenarios"' in output
        assert '"rules"' in output

    def test_round_trip(self):
        result = parse_bdd_feature(_load_feature())
        data = result.model_dump()
        restored = BDDMetadata(**data)
        assert len(restored.scenarios) == len(result.scenarios)

    def test_sample_output_format(self):
        """Verify the exact output format from the requirements."""
        text = "Given user age is below 18\nThen registration fails"
        result = parse_bdd_feature(text)
        rule = result.scenarios[0].rules[0]
        assert rule.model_dump() == {
            "field": "age",
            "condition": "<18",
            "result": "fail",
        }
