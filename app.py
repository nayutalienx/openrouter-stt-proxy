from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

try:
    from win11toast import notify as notify_windows_toast
except ImportError:
    notify_windows_toast = None

load_dotenv()


def get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Missing required environment variable: {name}. Create .env from .env.example and set it.",
        )
    return value


def get_optional_env(name: str) -> str:
    return os.getenv(name, "").strip()


def get_env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def get_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default

    try:
        return int(value.strip())
    except ValueError:
        return default


def get_env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default

    try:
        return float(value.strip())
    except ValueError:
        return default


def normalize_cleanup_mode(mode: str) -> str:
    normalized = mode.strip().lower()
    if normalized in {"chat", "formal", "punctuation"}:
        return normalized
    return "chat"


def normalize_language_hint(language: str | None) -> str | None:
    if not language or not language.strip():
        return None

    normalized = language.strip().lower()
    if normalized in {"ru", "rus", "ru-ru", "russian"}:
        return "ru"
    if normalized in {"en", "en-us", "en-gb", "eng", "english"}:
        return "en"
    return normalized


OPENROUTER_TRANSCRIPTIONS_URL = "https://openrouter.ai/api/v1/audio/transcriptions"
OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"

DEFAULT_STT_MODEL = get_optional_env("DEFAULT_MODEL") or "qwen/qwen3-asr-flash-2026-02-10"
STT_TIMEOUT_SECONDS = get_env_float("OPENROUTER_TIMEOUT_SECONDS", 60.0)
MAX_AUDIO_MB = get_env_int("MAX_AUDIO_MB", 25)
MAX_AUDIO_BYTES = MAX_AUDIO_MB * 1024 * 1024

