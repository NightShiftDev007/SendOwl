"""Content addresses for native collection configuration."""

import json
from hashlib import sha256


def calculate_collection_config_sha256(
    mode: str,
    homepage_url: str,
    feed_url: str | None,
    poll_interval_seconds: int,
) -> str:
    encoded = json.dumps(
        {
            "schema_version": "sandowl-native-media-collection/v1",
            "mode": mode,
            "homepage_url": homepage_url,
            "feed_url": feed_url,
            "poll_interval_seconds": poll_interval_seconds,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(encoded.encode("utf-8")).hexdigest()
