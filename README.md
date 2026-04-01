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

The project now vendors the Mortal runtime assets locally under [vendor/README.md](/Users/sehouz/ZLTV/majsoul-auto-rating/vendor/README.md) and has an in-process wrapper:

- [mortal_runtime.py](/Users/sehouz/ZLTV/majsoul-auto-rating/mortal_runtime.py)
- [mortal_review.py](/Users/sehouz/ZLTV/majsoul-auto-rating/mortal_review.py)

These modules do not spawn the Mortal CLI. They load the model directly,
create `libriichi.mjai.Bot` sessions in-process, and can compute a lightweight
review result.

Vendored assets now include:

- Mortal Python runtime files
- `libriichi.so`
- `libriichi` Rust source
- `mortal.pth`
- GRP model

At the moment, Python package dependencies still need to exist in the active
environment, especially `torch`, `numpy`, `toml`, and a recent `protobuf`.
The project no longer needs to import code from `/Users/sehouz/Mahjang/Mortal`
at runtime.

The vendored Rust source has been validated with:

```bash
cd /Users/sehouz/ZLTV/majsoul-auto-rating/vendor/libriichi-src
env PYO3_PYTHON=/Users/sehouz/Mahjang/Mortal/.venv/bin/python cargo build --release --lib
```

`target/`, compiled extension binaries, and local model files are ignored by
git.

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
