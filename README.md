# OpenRouter STT Proxy for OpenWhispr

Small local Windows-friendly proxy that accepts OpenAI-style multipart transcription requests from OpenWhispr/OpenWhisper, forwards audio to OpenRouter Speech-to-Text, and can optionally clean up the transcript with OpenRouter Chat Completions.

## What it does

- Listens locally on `http://127.0.0.1:8787`
- Accepts `POST /v1/audio/transcriptions` as `multipart/form-data`
- Reads the uploaded audio into memory
- Converts audio bytes to base64 JSON for OpenRouter STT
- Sends the request to `https://openrouter.ai/api/v1/audio/transcriptions`
- Optionally sends the raw transcript to `deepseek/deepseek-v4-flash` for cleanup
- Supports Russian, English, and mixed Russian/English dictation in the cleanup stage
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
DEFAULT_MODEL=openai/gpt-4o-transcribe
MAX_AUDIO_MB=25
OPENROUTER_TIMEOUT_SECONDS=60
CLEANUP_PROVIDER=openrouter
ENABLE_CLEANUP=true
CLEANUP_MODEL=deepseek/deepseek-v4-flash
CLEANUP_TEMPERATURE=0.1
CLEANUP_TIMEOUT_SECONDS=60
CLEANUP_ON_ERROR=raw
CLEANUP_MIN_CHARS=20
CLEANUP_MAX_INPUT_CHARS=12000
CLEANUP_MODE=chat
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
CLEANUP_TOGGLE_HOTKEY=CTRL+2
CLEANUP_DEFAULT_ACTIVE=false
CLEANUP_WINDOWS_NOTIFICATIONS=true
CLEANUP_NOTIFICATION_MODE=overlay
CLEANUP_NOTIFICATION_DURATION_MS=1600
CLEANUP_NOTIFICATION_MAX_STACK=4
DEBUG_ENDPOINTS=false
LOCAL_PROXY_API_KEY=
```

## Environment variables

- `OPENROUTER_API_KEY`: required. Your OpenRouter key.
- `OPENROUTER_APP_NAME`: optional label sent as `X-Title`.
- `OPENROUTER_SITE_URL`: optional site URL sent as `HTTP-Referer`.
- `DEFAULT_MODEL`: default STT model. Defaults to `openai/gpt-4o-transcribe`.
- `MAX_AUDIO_MB`: max accepted upload size in MB. Default is `25`.
- `OPENROUTER_TIMEOUT_SECONDS`: upstream STT timeout. Default is `60`.
- `CLEANUP_PROVIDER`: cleanup backend. Use `openrouter` or `deepseek`.
- `ENABLE_CLEANUP`: enables or disables transcript cleanup. Default is `true`.
- `CLEANUP_MODEL`: chat model for cleanup. Examples: `deepseek/deepseek-v4-flash` on OpenRouter or `deepseek-v4-flash` on DeepSeek.
- `CLEANUP_TEMPERATURE`: low cleanup temperature for stable editing. Default is `0.1`.
- `CLEANUP_TIMEOUT_SECONDS`: cleanup timeout. Default is `60`.
- `CLEANUP_ON_ERROR`: `raw` or `fail`. If `raw`, the proxy returns the raw STT transcript when cleanup fails.
- `CLEANUP_MIN_CHARS`: skip cleanup for very short transcripts. Default is `20`.
- `CLEANUP_MAX_INPUT_CHARS`: skip cleanup when the raw transcript is longer than this threshold. Default is `12000`.
- `CLEANUP_MODE`: `chat`, `formal`, or `punctuation`.
- `DEEPSEEK_API_KEY`: required only when `CLEANUP_PROVIDER=deepseek`.
- `DEEPSEEK_BASE_URL`: defaults to `https://api.deepseek.com`.
- `CLEANUP_TOGGLE_HOTKEY`: optional Windows global hotkey for toggling cleanup on and off. Default is `CTRL+2`.
- `CLEANUP_DEFAULT_ACTIVE`: whether cleanup starts enabled when the proxy launches. Default is `false`.
- `CLEANUP_WINDOWS_NOTIFICATIONS`: show a Windows toast notification when cleanup is toggled. Default is `true`.
- `CLEANUP_NOTIFICATION_MODE`: `overlay`, `toast`, or any other fallback mode. `overlay` is the default and shows fast custom popup cards in the bottom-right corner.
- `CLEANUP_NOTIFICATION_DURATION_MS`: how long each custom overlay stays visible. Default is `1600`.
- `CLEANUP_NOTIFICATION_MAX_STACK`: max number of simultaneous overlay cards shown during rapid toggling. Default is `4`.
- `DEBUG_ENDPOINTS`: when `true`, debug endpoints are allowed beyond strict localhost-only access rules.
- `LOCAL_PROXY_API_KEY`: optional local auth key. Leave empty to disable local auth.

