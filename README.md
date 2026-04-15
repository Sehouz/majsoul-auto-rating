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
create `libriichi.mjai.Bot` sessions in-process, and compute a lightweight
review result.

Vendored assets now include:

- Mortal Python runtime files
- `libriichi.so`
- `libriichi` Rust source
- `mortal.pth`
- optional `mortal.onnx`

Install exactly one backend environment at a time:

```bash
uv sync --extra test --extra torch
```

or:

```bash
uv sync --extra test --extra onnxruntime
```

The shared package dependencies still need to exist in the active environment,
including `numpy`, `toml`, and a recent `protobuf`.

For the ONNX Runtime backend, export the ONNX assets once from the Mortal
checkpoint:

```bash
uv run python tools/export_mortal_onnx.py
```

This writes:

- `vendor/models/mortal.onnx`

The ONNX metadata is embedded directly into the model file.
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

Use the ONNX Runtime backend instead:

```bash
uv run python tools/runtime_smoke.py --backend onnxruntime --mjai-log /tmp/game.mjai.jsonl --player-id 0
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

Backend selection is available on all runtime tools through `--backend`
(`torch` or `onnxruntime`).

For ONNX Runtime, the exported artifact is now a single file:

- `mortal.onnx`

with model metadata embedded directly into ONNX `metadata_props`.

## Publish Reviewer Reports

You can publish a generated reviewer report JSON to Aliyun OSS and receive both
the public JSON URL and a viewer URL.

Install the extra first:

```bash
uv sync --extra oss --extra torch
```

Example:

```bash
uv run python tools/publish_review_report.py \
  --parsed-record /tmp/game_record.json \
  --player-id 0 \
  --uuid 260414-37ae1c1e-de1f-4413-894d-6b81a036e8b6 \
  --backend onnxruntime \
  --onnx-model /opt/models/mortal.onnx \
  --oss-endpoint https://oss-cn-hangzhou.aliyuncs.com \
  --oss-bucket rabbitbot-report \
  --oss-access-key-id YOUR_KEY_ID \
  --oss-access-key-secret YOUR_KEY_SECRET \
  --oss-public-base-url https://rabbitbot.selenaz.cn \
  --viewer-base-url https://rabbitbot.selenaz.cn/killerducky/index.html
```

Object keys follow this pattern:

```text
report/majsoul/{date}/hash({uuid}_{player_id}_{model_suffix}).json
```

The filename stays short because only the hash is exposed in the URL. The model
and backend suffix are folded into the hash input and should be reflected in the
report's own model tag instead of the public filename.

Published objects are uploaded with `public-read` ACL by default so the returned
public URL and viewer URL can be opened directly.

## Packaging Modes

Build a torch-only wheel:

```bash
MAJSOUL_PACKAGE_BACKEND=torch uv build
```

Build an onnxruntime-only wheel:

```bash
MAJSOUL_PACKAGE_BACKEND=onnxruntime uv build
```

The build mode only affects packaged model assets:

- `torch` mode keeps `mortal.pth` and prunes ONNX files
- `onnxruntime` mode keeps `mortal.onnx` and prunes `mortal.pth`

Dependency installation is still controlled by the selected optional extra.

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