cleanup_provider_value = (get_optional_env("CLEANUP_PROVIDER") or "openrouter").strip().lower()
CLEANUP_PROVIDER = cleanup_provider_value if cleanup_provider_value in {"openrouter", "deepseek"} else "openrouter"
ENABLE_CLEANUP = get_env_bool("ENABLE_CLEANUP", True)
CLEANUP_MODEL = get_optional_env("CLEANUP_MODEL") or "deepseek/deepseek-v4-flash"
CLEANUP_TEMPERATURE = get_env_float("CLEANUP_TEMPERATURE", 0.1)
CLEANUP_TIMEOUT_SECONDS = get_env_float("CLEANUP_TIMEOUT_SECONDS", 60.0)
CLEANUP_ON_ERROR = (get_optional_env("CLEANUP_ON_ERROR") or "raw").strip().lower()
CLEANUP_MIN_CHARS = get_env_int("CLEANUP_MIN_CHARS", 20)
CLEANUP_MAX_INPUT_CHARS = get_env_int("CLEANUP_MAX_INPUT_CHARS", 12000)
CLEANUP_MODE = normalize_cleanup_mode(get_optional_env("CLEANUP_MODE") or "chat")
DEBUG_ENDPOINTS = get_env_bool("DEBUG_ENDPOINTS", False)
DEEPSEEK_BASE_URL = get_optional_env("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL
CLEANUP_TOGGLE_HOTKEY = (get_optional_env("CLEANUP_TOGGLE_HOTKEY") or "").strip().upper()
CLEANUP_DEFAULT_ACTIVE = get_env_bool("CLEANUP_DEFAULT_ACTIVE", False)
CLEANUP_WINDOWS_NOTIFICATIONS = get_env_bool("CLEANUP_WINDOWS_NOTIFICATIONS", True)

SUPPORTED_FORMATS: dict[str, str] = {
    ".wav": "wav",
    ".mp3": "mp3",
    ".m4a": "m4a",
    ".webm": "webm",
    ".flac": "flac",
    ".ogg": "ogg",
}

ALLOWED_RESPONSE_FORMATS = {"text", "json", "verbose_json", "", None}
LOCAL_CLIENT_HOSTS = {"127.0.0.1", "::1", "localhost"}
TEXT_PREVIEW_CHARS = 120
WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
HOTKEY_ID_CLEANUP_TOGGLE = 1
CREATE_NO_WINDOW = 0x08000000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("openrouter-stt-proxy")

app = FastAPI(title="OpenRouter STT Proxy", version="1.1.0")
bearer_scheme = HTTPBearer(auto_error=False)
cleanup_state_lock = threading.Lock()
cleanup_runtime_active = ENABLE_CLEANUP and CLEANUP_DEFAULT_ACTIVE
cleanup_toggle_listener_started = False
cleanup_toggle_registered = False


class DebugCleanupRequest(BaseModel):
    text: str = Field(min_length=1)
    language: str | None = None


@app.on_event("startup")
async def startup_event() -> None:
    ensure_cleanup_toggle_listener_started()


def build_openrouter_headers() -> dict[str, str]:
    api_key = get_required_env("OPENROUTER_API_KEY")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    site_url = get_optional_env("OPENROUTER_SITE_URL")
    app_name = get_optional_env("OPENROUTER_APP_NAME")
    if site_url:
        headers["HTTP-Referer"] = site_url
    if app_name:
        headers["X-Title"] = app_name

    return headers


def build_deepseek_headers() -> dict[str, str]:
    api_key = get_required_env("DEEPSEEK_API_KEY")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def build_cleanup_headers() -> dict[str, str]:
    if CLEANUP_PROVIDER == "deepseek":
        return build_deepseek_headers()
    return build_openrouter_headers()


def get_cleanup_url() -> str:
    if CLEANUP_PROVIDER == "deepseek":
        return f"{DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions"
    return OPENROUTER_CHAT_COMPLETIONS_URL


def get_cleanup_owned_by() -> str:
    if CLEANUP_PROVIDER == "deepseek":
        return "deepseek"
    return "openrouter"


def get_windows_virtual_key_code(key: str) -> int | None:
    if not key:
        return None
    if len(key) == 1:
        char = key.upper()
        if "0" <= char <= "9":
            return ord(char)
        if "A" <= char <= "Z":
            return ord(char)

    function_keys = {
        f"F{index}": 0x6F + index
        for index in range(1, 13)
    }
    return function_keys.get(key)


def parse_toggle_hotkey(hotkey: str) -> tuple[int, int] | None:
    if not hotkey:
        return None

    modifiers = 0
    virtual_key: int | None = None
    parts = [part.strip().upper() for part in hotkey.split("+") if part.strip()]

    for part in parts:
        if part in {"CTRL", "CONTROL"}:
            modifiers |= MOD_CONTROL
        elif part == "ALT":
            modifiers |= MOD_ALT
        elif part == "SHIFT":
            modifiers |= MOD_SHIFT
        elif part in {"WIN", "WINDOWS"}:
            modifiers |= MOD_WIN
        else:
            virtual_key = get_windows_virtual_key_code(part)

    if virtual_key is None:
        return None
    return modifiers | MOD_NOREPEAT, virtual_key


def is_cleanup_runtime_active() -> bool:
    with cleanup_state_lock:
        return cleanup_runtime_active


def toggle_cleanup_runtime_active() -> bool:
    global cleanup_runtime_active
    with cleanup_state_lock:
        cleanup_runtime_active = not cleanup_runtime_active
        return cleanup_runtime_active


def send_windows_cleanup_notification(active: bool) -> None:
    if not CLEANUP_WINDOWS_NOTIFICATIONS or os.name != "nt":
        return

    title = "OpenRouter STT Proxy"
    body = "Cleanup enabled" if active else "Cleanup disabled"

    if notify_windows_toast is not None:
        try:
            notify_windows_toast(title, body, audio={"silent": "true"})
            return
        except Exception as exc:
            logger.warning("Failed to send Windows toast notification via win11toast: %s", exc)

    escaped_title = title.replace("'", "''")
    escaped_body = body.replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -AssemblyName System.Drawing; "
        "$notify = New-Object System.Windows.Forms.NotifyIcon; "
        "$notify.Icon = [System.Drawing.SystemIcons]::Information; "
        "$notify.Visible = $true; "
        f"$notify.BalloonTipTitle = '{escaped_title}'; "
        f"$notify.BalloonTipText = '{escaped_body}'; "
        "$notify.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::Info; "
        "$notify.ShowBalloonTip(3000); "
        "Start-Sleep -Seconds 4; "
        "$notify.Dispose()"
    )

    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-STA",
                "-WindowStyle",
                "Hidden",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            check=False,
            timeout=5,
            creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode not in {0, None}:
            logger.warning("Windows cleanup notification process exited with code %s.", result.returncode)
    except Exception as exc:
        logger.warning("Failed to send Windows cleanup notification: %s", exc)


