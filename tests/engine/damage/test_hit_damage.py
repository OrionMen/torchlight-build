import json
import unittest
from pathlib import Path

from engine.damage import Conversion, DamageComponent, Modifier, calculate_hit_damage


CASE_FILE = Path(__file__).resolve().parents[2] / "spec_cases/R001_hit_damage_cases.json"


def component_from_dict(data):
    return DamageComponent(**data)


def modifier_from_dict(data):
    return Modifier(**data)


def conversion_from_dict(data):
    return Conversion(**data) if data else None


class R001SpecCasesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(CASE_FILE.read_text(encoding="utf-8"))["cases"]

    def test_all_frozen_cases(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                result = calculate_hit_damage(
                    components=[component_from_dict(item) for item in case["components"]],
                    modifiers=[modifier_from_dict(item) for item in case["modifiers"]],
                    tags=case["tags"],
                    conversion=conversion_from_dict(case["conversion"]),
                )
                actual_by_type = {}
                for component in result.components:
                    actual_by_type[component.current_type] = (
                        actual_by_type.get(component.current_type, 0.0) + component.final_value
                    )
                self.assertEqual(set(case["expected"]["by_type"]), set(actual_by_type))
                for damage_type, expected in case["expected"]["by_type"].items():
                    self.assertAlmostEqual(actual_by_type[damage_type], expected)
                self.assertAlmostEqual(result.total_value, case["expected"]["total_value"])
                for damage_type, expected in case["expected"].get("history", {}).items():
                    histories = [
                        list(item.source_type_history)
                        for item in result.components
                        if item.current_type == damage_type
                    ]
                    self.assertIn(expected, histories)

    def test_modifier_requires_all_tags(self):
        result = calculate_hit_damage(
            components=[DamageComponent(100, "physical", ["physical"])],
            modifiers=[
                Modifier(
                    "increased",
                    1.0,
                    {"attack", "area"},
                    frozenset(),
                    "character_global",
                )
            ],
            tags={"attack"},
        )
        self.assertAlmostEqual(result.total_value, 100.0)

    def test_extra_group_order_and_trace_are_deterministic(self):
        arguments = {
            "components": [DamageComponent(100, "physical", ["physical"])],
            "modifiers": [
                Modifier("extra", 0.3, frozenset(), frozenset(), "character_global", extra_group="zeta"),
                Modifier("extra", 0.2, frozenset(), frozenset(), "character_global", extra_group="alpha"),
            ],
            "tags": {"hit"},
        }
        first = calculate_hit_damage(**arguments)
        second = calculate_hit_damage(**arguments)
        self.assertEqual(first.trace, second.trace)
        self.assertEqual(list(first.components[0].extra_groups), ["alpha", "zeta"])


class R001ValidationTest(unittest.TestCase):
    def test_component_validation(self):
        with self.assertRaises(ValueError):
            DamageComponent(-1, "physical", ["physical"])
        with self.assertRaises(ValueError):
            DamageComponent(1, "arcane", ["arcane"])
        with self.assertRaises(ValueError):
            DamageComponent(1, "fire", ["physical"])
        with self.assertRaises(ValueError):
            DamageComponent(1, "fire", ["fire", "fire"])

    def test_modifier_validation(self):
        with self.assertRaises(ValueError):
            Modifier("more", 0.5)
        with self.assertRaises(ValueError):
            Modifier("increased", 0.5, required_damage_types={"arcane"})
        with self.assertRaises(ValueError):
            Modifier("increased", 0.5, owner_scope="unknown")

    def test_conversion_ratio_validation(self):
        with self.assertRaises(ValueError):
            Conversion("physical", "fire", -0.01)
        with self.assertRaises(ValueError):
            Conversion("physical", "fire", 1.01)

    def test_multiple_conversions_rejected(self):
        with self.assertRaises(ValueError):
            calculate_hit_damage(
                components=[DamageComponent(100, "physical", ["physical"])],
                conversion=[
                    Conversion("physical", "fire", 0.5),
                    Conversion("physical", "cold", 0.5),
                ],
            )

    def test_negative_extra_multiplier_rejected(self):
        with self.assertRaises(ValueError):
            calculate_hit_damage(
                components=[DamageComponent(100, "physical", ["physical"])],
                modifiers=[Modifier("extra", -1.01, extra_group="invalid")],
            )


if __name__ == "__main__":
    unittest.main()
