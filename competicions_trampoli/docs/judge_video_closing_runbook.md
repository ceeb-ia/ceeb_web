# Judge Video Closing Runbook

This runbook covers production-oriented closing items after MVP implementation.

## 1) Persistence and Docker

- Keep media on persistent volume (`MEDIA_ROOT=/data/media`).
- Configure upload limits from environment:
  - `DATA_UPLOAD_MAX_MEMORY_SIZE`
  - `FILE_UPLOAD_MAX_MEMORY_SIZE`
  - `DATA_UPLOAD_MAX_NUMBER_FILES`
- Configure host/security from environment:
  - `ALLOWED_HOSTS`
  - `CSRF_TRUSTED_ORIGINS` (if using HTTPS domain)

### Important

- For mobile camera capture outside localhost, serve the app via HTTPS.
- `runserver` is fine for dev, not for production edge traffic.
- Reference nginx config is provided at:
  - `docker/nginx/judge_video.conf`

Run optional proxy profile:

```powershell
docker compose --profile edge up
```

## 2) Traceability

- `ScoreEntryVideoEvent` stores immutable audit events:
  - upload
  - replace
  - delete
  - upload_rejected
- Events include competition, apparatus, inscription, score entry, token, status, detail, payload.

## 3) Observability

- Video endpoints emit structured JSON logs from `views_judge.py`.
- Logged fields include token, inscription, exercise, apparatus, status and latency.

## 4) Retention operations

Use management command:

```powershell
py manage.py cleanup_judge_videos --older-than-days 60
```

Dry-run first:

```powershell
py manage.py cleanup_judge_videos --older-than-days 60 --dry-run
```

Optional status filtering:

```powershell
py manage.py cleanup_judge_videos --older-than-days 30 --status failed
```