def run_cleanup_toggle_hotkey_listener() -> None:
    global cleanup_toggle_registered

    if os.name != "nt" or not ENABLE_CLEANUP or not CLEANUP_TOGGLE_HOTKEY:
        return

    parsed_hotkey = parse_toggle_hotkey(CLEANUP_TOGGLE_HOTKEY)
    if parsed_hotkey is None:
        logger.warning("Unsupported CLEANUP_TOGGLE_HOTKEY=%s. Cleanup toggle listener not started.", CLEANUP_TOGGLE_HOTKEY)
        return

    modifiers, virtual_key = parsed_hotkey
    user32 = ctypes.windll.user32
    registered = user32.RegisterHotKey(None, HOTKEY_ID_CLEANUP_TOGGLE, modifiers, virtual_key)
    if not registered:
        logger.warning("Failed to register cleanup toggle hotkey %s.", CLEANUP_TOGGLE_HOTKEY)
        return

    cleanup_toggle_registered = True
    logger.info(
        "Cleanup toggle hotkey listener started hotkey=%s default_active=%s",
        CLEANUP_TOGGLE_HOTKEY,
        is_cleanup_runtime_active(),
    )

    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID_CLEANUP_TOGGLE:
            active = toggle_cleanup_runtime_active()
            logger.info("Cleanup toggled active=%s hotkey=%s", active, CLEANUP_TOGGLE_HOTKEY)
            send_windows_cleanup_notification(active)


def ensure_cleanup_toggle_listener_started() -> None:
    global cleanup_toggle_listener_started

    if cleanup_toggle_listener_started:
        return
    cleanup_toggle_listener_started = True

    listener_thread = threading.Thread(
        target=run_cleanup_toggle_hotkey_listener,
        name="cleanup-toggle-hotkey-listener",
        daemon=True,
    )
    listener_thread.start()


def resolve_audio_format(filename: str | None) -> str:
    if not filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is missing a filename.",
        )

    extension = Path(filename).suffix.lower()
    audio_format = SUPPORTED_FORMATS.get(extension)
    if not audio_format:
        supported = ", ".join(sorted(value for value in set(SUPPORTED_FORMATS.values())))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported audio format for '{filename}'. "
                f"Supported formats: {supported}."
            ),
        )
    return audio_format


def parse_upstream_payload(response: httpx.Response) -> Any:
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type.lower():
        return response.json()
    return response.text


def normalize_response_format(response_format: str | None) -> str:
    normalized = (response_format or "").strip().lower()
    if normalized not in ALLOWED_RESPONSE_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported response_format. Use one of: json, verbose_json, text.",
        )
    return normalized or "json"


def truncate_text_preview(text: str) -> str:
    preview = text[:TEXT_PREVIEW_CHARS].replace("\r", " ").replace("\n", " ")
    return preview.strip()


def build_stt_payload(
    *,
    model: str,
    audio_base64: str,
    audio_format: str,
    language: str | None,
    prompt: str | None,
    temperature: float | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "input_audio": {
            "data": audio_base64,
            "format": audio_format,
        },
    }

    if language:
        payload["language"] = language
    if temperature is not None:
        payload["temperature"] = temperature
    if prompt:
        payload["provider"] = {
            "options": {
                "qwen": {
                    "prompt": prompt,
                }
            }
        }

    return payload


def extract_text_from_stt_response(payload: Any) -> str | None:
    if isinstance(payload, dict):
        text = payload.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()

        data = payload.get("data")
        if isinstance(data, dict):
            nested_text = data.get("text")
            if isinstance(nested_text, str) and nested_text.strip():
                return nested_text.strip()

        choices = payload.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if isinstance(choice, dict):
                    candidate = choice.get("text")
                    if isinstance(candidate, str) and candidate.strip():
                        return candidate.strip()

    if isinstance(payload, str) and payload.strip():
        return payload.strip()

    return None


def extract_text_from_chat_response(payload: Any) -> str | None:
    if isinstance(payload, dict):
        choices = payload.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue

                message = choice.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str) and content.strip():
                        return content.strip()
                    if isinstance(content, list):
                        text_parts: list[str] = []
                        for item in content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                part_text = item.get("text")
                                if isinstance(part_text, str) and part_text.strip():
                                    text_parts.append(part_text.strip())
                        if text_parts:
                            return "\n".join(text_parts).strip()

                direct_text = choice.get("text")
                if isinstance(direct_text, str) and direct_text.strip():
                    return direct_text.strip()

        direct_text = payload.get("text")
        if isinstance(direct_text, str) and direct_text.strip():
            return direct_text.strip()

    if isinstance(payload, str) and payload.strip():
        return payload.strip()

    return None


