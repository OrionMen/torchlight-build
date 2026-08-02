import json
import unittest
from pathlib import Path

from engine.static_model import (
    CalculationContext,
    CapabilityContribution,
    Modifier,
    SourceTrace,
    aggregate_modifiers,
    calculate_extra_groups_multiplier,
    resolve_mechanic,
)


CASE_FILE = Path(__file__).resolve().parents[2] / "spec_cases/A001_A002_static_model_cases.json"


class FrozenCasesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(CASE_FILE.read_text(encoding="utf-8"))["cases"]

    def test_all_frozen_cases(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                if "context" in case:
                    context = CalculationContext(**case["context"])
                    result = aggregate_modifiers(
                        [Modifier(**item) for item in case["modifiers"]],
                        context,
                    )
                    self.assertEqual(set(result.node_values), set(case["expected"]))
                    for node, expected in case["expected"].items():
                        self.assertAlmostEqual(result.node_values[node], expected)
                elif "mechanic" in case:
                    result = resolve_mechanic(
                        mechanic_id=case["mechanic"]["id"],
                        base_maximum=case["mechanic"]["base_maximum"],
                        capability_sources=case["capability_sources"],
                        maximum_modifiers=case["maximum_modifiers"],
                    )
                    expected = case["expected"]
                    self.assertEqual(result.capability_available, expected["capability_available"])
                    self.assertAlmostEqual(result.effective_maximum, expected["effective_maximum"])
                    self.assertAlmostEqual(result.assumed_value, expected["assumed_value"])
                else:
                    self.assertAlmostEqual(
                        calculate_extra_groups_multiplier(case["groups"]),
                        case["expected_multiplier"],
                    )


class StaticModelBehaviorTest(unittest.TestCase):
    def test_all_any_none_filters_and_subtract(self):
        context = CalculationContext({"attack", "physical"}, "fire")
        modifiers = [
            Modifier("all", "stat.test", "shared", "add", 1, {"skill_tags_all": ["attack"]}),
            Modifier("any", "stat.test", "shared", "add", 2, {"skill_tags_any": ["cold", "physical"]}),
            Modifier("none", "stat.test", "shared", "add", 4, {"skill_tags_none": ["attack"]}),
            Modifier("subtract", "stat.test", "shared", "subtract", 0.5),
        ]
        result = aggregate_modifiers(modifiers, context)
        self.assertAlmostEqual(result.node_values["stat.test"], 2.5)
        rejected = next(item for item in result.trace if item.source_id == "none")
        self.assertFalse(rejected.matched)
        self.assertIn("skill_tags_none", rejected.rejection_reason)

    def test_aggregation_keys_remain_independent(self):
        context = CalculationContext({"attack"}, "physical")
        result = aggregate_modifiers(
            [
                Modifier("one", "damage.more", "hero.one", "add", 0.2),
                Modifier("two", "damage.more", "hero.two", "add", 0.4),
            ],
            context,
        )
        self.assertEqual(result.groups["damage.more"], {"hero.one": 0.2, "hero.two": 0.4})
        self.assertAlmostEqual(
            calculate_extra_groups_multiplier(result.groups["damage.more"]),
            1.68,
        )

    def test_filtered_capability_and_trace_source(self):
        source = CapabilityContribution(
            id="cap.focus",
            mechanic_id="mechanic.focus",
            filters={"skill_tags_all": ["spell"]},
            source=SourceTrace(original_text="获得专注祝福"),
        )
        result = resolve_mechanic(
            mechanic_id="mechanic.focus",
            base_maximum=4,
            capability_sources=[source],
            maximum_modifiers=[2],
            context=CalculationContext({"attack"}, "physical"),
        )
        self.assertFalse(result.capability_available)
        self.assertEqual(result.effective_maximum, 6)
        self.assertEqual(result.assumed_value, 0)
        self.assertEqual(result.trace[0].original_text, "获得专注祝福")
        self.assertFalse(result.trace[0].matched)


class StaticModelValidationTest(unittest.TestCase):
    def test_invalid_modifier_operation(self):
        with self.assertRaises(ValueError):
            Modifier("bad", "stat.test", "stat.test", "multiply", 1)

    def test_invalid_extra_group_multiplier(self):
        with self.assertRaises(ValueError):
            calculate_extra_groups_multiplier({"bad": [-1.1]})

    def test_invalid_mechanic_maximum(self):
        with self.assertRaises(ValueError):
            resolve_mechanic(
                mechanic_id="mechanic.test",
                base_maximum=1,
                capability_sources=[],
                maximum_modifiers=[-2],
            )


if __name__ == "__main__":
    unittest.main()
