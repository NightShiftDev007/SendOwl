"""Stream-parse MySQL `INSERT IGNORE INTO \`db\`.\`table\` (...) VALUES (...);` dumps."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

_INSERT_RE = re.compile(
    r"^INSERT\s+IGNORE\s+INTO\s+`[^`]+`\.`(?P<table>[^`]+)`\s*\((?P<cols>[^)]+)\)\s*VALUES\s*\((?P<vals>.*)\)\s*;\s*$",
    re.IGNORECASE | re.DOTALL,
)


def _split_columns(cols_blob: str) -> list[str]:
    return [c.strip().strip("`") for c in cols_blob.split(",") if c.strip()]


def _parse_value_token(raw: str) -> Any:
    s = raw.strip()
    if not s or s.upper() == "NULL":
        return None
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        inner = s[1:-1]
        return (
            inner.replace("\\'", "'")
            .replace('\\"', '"')
            .replace("\\\\", "\\")
            .replace("\\n", "\n")
            .replace("\\r", "\r")
            .replace("\\t", "\t")
        )
    low = s.lower()
    if low in {"true", "false"}:
        return low == "true"
    try:
        if "." in s or "e" in low:
            return float(s)
        return int(s)
    except ValueError:
        return s


def split_sql_values(values_blob: str) -> list[Any]:
    """Split a VALUES(...) payload respecting quoted strings."""
    parts: list[str] = []
    buf: list[str] = []
    in_quote = False
    escape = False
    i = 0
    n = len(values_blob)
    while i < n:
        ch = values_blob[i]
        if in_quote:
            buf.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == "'":
                in_quote = False
            i += 1
            continue
        if ch == "'":
            in_quote = True
            buf.append(ch)
            i += 1
            continue
        if ch == ",":
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return [_parse_value_token(p) for p in parts]


def iter_insert_rows(path: Path) -> Iterator[tuple[str, list[str], list[Any]]]:
    """Yield (table, columns, values) for each INSERT IGNORE line."""
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line or not line.upper().startswith("INSERT"):
                continue
            m = _INSERT_RE.match(line)
            if not m:
                # Multi-line inserts are not expected in this dump format.
                continue
            table = m.group("table")
            cols = _split_columns(m.group("cols"))
            vals = split_sql_values(m.group("vals"))
            if len(vals) != len(cols):
                raise ValueError(
                    f"{path.name}:{line_no}: column/value mismatch "
                    f"{len(cols)} cols vs {len(vals)} vals"
                )
            yield table, cols, vals


def find_part_files(dump_root: Path, table: str) -> list[Path]:
    data_dir = dump_root / table / "data"
    if not data_dir.is_dir():
        return []
    return sorted(data_dir.glob(f"{table}_*_part*.sql"))