def build_multilingual_cleanup_prompt(mode: str, language: str | None = None) -> str:
    base_prompt = """You are an editor for dictated text.

Your task is to turn raw speech recognition output into clean, natural written text.

Rules:
- Do not add new facts.
- Do not change the meaning.
- Do not shorten the text aggressively.
- Fix punctuation, capitalization, grammar, and obvious recognition mistakes.
- Preserve the original language of each segment.
- If the text mixes Russian and English, keep that language mix intact.
- Keep technical names, commands, product names, and code terms in the language and form the speaker used unless there is an obvious recognition mistake.
- Remove obvious repetitions, filler words, and false starts only when they are not needed for meaning.
- Preserve the author's natural voice.
- Do not make the text sound too formal unless asked by the mode.
- If the text is long, split it into paragraphs when helpful.
- If the text looks like a chat message, format it like a normal message.
- Do not add commentary, explanations, headings, or Markdown.
- Return only the cleaned text."""

    mode_prompt = {
        "chat": "Make the text sound like a natural message with a live, conversational tone.",
        "formal": "Make the text more polished and businesslike without changing its meaning.",
        "punctuation": "Focus almost only on punctuation, capitalization, grammar, and obvious ASR mistakes. Rephrase as little as possible.",
    }[normalize_cleanup_mode(mode)]

    language_hint = ""
    normalized_language = normalize_language_hint(language)
    if normalized_language and normalized_language not in {"ru", "en"}:
        language_hint = (
            f"\nPrimary language hint from the caller: {language.strip()}. "
            "Preserve that language while still keeping any mixed-language fragments intact."
        )

    return f"{base_prompt}\n\n{mode_prompt}{language_hint}"


def build_cleanup_prompt(mode: str, raw_text: str, language: str | None = None) -> str:
    del raw_text
    return build_multilingual_cleanup_prompt(mode, language=language)


def build_cleanup_messages(mode: str, raw_text: str, language: str | None = None) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": build_cleanup_prompt(mode, raw_text, language=language),
        },
        {
            "role": "user",
            "content": f"Raw dictated text:\n{raw_text}",
        },
    ]


def handle_cleanup_failure(
    raw_text: str,
    message: str,
    *,
    status_code: int,
    exc: Exception | None = None,
) -> str:
    if CLEANUP_ON_ERROR != "fail":
        logger.warning("%s Returning raw transcript because CLEANUP_ON_ERROR=raw.", message)
        return raw_text

    raise HTTPException(status_code=status_code, detail=message) from exc


async def verify_local_proxy_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> None:
    expected_token = get_optional_env("LOCAL_PROXY_API_KEY")
    if not expected_token:
        return

    token = credentials.credentials if credentials else ""
    if credentials is None or credentials.scheme.lower() != "bearer" or token != expected_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Local proxy authorization failed. "
                "Send Authorization: Bearer <LOCAL_PROXY_API_KEY>."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )


async def verify_debug_endpoint_access(request: Request) -> None:
    if DEBUG_ENDPOINTS:
        return

    client_host = request.client.host if request.client else ""
    if client_host not in LOCAL_CLIENT_HOSTS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Debug cleanup endpoint is available only from localhost unless DEBUG_ENDPOINTS=true.",
        )


async def transcribe_with_openrouter(
    *,
    model: str,
    audio_bytes: bytes,
    audio_format: str,
    language: str | None,
    prompt: str | None,
    temperature: float | None,
) -> tuple[str, int, Any]:
    audio_base64 = base64.b64encode(audio_bytes).decode("ascii")
    payload = build_stt_payload(
        model=model,
        audio_base64=audio_base64,
        audio_format=audio_format,
        language=language,
        prompt=prompt,
        temperature=temperature,
    )

    try:
        timeout = httpx.Timeout(STT_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                OPENROUTER_TRANSCRIPTIONS_URL,
                headers=build_openrouter_headers(),
                json=payload,
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=(
                "Timed out while waiting for OpenRouter STT. "
                "Try a smaller file or increase OPENROUTER_TIMEOUT_SECONDS."
            ),
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reach OpenRouter STT: {exc}",
        ) from exc

    upstream_payload = parse_upstream_payload(response)

    if response.status_code in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}:
        raise HTTPException(
            status_code=response.status_code,
            detail={
                "message": "OpenRouter STT authorization failed. Check OPENROUTER_API_KEY.",
                "upstream": upstream_payload,
            },
        )

    if response.status_code == status.HTTP_400_BAD_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "OpenRouter STT rejected the request.",
                "upstream": upstream_payload,
            },
        )

    if response.is_error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "message": f"OpenRouter STT request failed with status {response.status_code}.",
                "upstream": upstream_payload,
            },
        )

    raw_text = extract_text_from_stt_response(upstream_payload)
    if not raw_text:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "message": "OpenRouter STT response did not contain transcription text.",
                "upstream": upstream_payload,
            },
        )

    return raw_text, response.status_code, upstream_payload


