import unittest

from crawler.audit_full_mirror_routes import canonical_web_path, classify_missing_route


class FullMirrorRouteAuditTest(unittest.TestCase):
    def test_inventory_wrong_namespace(self):
        expected = {"/cn/STR_Helmet", "/cn/Vorax_Limb%3A_Head"}
        self.assertEqual(classify_missing_route("/cn/Inventory/STR_Helmet", expected),
                         ("wrong_namespace", "/cn/STR_Helmet"))

    def test_nether_kings_wrong_directory(self):
        child = "/cn/Nether_Kings_Broken_Divinity%3A_Contamination"
        generated = "/cn/Nether_Kings_Broken_Divinity/Nether_Kings_Broken_Divinity%3A_Contamination"
        self.assertEqual(classify_missing_route(generated, {child}), ("wrong_directory", child))

    def test_encoding_is_canonicalized_stably(self):
        self.assertEqual(canonical_web_path("/cn/Vorax_Limb:_Head"), "/cn/Vorax_Limb%3A_Head")
        self.assertEqual(canonical_web_path("/cn/Vorax_Limb%3A_Head"), "/cn/Vorax_Limb%3A_Head")

    def test_duplicate_and_known_missing_are_distinct_audit_inputs(self):
        records = [
            {"expected": "/cn/Same", "known_missing": False},
            {"expected": "/cn/Same", "known_missing": False},
            {"expected": "/cn/Missing", "known_missing": True},
        ]
        duplicates = {item["expected"] for item in records
                      if sum(other["expected"] == item["expected"] for other in records) > 1}
        known_missing = {item["expected"] for item in records if item["known_missing"]}
        self.assertEqual(duplicates, {"/cn/Same"})
        self.assertEqual(known_missing, {"/cn/Missing"})


if __name__ == "__main__":
    unittest.main()
