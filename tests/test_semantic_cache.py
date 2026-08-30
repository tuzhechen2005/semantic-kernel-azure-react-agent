import unittest

from src.semantic_cache import CacheScope, ConservativeSemanticCache


class SemanticCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cache = ConservativeSemanticCache(max_entries=8)
        self.scope = CacheScope(
            corpus_sha256="corpus-v1",
            prompt_version="prompt-v1",
            model_version="phi3-v1",
            security_domain="public-docs",
        )
        self.source = "https://learn.microsoft.com/disk-types"

    def test_equivalent_token_order_hits_and_records_call_avoidance(self) -> None:
        self.cache.put(
            "standard hdd for backup",
            self.scope,
            answer="Use Standard HDD.",
            citations=(self.source,),
        )
        lookup = self.cache.get(
            "Backup: standard HDD for?",
            self.scope,
            allowed_sources={self.source},
        )

        self.assertTrue(lookup.hit)
        self.assertEqual(lookup.answer, "Use Standard HDD.")
        self.assertEqual(self.cache.metrics()["modelCallsAvoided"], 1)

    def test_scope_changes_never_hit(self) -> None:
        self.cache.put("disk backup", self.scope, answer="A", citations=(self.source,))
        for changed in (
            CacheScope("corpus-v2", "prompt-v1", "phi3-v1", "public-docs"),
            CacheScope("corpus-v1", "prompt-v2", "phi3-v1", "public-docs"),
            CacheScope("corpus-v1", "prompt-v1", "phi3-v2", "public-docs"),
            CacheScope("corpus-v1", "prompt-v1", "phi3-v1", "tenant-private"),
        ):
            with self.subTest(scope=changed):
                self.assertFalse(
                    self.cache.get("disk backup", changed, allowed_sources={self.source}).hit
                )

    def test_negation_numbers_and_parameters_are_hard_misses(self) -> None:
        self.cache.put(
            "retain backup for 30 days in eastus",
            self.scope,
            answer="A",
            citations=(self.source,),
        )
        for query in (
            "do not retain backup for 30 days in eastus",
            "retain backup for 31 days in eastus",
            "retain backup for 30 days in westus",
        ):
            with self.subTest(query=query):
                self.assertFalse(
                    self.cache.get(query, self.scope, allowed_sources={self.source}).hit
                )
        self.assertEqual(self.cache.metrics()["falsePositiveHits"], 0)

    def test_missing_current_citation_invalidates_entry(self) -> None:
        self.cache.put("disk backup", self.scope, answer="A", citations=(self.source,))
        lookup = self.cache.get(
            "disk backup", self.scope, allowed_sources={"https://learn.microsoft.com/other"}
        )
        self.assertFalse(lookup.hit)
        self.assertEqual(lookup.reason, "citation_not_allowed")


if __name__ == "__main__":
    unittest.main()