async def cleanup_text(raw_text: str, language: str | None = None) -> str:
    if not ENABLE_CLEANUP:
        logger.info(
            "Cleanup response status=skipped reason=disabled cleanup_enabled=%s cleanup_provider=%s cleanup_model=%s cleanup_mode=%s cleanup_toggle_hotkey=%s",
            ENABLE_CLEANUP,
            CLEANUP_PROVIDER,
            CLEANUP_MODEL,
            CLEANUP_MODE,
            CLEANUP_TOGGLE_HOTKEY,
        )
        return raw_text

    if not is_cleanup_runtime_active():
        logger.info(
            "Cleanup response status=skipped reason=toggle_off cleanup_toggle_hotkey=%s",
            CLEANUP_TOGGLE_HOTKEY or "none",
        )
        return raw_text

    normalized_text = raw_text.strip()
    if not normalized_text:
        logger.info("Cleanup response status=skipped reason=empty_text")
        return raw_text

    if len(normalized_text) < CLEANUP_MIN_CHARS:
        logger.info(
            "Cleanup response status=skipped reason=text_too_short raw_text_length=%s cleanup_min_chars=%s",
            len(normalized_text),
            CLEANUP_MIN_CHARS,
        )
        return raw_text

    if len(normalized_text) > CLEANUP_MAX_INPUT_CHARS:
        logger.info(
            "Cleanup response status=skipped reason=text_too_long raw_text_length=%s cleanup_max_input_chars=%s",
            len(normalized_text),
            CLEANUP_MAX_INPUT_CHARS,
        )
        return raw_text

    messages = build_cleanup_messages(CLEANUP_MODE, normalized_text, language=language)
    payload: dict[str, Any] = {
        "model": CLEANUP_MODEL,
        "messages": messages,
        "temperature": CLEANUP_TEMPERATURE,
    }

    logger.debug("Cleanup raw preview=%s", truncate_text_preview(normalized_text))

    try:
        timeout = httpx.Timeout(CLEANUP_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                get_cleanup_url(),
                headers=build_cleanup_headers(),
                json=payload,
            )
    except httpx.TimeoutException as exc:
        return handle_cleanup_failure(
            raw_text,
            f"Cleanup request timed out while waiting for {CLEANUP_PROVIDER} chat completions.",
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            exc=exc,
        )
    except httpx.HTTPError as exc:
        return handle_cleanup_failure(
            raw_text,
            f"Failed to reach {CLEANUP_PROVIDER} cleanup endpoint: {exc}",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            exc=exc,
        )

    cleanup_payload = parse_upstream_payload(response)
    logger.info(
        "Cleanup response status=%s cleanup_provider=%s cleanup_model=%s cleanup_mode=%s",
        response.status_code,
        CLEANUP_PROVIDER,
        CLEANUP_MODEL,
        CLEANUP_MODE,
    )

    if response.status_code in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}:
        return handle_cleanup_failure(
            raw_text,
            (
                "DeepSeek cleanup authorization failed. Check DEEPSEEK_API_KEY."
                if CLEANUP_PROVIDER == "deepseek"
                else "OpenRouter cleanup authorization failed. Check OPENROUTER_API_KEY."
            ),
            status_code=response.status_code,
        )

    if response.status_code == status.HTTP_400_BAD_REQUEST:
        return handle_cleanup_failure(
            raw_text,
            f"{CLEANUP_PROVIDER.capitalize()} cleanup rejected the request.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if response.is_error:
        return handle_cleanup_failure(
            raw_text,
            f"{CLEANUP_PROVIDER.capitalize()} cleanup request failed with status {response.status_code}.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    cleaned_text = extract_text_from_chat_response(cleanup_payload)
    if not cleaned_text:
        logger.warning("Cleanup returned empty text. Falling back to raw transcript.")
        return raw_text

    logger.debug("Cleanup cleaned preview=%s", truncate_text_preview(cleaned_text))
    return cleaned_text


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "provider": "openrouter",
        "default_stt_model": DEFAULT_STT_MODEL,
        "cleanup_enabled": ENABLE_CLEANUP,
        "cleanup_active": is_cleanup_runtime_active(),
        "cleanup_provider": CLEANUP_PROVIDER,
        "cleanup_model": CLEANUP_MODEL,
        "cleanup_mode": CLEANUP_MODE,
        "cleanup_toggle_hotkey": CLEANUP_TOGGLE_HOTKEY or None,
        "cleanup_default_active": CLEANUP_DEFAULT_ACTIVE,
    }


@app.get("/v1/models", dependencies=[Depends(verify_local_proxy_auth)])
async def list_models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": DEFAULT_STT_MODEL,
                "object": "model",
                "owned_by": "openrouter",
                "type": "speech-to-text",
            },
            {
                "id": CLEANUP_MODEL,
                "object": "model",
                "owned_by": get_cleanup_owned_by(),
                "type": "chat-cleanup",
            },
        ],
    }


