"""Tests for BDD → SchemaMetadata converter."""

from app.converters.bdd_to_schema import bdd_to_schema
from app.models.bdd import BDDMetadata, BDDRule, BDDScenario


def test_basic_conversion():
    bdd = BDDMetadata(
        feature="User Registration",
        scenarios=[
            BDDScenario(
                name="Valid user",
                rules=[
                    BDDRule(field="age", condition=">18", result="pass"),
                    BDDRule(field="email", condition="valid_format", result="pass"),
                ],
            ),
        ],
    )
    schema = bdd_to_schema(bdd)
    assert len(schema.tables) == 1
    t = schema.tables[0]
    assert t.name == "bdd_data"
    cols = {c.name: c for c in t.columns}
    assert "age" in cols
    assert "email" in cols
    assert cols["age"].data_type == "INTEGER"
    assert cols["email"].data_type == "VARCHAR"


def test_empty_scenarios():
    bdd = BDDMetadata(feature="Empty", scenarios=[])
    schema = bdd_to_schema(bdd)
    assert schema.tables == []


def test_numeric_bounds():
    bdd = BDDMetadata(
        feature="Loan",
        scenarios=[
            BDDScenario(
                name="Amount check",
                rules=[
                    BDDRule(field="amount", condition=">100", result="pass"),
                    BDDRule(field="amount", condition="<10000", result="pass"),
                ],
            ),
        ],
    )
    schema = bdd_to_schema(bdd)
    col = schema.tables[0].columns[0]
    assert col.data_type == "INTEGER"
    assert col.check_constraint is not None


def test_null_conditions():
    bdd = BDDMetadata(
        feature="Nullable",
        scenarios=[
            BDDScenario(
                name="Null check",
                rules=[
                    BDDRule(field="phone", condition="null", result="pass"),
                ],
            ),
        ],
    )
    schema = bdd_to_schema(bdd)
    col = schema.tables[0].columns[0]
    assert col.nullable is True


def test_field_deduplication():
    """Same field from multiple rules should produce one column."""
    bdd = BDDMetadata(
        feature="Dedup",
        scenarios=[
            BDDScenario(
                name="A", rules=[BDDRule(field="age", condition=">0", result="pass")]
            ),
            BDDScenario(
                name="B", rules=[BDDRule(field="age", condition="<200", result="pass")]
            ),
        ],
    )
    schema = bdd_to_schema(bdd)
    assert len(schema.tables[0].columns) == 1
