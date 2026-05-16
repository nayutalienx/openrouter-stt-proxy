# OpenRouter STT Proxy for OpenWhispr

Small local Windows-friendly proxy that accepts OpenAI-style multipart transcription requests from OpenWhispr/OpenWhisper, forwards audio to OpenRouter Speech-to-Text, and can optionally clean up the transcript with OpenRouter Chat Completions.

## What it does

- Listens locally on `http://127.0.0.1:8787`
- Accepts `POST /v1/audio/transcriptions` as `multipart/form-data`
- Reads the uploaded audio into memory
- Converts audio bytes to base64 JSON for OpenRouter STT
- Sends the request to `https://openrouter.ai/api/v1/audio/transcriptions`
- Optionally sends the raw transcript to `deepseek/deepseek-v4-flash` for cleanup
- Returns an OpenAI-compatible transcription response:

```json
{
  "text": "final transcript"
}
```

## Project files

```text
openrouter-stt-proxy/
  app.py
  requirements.txt
  .env.example
  run.ps1
  run.bat
  test-health.ps1
  test-cleanup.ps1
  README.md
```

## Requirements

- Windows 10 or Windows 11
- Python 3.10 or newer
- Internet access to `openrouter.ai`
- OpenRouter API key

## Install Python on Windows

1. Download Python 3.10+ from [python.org](https://www.python.org/downloads/windows/).
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
git clone https://github.com/nayutalienx/openrouter-stt-proxy.git
cd openrouter-stt-proxy
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
ENABLE_CLEANUP=true
CLEANUP_MODEL=deepseek/deepseek-v4-flash
CLEANUP_TEMPERATURE=0.1
CLEANUP_TIMEOUT_SECONDS=60
CLEANUP_ON_ERROR=raw
CLEANUP_MIN_CHARS=20
CLEANUP_MAX_INPUT_CHARS=12000
CLEANUP_MODE=chat
DEBUG_ENDPOINTS=false
LOCAL_PROXY_API_KEY=
```

## Environment variables

- `OPENROUTER_API_KEY`: required. Your OpenRouter key.
- `OPENROUTER_APP_NAME`: optional label sent as `X-Title`.
- `OPENROUTER_SITE_URL`: optional site URL sent as `HTTP-Referer`.
- `DEFAULT_MODEL`: default STT model. Defaults to `qwen/qwen3-asr-flash-2026-02-10`.
- `MAX_AUDIO_MB`: max accepted upload size in MB. Default is `25`.
- `OPENROUTER_TIMEOUT_SECONDS`: upstream STT timeout. Default is `60`.
- `ENABLE_CLEANUP`: enables or disables transcript cleanup. Default is `true`.
- `CLEANUP_MODEL`: OpenRouter chat model for cleanup. Default is `deepseek/deepseek-v4-flash`.
- `CLEANUP_TEMPERATURE`: low cleanup temperature for stable editing. Default is `0.1`.
- `CLEANUP_TIMEOUT_SECONDS`: cleanup timeout. Default is `60`.
- `CLEANUP_ON_ERROR`: `raw` or `fail`. If `raw`, the proxy returns the raw STT transcript when cleanup fails.
- `CLEANUP_MIN_CHARS`: skip cleanup for very short transcripts. Default is `20`.
- `CLEANUP_MAX_INPUT_CHARS`: skip cleanup when the raw transcript is longer than this threshold. Default is `12000`.
- `CLEANUP_MODE`: `chat`, `formal`, or `punctuation`.
- `DEBUG_ENDPOINTS`: when `true`, debug endpoints are allowed beyond strict localhost-only access rules.
- `LOCAL_PROXY_API_KEY`: optional local auth key. Leave empty to disable local auth.

## Optional cleanup with DeepSeek V4 Flash

The cleanup step improves punctuation, casing, grammar, and obvious ASR mistakes after Qwen STT produces the raw transcript. This is useful when you dictate into OpenWhispr and want readable chat-style text without changing the meaning.

Enable cleanup:

```env
ENABLE_CLEANUP=true
CLEANUP_MODEL=deepseek/deepseek-v4-flash
```

Disable cleanup:

```env
ENABLE_CLEANUP=false
```

Cleanup modes:

- `CLEANUP_MODE=chat`: natural chat-style cleanup with a live, human tone
- `CLEANUP_MODE=formal`: cleaner and more businesslike style without changing meaning
- `CLEANUP_MODE=punctuation`: minimal rewriting, mostly punctuation, casing, grammar, and obvious ASR fixes

Important:

- Do not enable cleanup in both OpenWhispr and this proxy at the same time, otherwise the text can become over-edited.
- If cleanup fails and `CLEANUP_ON_ERROR=raw`, the proxy returns the raw STT transcript instead of failing the whole request.

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
- `API Key`: leave empty if `LOCAL_PROXY_API_KEY` is not set
- `Model`: `qwen/qwen3-asr-flash-2026-02-10`

If you set `LOCAL_PROXY_API_KEY` in `.env`, then put that same value into the OpenWhispr `API Key` field. The proxy expects `Authorization: Bearer <LOCAL_PROXY_API_KEY>` for `/v1/audio/transcriptions` when local auth is enabled.

## Endpoints

### `GET /health`

Health is intentionally left without local auth.

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8787/health"
```

Response:

```json
{
  "status": "ok",
  "provider": "openrouter",
  "default_stt_model": "qwen/qwen3-asr-flash-2026-02-10",
  "cleanup_enabled": true,
  "cleanup_model": "deepseek/deepseek-v4-flash",
  "cleanup_mode": "chat"
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
      "owned_by": "openrouter",
      "type": "speech-to-text"
    },
    {
      "id": "deepseek/deepseek-v4-flash",
      "object": "model",
      "owned_by": "openrouter",
      "type": "chat-cleanup"
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

The proxy always returns:

```json
{
  "text": "cleaned or raw transcript"
}
```

### `POST /debug/cleanup`

This endpoint lets you test cleanup without audio.

- If `LOCAL_PROXY_API_KEY` is set, it requires `Authorization: Bearer <LOCAL_PROXY_API_KEY>`.
- If `DEBUG_ENDPOINTS=false`, it is limited to localhost access.

Request:

```json
{
  "text": "ну короче я хотел сказать что давай наверное завтра это обсудим потому что сейчас не очень удобно"
}
```

Response:

```json
{
  "text": "Короче, я хотел сказать: давай, наверное, обсудим это завтра, потому что сейчас не очень удобно."
}
```

## Test scripts

### Health test

```powershell
.\test-health.ps1
```

### Cleanup test

```powershell
.\test-cleanup.ps1
```

### cURL transcription test

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

## Notes about request forwarding

- Audio is not persisted by the proxy as output files.
- The proxy does not log base64 audio or API keys.
- The proxy does not log the full user transcript.
- `language` and `temperature` are forwarded to STT when provided.
- `prompt` is forwarded only when non-empty and is sent as a Qwen provider-specific option.
- Cleanup uses the same `OPENROUTER_API_KEY` as STT.

## Error handling

STT:

- Missing `OPENROUTER_API_KEY`: proxy returns `500`
- Missing `file`: FastAPI returns `422`
- Unsupported extension: proxy returns `400`
- File larger than `MAX_AUDIO_MB`: proxy returns `413`
- OpenRouter STT `401` or `403`: proxy returns a message telling you to check `OPENROUTER_API_KEY`
- OpenRouter STT `400`: proxy returns the upstream error body
- Upstream STT timeout: proxy returns `504`
- Other STT upstream failures: proxy returns `500`

Cleanup:

- If cleanup fails and `CLEANUP_ON_ERROR=raw`, the proxy logs a warning and returns the raw transcript
- If cleanup fails and `CLEANUP_ON_ERROR=fail`, the proxy returns an error
- If cleanup returns an empty string, the proxy returns the raw transcript

## Quick start

1. Install Python 3.10+.
2. Clone the repository and open the project folder.
3. Run `Copy-Item .env.example .env`.
4. Put your OpenRouter key into `.env`.
5. Start the proxy with `.\run.ps1`.
6. Check `http://127.0.0.1:8787/health`.
7. Optionally test `.\test-cleanup.ps1`.
8. Point OpenWhispr to `http://127.0.0.1:8787/v1`.

## Troubleshooting

### `401` or `403`

- Check that `OPENROUTER_API_KEY` in `.env` is correct.
- Restart the proxy after editing `.env`.
- Verify your OpenRouter account can access both `qwen/qwen3-asr-flash-2026-02-10` and `deepseek/deepseek-v4-flash` if cleanup is enabled.
- If `LOCAL_PROXY_API_KEY` is set, make sure the local `Authorization: Bearer ...` header is also present.

### `400`

- Check that the uploaded filename extension matches the real audio format.
- Try `wav` or `mp3` if the source format is unusual.
- Remove `prompt`, `language`, or `temperature` and retry.

### `504`

- The file may be too large or the upstream model is slow.
- Reduce audio length or increase `OPENROUTER_TIMEOUT_SECONDS` or `CLEANUP_TIMEOUT_SECONDS`.
