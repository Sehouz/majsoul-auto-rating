# majsoul-auto-rating

Self-contained Majsoul utilities for:
- capturing a fresh `access_token`
- querying recent paipu UUIDs by `uid` or `username`

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
python test_recent_paipu_fetcher.py --token-file captured_token.json --username 某玩家 --count 5
```

Or pass a token explicitly:

```bash
python test_recent_paipu_fetcher.py --access-token YOUR_TOKEN --uid 12345678
```
