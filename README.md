# majsoul-auto-rating

Core library and tools for:
- capturing a fresh `access_token`
- querying recent paipu UUIDs by `uid` or `eid`
- converting Mahjong Soul replay records into MJAI events
- reviewing a user's recent ranked paipu with embedded Mortal

The repository is organized as:

- `majsoul_auto_rating/`: reusable core library
- `tools/`: manual runners for live queries and local inspection
- `tests/`: automated pytest coverage
- `vendor/`: vendored Mortal runtime assets

## Environment

Create the virtual environment with `uv`:

```bash
cd /Users/sehouz/ZLTV/majsoul-auto-rating
uv venv
uv sync --extra test
playwright install chromium
```

Run the automated tests with:

```bash
uv run pytest
```

## Capture Token

Open Majsoul in a browser and capture a fresh token after manual login:

```bash
uv run python tools/capture_access_token.py --server cn --output captured_token.json
```

If capture succeeds, the script prints JSON and can optionally save it.

## Query Recent Paipu

Use the captured JSON file directly:

```bash
uv run python tools/query_recent_paipu.py --token-file captured_token.json --uid 12345678
uv run python tools/query_recent_paipu.py --token-file captured_token.json --eid 87654321
```

Or pass a token explicitly:

```bash
uv run python tools/query_recent_paipu.py --access-token YOUR_TOKEN --uid 12345678
```

## MJAI Conversion

Convert an already parsed Mahjong Soul record JSON into MJAI events:

```bash
uv run python tools/convert_record_to_mjai.py /path/to/parsed_record.json
```

Save the MJAI log as JSON lines:

```bash
uv run python tools/convert_record_to_mjai.py \
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

The project vendors the Mortal runtime assets locally under
[`vendor/README.md`](./vendor/README.md) and exposes the in-process wrappers from
`majsoul_auto_rating.runtime` and `majsoul_auto_rating.review`.

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
uv run python tools/runtime_smoke.py --mjai-log /tmp/game.mjai.jsonl --player-id 0
```

By default the embedded runtime now mirrors Mortal's `train_play.default`
sampling parameters from `config.example.toml`:

- `boltzmann_epsilon = 0.005`
- `boltzmann_temp = 0.05`
- `top_p = 1.0`

Override them from the CLI when needed:

```bash
uv run python tools/runtime_smoke.py \
  --mjai-log /tmp/game.mjai.jsonl \
  --player-id 0 \
  --boltzmann-epsilon 0 \
  --boltzmann-temp 1 \
  --top-p 1
```

Run the lightweight in-process review:

```bash
uv run python tools/review_mjai_log.py --mjai-log /tmp/game.mjai.jsonl --player-id 0
```

## Recent User Rating

Review a user's recent ranked paipu end-to-end:

```bash
uv run python tools/query_recent_rating.py --token-file captured_token.json --uid 12345678 --count 20
```

This entry now only reviews 4-player ranked games.

You can also use `--eid` instead of `--uid`.

The output includes:

- per-game `rating` and `rating_percent`
- `average_rating` / `average_rating_percent`
- `aggregate_rating` / `aggregate_rating_percent`
- per-game failures if some paipu cannot be converted or reviewed

`rating` is kept as a `0..1` internal value, matching the upstream review core.
For human-readable score display, use `rating_percent`, which is `rating * 100`.

## Library Usage

The public import surface is exposed from `majsoul_auto_rating`:

```python
from majsoul_auto_rating import authenticated_client, fetch_and_review_recent_games
```

This keeps the core query/review logic reusable for future integrations like a
NoneBot2 plugin without coupling the library to any specific bot framework.
