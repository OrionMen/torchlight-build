import unittest

from crawler.fetch_manifest import request_url_for


class FetchUrlEncodingTest(unittest.TestCase):
    def test_path_percent_encoding(self):
        self.assertEqual(
            request_url_for("https://tlidb.com/cn/Vorax_Limb:_Head"),
            "https://tlidb.com/cn/Vorax_Limb%3A_Head",
        )
        self.assertEqual(
            request_url_for("https://tlidb.com/cn/Vorax_Limb%3A_Head"),
            "https://tlidb.com/cn/Vorax_Limb%3A_Head",
        )

    def test_space_unicode_query_fragment_and_slash(self):
        self.assertEqual(request_url_for("https://tlidb.com/cn/A B"), "https://tlidb.com/cn/A%20B")
        self.assertEqual(request_url_for("https://tlidb.com/cn/怒气"),
                         "https://tlidb.com/cn/%E6%80%92%E6%B0%94")
        self.assertEqual(request_url_for("https://tlidb.com/cn/A:B?q=怒气#part"),
                         "https://tlidb.com/cn/A%3AB?q=怒气")
        self.assertEqual(request_url_for("https://tlidb.com/cn/A/B"), "https://tlidb.com/cn/A/B")

    def test_plain_ascii_url_is_unchanged(self):
        self.assertEqual(request_url_for("https://tlidb.com/cn/STR_Helmet"),
                         "https://tlidb.com/cn/STR_Helmet")


if __name__ == "__main__":
    unittest.main()
