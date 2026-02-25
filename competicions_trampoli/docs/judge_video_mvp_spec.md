# Judge Video MVP Specification

This file freezes Step 1 functional decisions for the first implementation.

## Scope

- Capture video from the judge portal per participant card.
- Link each capture to one concrete scoring row:
  - `competicio`
  - `inscripcio`
  - `exercici`
  - `comp_aparell`
- Keep the scoring workflow independent from video upload.

## Functional Decisions

- One active video per score row.
  - Implemented by one-to-one relation with `ScoreEntry`.
  - Re-record means replacing the same linked video record/file.
- Upload limits (MVP):
  - max duration: 90 seconds
  - max size: 120 MB
  - mime types: `video/mp4`, `video/webm`, `video/quicktime`
- Judge provenance is stored through optional `JudgeDeviceToken` relation.
- Video lifecycle states:
  - `pending`
  - `ready`
  - `failed`

## Non-Goals in Step 1/2

- No recording UI changes yet.
- No upload API yet.
- No playback/public endpoints yet.
- No background transcoding yet.

## Step 3 API Contract

All endpoints are protected by judge token and competition/apparatus checks.

### 1) Video status

- `GET /judge/<uuid:token>/api/video/status/?inscripcio_id=<id>&exercici=<n>`
- Response:
  - `ok: true`
  - `has_video: true|false`
  - `inscripcio_id`, `exercici`, `score_entry_id` (if score exists)
  - `video` object when `has_video=true`

### 2) Video upload

- `POST /judge/<uuid:token>/api/video/upload/` (multipart/form-data)
- Fields:
  - required: `inscripcio_id`, `video_file`
  - optional: `exercici`, `duration_seconds`, `mime_type`, `original_filename`
- Response:
  - `ok: true`
  - `created: true|false` (new or replace)
  - `inscripcio_id`, `exercici`, `score_entry_id`
  - `video` object

### 3) Video delete (re-record flow)

- `POST /judge/<uuid:token>/api/video/delete/`
- Fields:
  - required: `inscripcio_id`
  - optional: `exercici`
- Response:
  - `ok: true`
  - `deleted: true|false`
  - `inscripcio_id`, `exercici`, `score_entry_id` (if exists)

### Video object format

- `id`
- `status` (`pending|ready|failed`)
- `duration_seconds`
- `file_size_bytes`
- `mime_type`
- `original_filename`
- `updated_at`
- `url` (absolute media URL when available)

## Step 4 Backend Rules

- Reuses judge token validity checks (`is_valid` + touch usage timestamp).
- Validates `Inscripcio` belongs to token competition.
- Rejects excluded inscription/apparatus pairs.
- Clamps `exercici` to apparatus max exercises.
- Enforces MVP media limits:
  - duration <= 90s
  - size <= 120MB
  - allowed mime types only
- Creates `ScoreEntry` if needed, then links/replaces one `ScoreEntryVideo`.
