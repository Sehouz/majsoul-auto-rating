"""Shared tool helpers for loading MJAI events and formatting JSON output."""

from __future__ import annotations

import json
from pathlib import Path

from majsoul_auto_rating import convert_parsed_record_to_mjai_events


def load_events(*, parsed_record: str | None = None, mjai_log: str | None = None) -> list[dict]:
    if bool(parsed_record) == bool(mjai_log):
        raise ValueError("exactly one of --parsed-record or --mjai-log is required")

    if parsed_record:
        with Path(parsed_record).open("r", encoding="utf-8") as handle:
            record = json.load(handle)
        return convert_parsed_record_to_mjai_events(record)

    events: list[dict] = []
    with Path(str(mjai_log)).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events
