# Lessons

Hard-won findings from building and debugging this project. Check here
before re-diagnosing the same symptoms.

## Vercel Blob edge cache ignores busting tricks

**Symptom:** After writing `manifest.json`, immediate reads return the old
content — even with a `?_cb=<timestamp>` query param or `Cache-Control:
no-cache` / `Pragma: no-cache` request headers.

**Cause:** Vercel's edge cache honors only the blob's TTL, and loosely:
`?_cb=<timestamp>` query params and `Cache-Control: no-cache` request
headers do not bust it. Observed staleness exceeded 80 s despite
`cacheControlMaxAge=60` — wait minutes, not seconds, before trusting a
read after a write. Ground truth without edge interference: the `list`
API's `uploadedAt`/`size` fields.

**Proof:** A canary experiment (write `v1`, read, overwrite `v2`, read
immediately) showed writes persist fine — only reads lag, by up to ~60 s.

**Rules:**
- Never read-modify-write Blobs in a tight loop (migration scripts must
  tolerate staleness or space operations >60 s apart).
- The sync engine is safe: it reads the manifest once, then works from
  the in-memory copy.
- Don't trust a dashboard refresh within seconds of a sync; the flash
  message is the source of truth for what just happened.

## Drive reports uppercase .MP3 as audio/mp3

Files named `*.MP3` come back with MIME type `audio/mp3` (not `audio/mpeg`).
The sync query allowlists exact MIME strings, so these were silently
skipped. `audio/mp3` is permanently allowlisted — do not remove it.
Related: RSS enclosure `type` must be a registered IANA type, so the feed
builder canonicalises `audio/mp3` → `audio/mpeg` (and `audio/x-m4a` →
`audio/mp4`).

## Garmin watches need ID3 tags to list episodes

Untagged MP3s (raw MPEG frames from byte 0) collapse into a single entry
or vanish on the watch. Sync auto-prepends minimal ID3v2.3 tags
(title, album, genre, track number, length) to untagged MP3s; already-
tagged files pass through byte-identical. Use ID3v2.3, not v2.4 (older
firmware).
Caveat found while building this: `mutagen`'s `MP3.save()` to a file-like
object wrote tags without audio in our version — the code builds a fresh
`ID3` object and prepends it to the stripped frames instead.
Refinement from a real watch test: title/artist/album/genre alone was NOT
enough — the episode stayed invisible until TRCK (track number) and TLEN
(length in ms) were added. A working file's genre was literally "genre",
so frame *presence* matters more than genre *content*. Feed items also
carry `<itunes:duration>` (Apple Podcasts standard) from the manifest's
`duration_sec`.

## Starlette 1.x broke two APIs we used

- `Jinja2Templates.TemplateResponse` is now `(request, name, context)`.
  Old call order raises a cryptic Jinja `TypeError` about unhashable dicts.
- Authlib's Starlette integration needs `SessionMiddleware` installed, and
  its default cookie name (`session`) clobbers our own auth cookie — ours
  is named `oauth_state_session`. Also, `app.user_middleware` entries
  expose `cls`/`kwargs`, not `options`.

## OAuth redirect URI must come from config, not the request

`request.url_for()` behind `vercel dev` (or any proxy) yields the internal
address (`127.0.0.1:<random-port>`), which Google can never accept. The
callback URI is built from `PODCAST_BASE_URL` instead.

## vercel-blob 0.4.x sends options as HTTP headers

All `put()` option values must be strings (`cacheControlMaxAge="60"`,
`addRandomSuffix="true"`); ints raise `must be of type str or bytes`.
Overwriting a stable path additionally needs `allowOverwrite="true"`.
`contentType` is silently ignored (MIME is guessed from the extension).
The Python SDK has no OIDC support — explicit `token` on every call is
the only auth path, and per the resolution order it wins everywhere.

## Pydantic Settings vs Vercel-injected vars

Vercel injects `VERCEL_OIDC_TOKEN` (and friends) into the runtime, and
pydantic-settings defaults to `extra="forbid"` — every request 500'd.
`extra="ignore"` is set deliberately; do not remove it.

## vercel.json minimalism

- No `rewrites` needed: the FastAPI preset routes every request to the
  app. A `/(.*) → /app.py` rewrite mangled paths so no route matched
  (every endpoint 404'd while the app ran fine).
- No `functions.*.runtime` pin: CLI `vercel dev` rejects `python3.14`
  as unknown. Version resolves via `.python-version` + `requires-python`.
- Hobby plan allows daily crons only (`0 0 * * *`); hourly needs Pro.

## Test-suite gotchas

- Tampering the **last** base64 character of a signed cookie is sometimes
  a no-op (trailing bits can be padding). Tamper high bits of the first
  signature character instead.
- In Jinja, `pending.update` resolves to the dict method, not the key —
  always use `pending["update"]` bracket access.
- Python 3.14 accepts the old `except E1, E2:` comma form (behaves as a
  tuple). Worse: `ruff format` 0.16.6 actively strips parentheses from
  `except (E1, E2):`, producing the comma form — verified empirically,
  do not hand-fix it back (futile). Correct on 3.14 only; would
  SyntaxError on older Pythons, so `requires-python >= 3.14` is
  load-bearing, not cosmetic.
