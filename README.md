# majsoul-auto-rating

Self-contained Majsoul utilities for:
- capturing a fresh `access_token`
- querying recent paipu UUIDs by `uid` or `eid`
- converting Mahjong Soul replay records into MJAI events

The Mortal rating/review core is being rebuilt as an in-process module.
The old subprocess-heavy `mjai-reviewer` wrapper is intentionally not part of
the current architecture.

## Environment

Create the virtual environment with `uv`:

```bash
cd /Users/sehouz/ZLTV/majsoul-auto-rating
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
playwright install chromium
```

## Capture Token

Open Majsoul in a browser and capture a fresh token after manual login:

```bash
python capture_access_token.py --server cn --output captured_token.json
```

If capture succeeds, the script prints JSON and can optionally save it.

## Test Recent Paipu Lookup

Use the captured JSON file directly:

```bash
python test_recent_paipu_fetcher.py --token-file captured_token.json --uid 12345678
python test_recent_paipu_fetcher.py --token-file captured_token.json --eid 87654321
```

Or pass a token explicitly:

```bash
python test_recent_paipu_fetcher.py --access-token YOUR_TOKEN --uid 12345678
```

## MJAI Conversion

Convert an already parsed Mahjong Soul record JSON into MJAI events:

```bash
python test_majsoul_to_mjai.py /path/to/parsed_record.json
```

Save the MJAI log as JSON lines:

```bash
python test_majsoul_to_mjai.py \
  /path/to/parsed_record.json \
  --dump-output artifacts/game.mjai.jsonl
```

The converter currently supports the standard 4-player replay path built from:

- `RecordNewRound`
- `RecordDealTile`
- `RecordDiscardTile`
- `RecordChiPengGang`
- `RecordAnGangAddGang`
- `RecordHule`
- `RecordNoTile`

## Embedded Mortal Runtime

The project now has an in-process Mortal wrapper:

- [mortal_runtime.py](/Users/sehouz/ZLTV/majsoul-auto-rating/mortal_runtime.py)
- [mortal_review.py](/Users/sehouz/ZLTV/majsoul-auto-rating/mortal_review.py)

These modules do not spawn the Mortal CLI. They load the model directly,
create `libriichi.mjai.Bot` sessions in-process, and can compute a lightweight
review result.

At the moment, this requires a Python environment that already has Mortal's
runtime dependencies such as `torch`. The local project `.venv` is enough for
Majsoul protocol work, but not for model execution.

Smoke test the embedded runtime with an existing MJAI log:

```bash
PYTHONPATH=/Users/sehouz/ZLTV/majsoul-auto-rating \
  /Users/sehouz/Mahjang/Mortal/.venv/bin/python \
  test_mortal_runtime.py \
  --mjai-log /tmp/game.mjai.jsonl \
  --player-id 0
```

Run the lightweight in-process review:

```bash
PYTHONPATH=/Users/sehouz/ZLTV/majsoul-auto-rating \
  /Users/sehouz/Mahjang/Mortal/.venv/bin/python \
  test_mortal_review.py \
  --mjai-log /tmp/game.mjai.jsonl \
  --player-id 0
```
