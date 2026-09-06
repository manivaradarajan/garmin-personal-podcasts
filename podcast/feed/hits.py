"""Feed fetch log — who requested the RSS feed and when.

Stored as a capped JSON list in Blob storage so the dashboard can show
whether clients like PlayRun are actually polling the feed. All helpers
are best-effort: logging must never break feed serving.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from podcast.blob.protocol import BlobStore

__all__ = ["FeedHit", "read_feed_hits", "record_feed_hit"]

_LOG = logging.getLogger(__name__)
_HITS_PATH = "feed-hits.json"
_MAX_HITS = 50
_MAX_UA_CHARS = 120


@dataclass(frozen=True)
class FeedHit:
    """One recorded feed request.

    Attributes:
        timestamp: ISO 8601 UTC of the request.
        user_agent: Client User-Agent header, truncated. Never a token.
        status: HTTP status served (200 or 403).
    """

    timestamp: str
    user_agent: str
    status: int


def record_feed_hit(
    blob_store: BlobStore, user_agent: str | None, status: int
) -> None:
    """Append a feed hit; swallow all errors.

    Args:
        blob_store: Blob storage implementation.
        user_agent: Raw User-Agent header value, or None if absent.
        status: HTTP status code served for the request.
    """
    try:
        hits = read_feed_hits(blob_store)
        hits.append(
            FeedHit(
                timestamp=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                user_agent=(user_agent or "-")[:_MAX_UA_CHARS],
                status=status,
            )
        )
        payload = {
            "entries": [
                {
                    "timestamp": h.timestamp,
                    "user_agent": h.user_agent,
                    "status": h.status,
                }
                for h in hits[-_MAX_HITS:]
            ]
        }
        blob_store.write(
            _HITS_PATH, json.dumps(payload).encode(), cache_max_age=60
        )
    except Exception as exc:
        _LOG.warning("Failed to record feed hit: %s", exc)


def read_feed_hits(blob_store: BlobStore) -> list[FeedHit]:
    """Read recorded feed hits, newest last.

    Args:
        blob_store: Blob storage implementation.

    Returns:
        Recorded hits, or an empty list on any problem.
    """
    try:
        raw = blob_store.read(_HITS_PATH, use_cache=False)
        if raw is None:
            return []
        payload = json.loads(raw)
        return [
            FeedHit(
                timestamp=str(e.get("timestamp", "")),
                user_agent=str(e.get("user_agent", "")),
                status=int(e.get("status", 0)),
            )
            for e in payload.get("entries", [])
        ]
    except Exception as exc:
        _LOG.warning("Failed to read feed hits: %s", exc)
        return []
