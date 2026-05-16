# OpenRouter STT Proxy for OpenWhispr

Small local Windows-friendly proxy that accepts OpenAI-style multipart transcription requests from OpenWhispr/OpenWhisper and forwards them to the OpenRouter Speech-to-Text API.

## What it does

- Listens locally on `http://127.0.0.1:8787`
- Accepts `POST /v1/audio/transcriptions` as `multipart/form-data`
- Reads the uploaded audio into memory
- Converts audio bytes to base64 JSON for OpenRouter
- Sends the request to `https://openrouter.ai/api/v1/audio/transcriptions`
- Returns an OpenAI-compatible transcription response

## Project files

```text
openrouter-stt-proxy/
  app.py
  requirements.txt
  .env.example
  run.ps1
  run.bat
  README.md
```

## Requirements

- Windows 10 or Windows 11
- Python 3.11 or newer
- Internet access to `openrouter.ai`
- OpenRouter API key

## Install Python on Windows

1. Download Python 3.11+ from [python.org](https://www.python.org/downloads/windows/).
2. Run the installer.
3. Enable `Add python.exe to PATH`.
4. Finish installation.
5. Verify in PowerShell:

```powershell
py -3 --version
```

## Setup

Open PowerShell in the project folder:

```powershell
cd C:\Users\nayut\Documents\Projects\open-whisper-proxy\openrouter-stt-proxy
```

Create `.env` from the example:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and set your key:

```env
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_APP_NAME=OpenWhispr STT Proxy
OPENROUTER_SITE_URL=http://localhost
DEFAULT_MODEL=qwen/qwen3-asr-flash-2026-02-10
MAX_AUDIO_MB=25
OPENROUTER_TIMEOUT_SECONDS=60
LOCAL_PROXY_API_KEY=
```

## Environment variables

- `OPENROUTER_API_KEY`: required. Your OpenRouter key.
- `OPENROUTER_APP_NAME`: optional label sent as `X-Title`.
- `OPENROUTER_SITE_URL`: optional site URL sent as `HTTP-Referer`.
- `DEFAULT_MODEL`: default STT model. Defaults to `qwen/qwen3-asr-flash-2026-02-10`.
- `MAX_AUDIO_MB`: max accepted upload size in MB. Default is `25`.
- `OPENROUTER_TIMEOUT_SECONDS`: upstream timeout. Default is `60`.
- `LOCAL_PROXY_API_KEY`: optional local auth key. Leave empty to disable local auth.

## Run on Windows

### PowerShell

If script execution is blocked, run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

Then start the proxy:

```powershell
.\run.ps1
```

### Double-click / CMD

You can also run:

```bat
run.bat
```

Both scripts will:

- create `.venv` if needed
- install `requirements.txt`
- check that `.env` exists
- start `uvicorn` on `127.0.0.1:8787`

## OpenWhispr settings

OpenWhispr:

- `Speech-to-Text` -> `Cloud Providers` -> `Custom`
- `Endpoint URL`: `http://127.0.0.1:8787/v1`
- `API Key`: leave empty
- `Model`: `qwen/qwen3-asr-flash-2026-02-10`

If you set `LOCAL_PROXY_API_KEY` in `.env`, then put that same value into the OpenWhispr `API Key` field. The proxy expects `Authorization: Bearer <LOCAL_PROXY_API_KEY>` when local auth is enabled.

## Endpoints

### `GET /health`

Example:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8787/health"
```

Response:

```json
{
  "status": "ok",
  "provider": "openrouter",
  "default_model": "qwen/qwen3-asr-flash-2026-02-10"
}
```

### `GET /v1/models`

Response:

```json
{
  "object": "list",
  "data": [
    {
      "id": "qwen/qwen3-asr-flash-2026-02-10",
      "object": "model",
      "owned_by": "openrouter"
    }
  ]
}
```

### `POST /v1/audio/transcriptions`

Accepted `multipart/form-data` fields:

- `file` required
- `model` optional, defaults to `qwen/qwen3-asr-flash-2026-02-10`
- `language` optional
- `prompt` optional
- `temperature` optional
- `response_format` optional

Supported filename extensions:

- `wav`
- `mp3`
- `m4a`
- `webm`
- `flac`
- `ogg`

## Test requests

### cURL on Windows

```bat
curl -X POST http://127.0.0.1:8787/v1/audio/transcriptions ^
  -F "file=@test.wav" ^
  -F "model=qwen/qwen3-asr-flash-2026-02-10"
```

If local auth is enabled:

```bat
curl -X POST http://127.0.0.1:8787/v1/audio/transcriptions ^
  -H "Authorization: Bearer YOUR_LOCAL_PROXY_API_KEY" ^
  -F "file=@test.wav" ^
  -F "model=qwen/qwen3-asr-flash-2026-02-10"
```

### PowerShell health check

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8787/health"
```

If local auth is enabled:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8787/health" -Headers @{
  Authorization = "Bearer YOUR_LOCAL_PROXY_API_KEY"
}
```

## Notes about request forwarding

- Audio is not persisted by the proxy as output files.
- The proxy does not log base64 audio or API keys.
- `language` and `temperature` are forwarded directly when provided.
- `prompt` is forwarded only when non-empty and is sent as a Qwen provider-specific option.
- `response_format=text` is handled locally and returns plain text. `json` and `verbose_json` return JSON.

## Error handling

- Missing `OPENROUTER_API_KEY`: proxy returns `500`
- Missing `file`: FastAPI returns `422`
- Unsupported extension: proxy returns `400`
- File larger than `MAX_AUDIO_MB`: proxy returns `413`
- OpenRouter `401` or `403`: proxy returns the same status with a hint to check `OPENROUTER_API_KEY`
- OpenRouter `400`: proxy returns upstream error body
- Upstream timeout: proxy returns `504`
- Other upstream failures: proxy returns `500`

## Quick start

1. Install Python 3.11+.
2. Open `C:\Users\nayut\Documents\Projects\open-whisper-proxy\openrouter-stt-proxy`.
3. Run `Copy-Item .env.example .env`.
4. Put your OpenRouter key into `.env`.
5. Start the proxy with `.\run.ps1`.
6. Check `http://127.0.0.1:8787/health`.
7. Point OpenWhispr to `http://127.0.0.1:8787/v1`.

## Troubleshooting

### `401` or `403`

- Check that `OPENROUTER_API_KEY` in `.env` is correct.
- Restart the proxy after editing `.env`.
- Verify your OpenRouter account can access `qwen/qwen3-asr-flash-2026-02-10`.
- If `LOCAL_PROXY_API_KEY` is set, make sure the local `Authorization: Bearer ...` header is also present.

### `400`

- Check that the uploaded filename extension matches the real audio format.
- Try `wav` or `mp3` if the source format is unusual.
- Remove `prompt`, `language`, or `temperature` and retry.

### `504`

- The file may be too large or the upstream model is slow.
- Reduce audio length or increase `OPENROUTER_TIMEOUT_SECONDS`.