@app.post(
    "/debug/cleanup",
    dependencies=[Depends(verify_local_proxy_auth), Depends(verify_debug_endpoint_access)],
    response_model=None,
)
async def debug_cleanup(payload: DebugCleanupRequest) -> dict[str, str]:
    cleaned_text = await cleanup_text(payload.text, language=payload.language)
    return {"text": cleaned_text}


@app.post(
    "/v1/audio/transcriptions",
    dependencies=[Depends(verify_local_proxy_auth)],
    response_model=None,
)
async def create_transcription(
    request: Request,
    file: UploadFile = File(...),
    model: str = Form(DEFAULT_STT_MODEL),
    language: str | None = Form(default=None),
    prompt: str | None = Form(default=None),
    temperature: float | None = Form(default=None),
    response_format: str | None = Form(default=None),
) -> JSONResponse:
    start = time.perf_counter()
    selected_model = model.strip() or DEFAULT_STT_MODEL
    normalized_language = language.strip() if language else None
    normalized_prompt = prompt.strip() if prompt else None
    raw_text = ""
    cleaned_text = ""
    file_bytes = b""
    stt_response_status = "not_sent"

    try:
        normalize_response_format(response_format)
        audio_format = resolve_audio_format(file.filename)
        file_bytes = await file.read()
        file_size = len(file_bytes)

        if file_size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded audio file is empty.",
            )
        if file_size > MAX_AUDIO_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Audio file is too large. Max size is {MAX_AUDIO_MB} MB.",
            )

        logger.info(
            "STT request started filename=%s file_size_bytes=%s stt_model=%s client=%s",
            file.filename,
            file_size,
            selected_model,
            request.client.host if request.client else "unknown",
        )

        raw_text, stt_status_code, _ = await transcribe_with_openrouter(
            model=selected_model,
            audio_bytes=file_bytes,
            audio_format=audio_format,
            language=normalized_language,
            prompt=normalized_prompt,
            temperature=temperature,
        )
        stt_response_status = str(stt_status_code)

        logger.info(
            "STT response status=%s raw_text_length=%s cleanup_enabled=%s cleanup_provider=%s cleanup_model=%s cleanup_mode=%s",
            stt_response_status,
            len(raw_text),
            ENABLE_CLEANUP,
            CLEANUP_PROVIDER,
            CLEANUP_MODEL,
            CLEANUP_MODE,
        )
        logger.debug("STT raw preview=%s", truncate_text_preview(raw_text))

        cleaned_text = await cleanup_text(raw_text, language=normalized_language)
        logger.info("Cleaned text length=%s", len(cleaned_text))

        return JSONResponse(content={"text": cleaned_text})
    finally:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            "Transcription completed filename=%s file_size_bytes=%s stt_model=%s stt_response_status=%s raw_text_length=%s cleaned_text_length=%s total_duration_ms=%s",
            file.filename,
            len(file_bytes),
            selected_model,
            stt_response_status,
            len(raw_text),
            len(cleaned_text),
            duration_ms,
        )
        await file.close()
