# Garmin Personal Podcasts

Google Drive → Vercel Blob sync with a private podcast RSS feed, built to
get personal audio onto a Garmin watch via [PlayRun](https://www.playrun.app/).

```
Google Drive → (hourly sync) → Vercel Blob → RSS feed → PlayRun → Garmin watch
```

## How it works

- A daily Vercel Cron lists audio files in a Drive folder
  via Service Account, diffs against a `manifest.json` in Blob storage, and
  incrementally uploads/deletes — resumable after timeouts, abort-on-partial
  Drive listings so files are never falsely deleted.
- `GET /api/feed?token=SECRET` serves RSS 2.0 with `<enclosure>` tags pointing
  at Blob URLs. PlayRun fetches once per episode and syncs to the watch.
- A Google-OAuth-gated dashboard shows storage usage, the feed URL, per-file
  audio players, a manual sync trigger, and alerts for files the Garmin can't
  play (Forerunner 970 supports MP3, M4A, M4B).

## Setup

Requires Python 3.14 and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync --group dev
```

### 1. Google Cloud (one-time)

- Enable the **Google Drive API**, create a **Service Account**, download its
  JSON key.
- Share a **regular My Drive folder** (not a Shared Drive) with the service
  account email as **Viewer**. New files inherit the share.
- Create an **OAuth 2.0 Web Application** credential for dashboard login
  (External, Testing mode; add your addresses as test users). Redirect URIs:
  `https://<app>.vercel.app/auth/callback`,
  `http://localhost:3000/auth/callback`.

### 2. Environment

Copy to `.env.local` (git-ignored) and to Vercel Project → Settings →
Environment Variables:

| Variable | Source |
|---|---|
| `GOOGLE_SA_JSON_B64` | `base64 -i sa-key.json \| tr -d '\n'` |
| `GOOGLE_DRIVE_FOLDER_ID` | Drive folder URL |
| `BLOB_READ_WRITE_TOKEN` | Blob store connection (auto-injected on Vercel) |
| `FEED_SECRET_TOKEN` | `secrets.token_urlsafe(32)` |
| `PODCAST_TITLE` / `PODCAST_BASE_URL` | Display name / deployed URL |
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | OAuth credential |
| `ALLOWED_EMAILS` | Comma-separated allowlist |
| `SESSION_SECRET_KEY` | `secrets.token_hex(32)` |
| `BLOB_QUOTA_MB` | Default `500` |

## Commands

```bash
uv run pytest tests/ -q   # full suite (99 tests)
uv run pytest tests/unit -q  # fast unit tests
uv run ruff check .       # lint
uv run ruff format .      # format
vercel dev -l 4000        # local dev (register :4000 callback first)
vercel --prod --yes       # deploy
```

## Layout

```
app.py                    # FastAPI entrypoint, routes only
podcast/
  config.py               # typed Settings (sole env reader)
  models.py               # DriveFile / ManifestEntry / SyncResult
  deps.py                 # injectable Settings / BlobStore / DriveClient
  auth/                   # service-account creds, OAuth flow, sessions
  drive/                  # Drive listing + streaming
  blob/                   # BlobStore protocol + Vercel implementation
  sync/                   # diff engine, lock, incremental manifest commits
  feed/                   # pure RSS builder
  compat.py               # Garmin playability checks
  web/                    # dashboard, auth + sync routes, templates
tests/                    # unit (pure logic, InMemoryBlobStore) + integration
```

Dependencies live in `pyproject.toml` + `uv.lock` (Vercel installs with uv —
no `requirements.txt`). Python version is pinned to 3.14 via
`.python-version` and `requires-python`.

## Notes

- Drive reports uppercase `.MP3` files as `audio/mp3` — allowlisted, don't
  remove it or those files silently stop syncing.
- MIME is the playability signal; Garmin also needs ID3 tags to list
  episodes, which no metadata check can verify.
- Hobby plan: cron runs daily (`0 0 * * *`); use Sync Now intraday.