## Optional cleanup with DeepSeek V4 Flash

The cleanup step improves punctuation, casing, grammar, and obvious ASR mistakes after the STT model produces the raw transcript. This is useful when you dictate into OpenWhispr and want readable chat-style text without changing the meaning.

Cleanup language behavior:

- the proxy uses one multilingual cleanup prompt written in English
- the prompt is designed to preserve Russian, English, and mixed Russian/English dictation
- if `language` is provided, it is treated only as a hint for the cleanup model, not as a hard prompt switch

This keeps the backend simpler and avoids separate Russian-only and English-only prompt branches.

Optional cleanup toggle hotkey:

```env
CLEANUP_TOGGLE_HOTKEY=CTRL+2
CLEANUP_DEFAULT_ACTIVE=false
CLEANUP_WINDOWS_NOTIFICATIONS=true
CLEANUP_NOTIFICATION_MODE=overlay
CLEANUP_NOTIFICATION_DURATION_MS=1600
CLEANUP_NOTIFICATION_MAX_STACK=4
```

With that setting, the proxy toggles cleanup state when you press `Ctrl+2` anywhere in Windows. This is useful on Windows for push-to-talk workflows such as:

- press `Ctrl+2` once -> cleanup enabled
- press `Ctrl+2` again -> cleanup disabled
- the proxy shows a fast custom overlay in the bottom-right corner so you can see the current state even when you toggle quickly

Enable cleanup:

```env
ENABLE_CLEANUP=true
CLEANUP_PROVIDER=openrouter
CLEANUP_MODEL=deepseek/deepseek-v4-flash
```

Use DeepSeek directly for cleanup:

```env
ENABLE_CLEANUP=true
CLEANUP_PROVIDER=deepseek
CLEANUP_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=your_deepseek_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
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
- `Model`: `openai/gpt-4o-transcribe`

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
  "default_stt_model": "openai/gpt-4o-transcribe",
  "cleanup_enabled": true,
  "cleanup_active": false,
  "cleanup_provider": "openrouter",
  "cleanup_model": "deepseek/deepseek-v4-flash",
  "cleanup_mode": "chat",
  "cleanup_toggle_hotkey": "CTRL+2",
  "cleanup_default_active": false
}
```

### `GET /v1/models`

Response:

```json
{
  "object": "list",
  "data": [
    {
      "id": "openai/gpt-4o-transcribe",
      "object": "model",
      "owned_by": "openrouter",
      "type": "speech-to-text"
    },
    {
      "id": "deepseek-v4-flash",
      "object": "model",
      "owned_by": "deepseek",
      "type": "chat-cleanup"
    }
  ]
}
```

### `POST /v1/audio/transcriptions`

Accepted `multipart/form-data` fields:

- `file` required
- `model` optional, defaults to `openai/gpt-4o-transcribe`
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
  -F "model=openai/gpt-4o-transcribe"
```

If local auth is enabled:

```bat
curl -X POST http://127.0.0.1:8787/v1/audio/transcriptions ^
  -H "Authorization: Bearer YOUR_LOCAL_PROXY_API_KEY" ^
  -F "file=@test.wav" ^
  -F "model=openai/gpt-4o-transcribe"
```

## Notes about request forwarding

- Audio is not persisted by the proxy as output files.
- The proxy does not log base64 audio or API keys.
- The proxy does not log the full user transcript.
- `language` and `temperature` are forwarded to STT when provided.
- `prompt` is forwarded only for compatible Qwen-based STT models. It is ignored for the default Whisper path.
- STT uses `OPENROUTER_API_KEY`.
- Cleanup uses `OPENROUTER_API_KEY` when `CLEANUP_PROVIDER=openrouter`.
- Cleanup uses `DEEPSEEK_API_KEY` when `CLEANUP_PROVIDER=deepseek`.
- Cleanup supports Russian, English, and mixed Russian/English text.
- Cleanup uses one multilingual English prompt for all supported languages.

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
- Verify your OpenRouter account can access `openai/gpt-4o-transcribe`.
- If `CLEANUP_PROVIDER=openrouter`, verify OpenRouter can access your cleanup model too.
- If `CLEANUP_PROVIDER=deepseek`, verify `DEEPSEEK_API_KEY` is correct and the model is available on your DeepSeek account.
- If `LOCAL_PROXY_API_KEY` is set, make sure the local `Authorization: Bearer ...` header is also present.

### `400`

- Check that the uploaded filename extension matches the real audio format.
- Try `wav` or `mp3` if the source format is unusual.
- Remove `prompt`, `language`, or `temperature` and retry.

### `504`

- The file may be too large or the upstream model is slow.
- Reduce audio length or increase `OPENROUTER_TIMEOUT_SECONDS` or `CLEANUP_TIMEOUT_SECONDS`.
