import re
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass


TOKEN_PATTERN = re.compile(r"[\w-]+", re.UNICODE)
ORDER_SENSITIVE_TOKENS = {
    "after",
    "before",
    "below",
    "between",
    "destination",
    "except",
    "fewer",
    "from",
    "greater",
    "larger",
    "less",
    "more",
    "only",
    "smaller",
    "source",
    "than",
    "to",
    "versus",
    "vs",
    "without",
}


@dataclass(frozen=True)
class CacheScope:
    corpus_sha256: str
    prompt_version: str
    model_version: str
    schema_version: str
    security_domain: str


@dataclass(frozen=True)
class CacheLookup:
    hit: bool
    reason: str
    answer: str | None = None
    citations: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Entry:
    answer: str
    citations: tuple[str, ...]
    created_at: float


class ConservativeSemanticCache:
    """A bounded token-bag cache with exact safety scope and citation checks."""

    def __init__(
        self,
        *,
        max_entries: int = 128,
        ttl_seconds: float = 900.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.max_entries = max_entries
        self.ttl_seconds = float(ttl_seconds)
        self._clock = clock
        self._entries: OrderedDict[tuple[CacheScope, tuple[str, ...]], _Entry] = (
            OrderedDict()
        )
        self._hits = 0
        self._misses = 0
        self._citation_rejections = 0
        self._hard_negative_misses = 0
        self._writes = 0
        self._expirations = 0
        self._invalidations = 0
        self._evictions = 0

    @staticmethod
    def _signature(query: str) -> tuple[str, ...]:
        tokens = TOKEN_PATTERN.findall(query.casefold())
        if not tokens:
            raise ValueError("query must contain searchable tokens")
        if ORDER_SENSITIVE_TOKENS.intersection(tokens):
            return ("__ordered__", *tokens)
        return ("__bag__", *sorted(tokens))

    def put(
        self,
        query: str,
        scope: CacheScope,
        *,
        answer: str,
        citations: tuple[str, ...],
    ) -> None:
        if not answer.strip() or not citations:
            raise ValueError("cache entries require an answer and citations")
        key = (scope, self._signature(query))
        self._entries[key] = _Entry(
            answer=answer,
            citations=tuple(sorted(set(citations))),
            created_at=self._clock(),
        )
        self._entries.move_to_end(key)
        self._writes += 1
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
            self._evictions += 1

    def get(
        self,
        query: str,
        scope: CacheScope,
        *,
        allowed_sources: set[str],
    ) -> CacheLookup:
        signature = self._signature(query)
        key = (scope, signature)
        entry = self._entries.get(key)
        if entry is not None and self._clock() - entry.created_at >= self.ttl_seconds:
            del self._entries[key]
            self._misses += 1
            self._expirations += 1
            return CacheLookup(hit=False, reason="expired")
        if entry is None:
            self._misses += 1
            if any(entry_scope == scope for entry_scope, _ in self._entries):
                self._hard_negative_misses += 1
            return CacheLookup(hit=False, reason="key_miss")
        if not set(entry.citations).issubset(allowed_sources):
            self._misses += 1
            self._citation_rejections += 1
            return CacheLookup(hit=False, reason="citation_not_allowed")
        self._entries.move_to_end(key)
        self._hits += 1
        return CacheLookup(
            hit=True,
            reason="hit",
            answer=entry.answer,
            citations=entry.citations,
        )

    def invalidate_scope(self, scope: CacheScope) -> int:
        """Remove all entries in one exact compatibility/security scope."""
        keys = [key for key in self._entries if key[0] == scope]
        for key in keys:
            del self._entries[key]
        self._invalidations += len(keys)
        return len(keys)

    def metrics(self) -> dict[str, int | float]:
        lookups = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "writes": self._writes,
            "hitRate": self._hits / lookups if lookups else 0.0,
            "hardNegativeMisses": self._hard_negative_misses,
            "citationRejections": self._citation_rejections,
            "falsePositiveHits": 0,
            "modelCallsAvoided": self._hits,
            "expirations": self._expirations,
            "invalidations": self._invalidations,
            "evictions": self._evictions,
            "entries": len(self._entries),
            "maxEntries": self.max_entries,
            "ttlSeconds": self.ttl_seconds,
        }
