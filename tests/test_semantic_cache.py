import unittest

from src.semantic_cache import CacheScope, ConservativeSemanticCache


class SemanticCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cache = ConservativeSemanticCache(max_entries=8)
        self.scope = CacheScope(
            corpus_sha256="corpus-v1",
            prompt_version="prompt-v1",
            model_version="phi3-v1",
            schema_version="answer-v1",
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
            CacheScope("corpus-v2", "prompt-v1", "phi3-v1", "answer-v1", "public-docs"),
            CacheScope("corpus-v1", "prompt-v2", "phi3-v1", "answer-v1", "public-docs"),
            CacheScope("corpus-v1", "prompt-v1", "phi3-v2", "answer-v1", "public-docs"),
            CacheScope("corpus-v1", "prompt-v1", "phi3-v1", "answer-v2", "public-docs"),
            CacheScope(
                "corpus-v1", "prompt-v1", "phi3-v1", "answer-v1", "tenant-private"
            ),
        ):
            with self.subTest(scope=changed):
                self.assertFalse(
                    self.cache.get(
                        "disk backup", changed, allowed_sources={self.source}
                    ).hit
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

    def test_relation_reversal_is_an_order_sensitive_hard_miss(self) -> None:
        self.cache.put(
            "is disk a larger than disk b",
            self.scope,
            answer="A",
            citations=(self.source,),
        )
        reversed_relation = self.cache.get(
            "is disk b larger than disk a",
            self.scope,
            allowed_sources={self.source},
        )
        self.assertFalse(reversed_relation.hit)
        self.assertEqual(reversed_relation.reason, "key_miss")

    def test_missing_current_citation_invalidates_entry(self) -> None:
        self.cache.put("disk backup", self.scope, answer="A", citations=(self.source,))
        lookup = self.cache.get(
            "disk backup",
            self.scope,
            allowed_sources={"https://learn.microsoft.com/other"},
        )
        self.assertFalse(lookup.hit)
        self.assertEqual(lookup.reason, "citation_not_allowed")

    def test_ttl_expiry_and_explicit_scope_invalidation_are_observable(self) -> None:
        current = [100.0]
        cache = ConservativeSemanticCache(
            max_entries=2,
            ttl_seconds=10,
            clock=lambda: current[0],
        )
        cache.put("disk backup", self.scope, answer="A", citations=(self.source,))
        self.assertTrue(
            cache.get("disk backup", self.scope, allowed_sources={self.source}).hit
        )

        current[0] = 111.0
        expired = cache.get("disk backup", self.scope, allowed_sources={self.source})
        self.assertFalse(expired.hit)
        self.assertEqual(expired.reason, "expired")
        self.assertEqual(cache.metrics()["expirations"], 1)

        cache.put("disk backup", self.scope, answer="A", citations=(self.source,))
        self.assertEqual(cache.invalidate_scope(self.scope), 1)
        self.assertEqual(cache.metrics()["invalidations"], 1)


if __name__ == "__main__":
    unittest.main()
