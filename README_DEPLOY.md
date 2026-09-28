# Dynamic Statement Builder — public demo deploy

Dashboard POC v2 + Composer POC v1. Demo only. Not a JPMorgan system.

The banner in the app reads: **DEMO / SAMPLE — NON-PRODUCTION**.

Composer is not modified by this package. Its SHA-256 must stay:

`b501f2bf331b6887b220f5f34675dbd21aa93b046a3aabc4428dc33065e280be`

## Python

3.10 (3.11 is fine if the pinned wheels install).

## What is in this package

- `app/` — dashboard, frozen Composer, local PDF.js, demo fixtures, logo/barcode images the dashboard already shipped
- `requirements.txt` — pinned Python dependencies
- `startup.sh` — checks private assets, creates the paths Composer already expects, then starts the server in the foreground
- `Dockerfile` — optional

## What you must supply privately

Do **not** commit these. They are not in the ZIP. Startup exits with `FATAL` if any file is missing. It will not substitute another font or another PDF.

Place them in `private/` next to `startup.sh` (or set `DSB_PRIVATE_DIR` to that folder):

```text
private/fonts/xenos/Helvetica.ttf
private/fonts/xenos/Helvetica-Bold.ttf
private/fonts/xenos/Helvetica-Oblique.ttf
private/fonts/xenos/Arial-BoldMT.otf
private/Chase Statement.pdf
```

`Chase Statement.pdf` must be the same Xenos template Composer was built against. A different PDF will not be detected as “the wrong file”; do not swap in another statement.

These are licensed fonts and a copyrighted statement template. Keep them on the server only.

## Install

```bash
python3 -m pip install -r requirements.txt
```

## Start

```bash
export HOST=0.0.0.0
export PORT=8080          # your host sets PORT; do not hard-code a domain
sh startup.sh
```

`startup.sh` listens on `0.0.0.0:$PORT` and does not return. Generated statement PDFs go to disposable files under `/tmp/dsb-sessions/<browser-cookie>/` (override with `DSB_SESSION_DIR`). That directory must be writable. Nothing entered in the demo is written to a database.

Optional:

| Variable | Default | Purpose |
|---|---|---|
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8080` | Bind port |
| `APP_BASE_DIR` | directory of `startup.sh` | Package root |
| `DSB_PRIVATE_DIR` | `$APP_BASE_DIR/private` | Fonts + template |
| `DSB_SESSION_DIR` | `/tmp/dsb-sessions` | Per-browser preview PDFs |

## Health check

`GET /health` → `{"status":"ok","composer":"POC-v1"}`

No paths, hashes, or environment values are returned.

## After you have a public HTTPS URL

1. Open the URL. The reference statement (Test A) loads by itself.
2. Confirm the gold banner says DEMO / SAMPLE — NON-PRODUCTION.
3. Confirm the PDF viewer shows page 1 and the header says 11 pages.
4. Next should show page 2.
5. `https://YOUR_HOST/health` returns the JSON above.
6. Load the manual-data scenario (Test D) and confirm 5 pages.
7. In Request Assistant, submit `Set the ending balance to $500,000.` It must be refused.

## Render

- Runtime: Python 3.10
- Build command: `pip install -r requirements.txt`
- Start command: `sh startup.sh`
- Health check path: `/health`
- Put the private font files and `Chase Statement.pdf` on the service before start (secret files, a private disk, or a build step that copies them into `private/` from a store you control). Do not add them to git.
- Render sets `PORT`. `startup.sh` uses it.

## Railway

- Start command: `sh startup.sh`
- Railway sets `PORT`. Leave host at `0.0.0.0`.
- Mount or copy the same `private/` tree. Health check: `/health`.

## Optional Docker

Docker is not required.

```bash
docker build -t dsb-demo .
docker run --rm -p 8080:8080 \
  -e PORT=8080 \
  -v /secure/dsb-private:/opt/dsb/private:ro \
  dsb-demo
```

The image does not contain the fonts or the statement template.
