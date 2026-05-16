from __future__ import annotations

import base64
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

load_dotenv()

OPENROUTER_TRANSCRIPTIONS_URL = "https://openrouter.ai/api/v1/audio/transcriptions"
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen/qwen3-asr-flash-2026-02-10")
DEFAULT_TIMEOUT_SECONDS = float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "60"))
MAX_AUDIO_MB = int(os.getenv("MAX_AUDIO_MB", "25"))
MAX_AUDIO_BYTES = MAX_AUDIO_MB * 1024 * 1024

SUPPORTED_FORMATS: dict[str, str] = {
    ".wav": "wav",
    ".mp3": "mp3",
    ".m4a": "m4a",
    ".webm": "webm",
    ".flac": "flac",
    ".ogg": "ogg",
}

TEXT_RESPONSE_FORMATS = {"text"}
JSON_RESPONSE_FORMATS = {"json", "verbose_json", None, ""}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("openrouter-stt-proxy")

app = FastAPI(title="OpenRouter STT Proxy", version="1.0.0")
bearer_scheme = HTTPBearer(auto_error=False)


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


def extract_text(payload: Any) -> str | None:
    if isinstance(payload, dict):
        text = payload.get("text")
        if isinstance(text, str) and text.strip():
            return text

        data = payload.get("data")
        if isinstance(data, dict):
            nested_text = data.get("text")
            if isinstance(nested_text, str) and nested_text.strip():
                return nested_text

        choices = payload.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                candidate = choice.get("text")
                if isinstance(candidate, str) and candidate.strip():
                    return candidate

                message = choice.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str) and content.strip():
                        return content
    elif isinstance(payload, str) and payload.strip():
        return payload

    return None


def build_openrouter_payload(
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


@app.get("/health", dependencies=[Depends(verify_local_proxy_auth)])
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "provider": "openrouter",
        "default_model": DEFAULT_MODEL,
    }


@app.get("/v1/models", dependencies=[Depends(verify_local_proxy_auth)])
async def list_models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": DEFAULT_MODEL,
                "object": "model",
                "owned_by": "openrouter",
            }
        ],
    }


@app.post(
    "/v1/audio/transcriptions",
    dependencies=[Depends(verify_local_proxy_auth)],
    response_model=None,
)
async def create_transcription(
    request: Request,
    file: UploadFile = File(...),
    model: str = Form(DEFAULT_MODEL),
    language: str | None = Form(default=None),
    prompt: str | None = Form(default=None),
    temperature: float | None = Form(default=None),
    response_format: str | None = Form(default=None),
) -> JSONResponse | PlainTextResponse:
    start = time.perf_counter()
    upstream_status = "not_sent"
    file_bytes = b""

    try:
        normalized_format = (response_format or "").strip().lower() or "json"
        selected_model = model.strip() or DEFAULT_MODEL
        if normalized_format not in TEXT_RESPONSE_FORMATS and normalized_format not in JSON_RESPONSE_FORMATS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Unsupported response_format. "
                    "Use one of: json, verbose_json, text."
                ),
            )

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
            "Incoming transcription filename=%s size_bytes=%s model=%s client=%s",
            file.filename,
            file_size,
            selected_model,
            request.client.host if request.client else "unknown",
        )

        audio_base64 = base64.b64encode(file_bytes).decode("ascii")
        payload = build_openrouter_payload(
            model=selected_model,
            audio_base64=audio_base64,
            audio_format=audio_format,
            language=language.strip() if language else None,
            prompt=prompt.strip() if prompt else None,
            temperature=temperature,
        )

        timeout = httpx.Timeout(DEFAULT_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                OPENROUTER_TRANSCRIPTIONS_URL,
                headers=build_openrouter_headers(),
                json=payload,
            )

        upstream_status = str(response.status_code)
        logger.info("OpenRouter response status=%s", response.status_code)

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type.lower():
            upstream_payload: Any = response.json()
        else:
            upstream_payload = response.text

        if response.status_code in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}:
            raise HTTPException(
                status_code=response.status_code,
                detail={
                    "message": "OpenRouter authorization failed. Check OPENROUTER_API_KEY.",
                    "upstream": upstream_payload,
                },
            )

        if response.status_code == status.HTTP_400_BAD_REQUEST:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "OpenRouter rejected the request.",
                    "upstream": upstream_payload,
                },
            )

        if response.is_error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "message": f"OpenRouter request failed with status {response.status_code}.",
                    "upstream": upstream_payload,
                },
            )

        text = extract_text(upstream_payload)
        if not text:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "message": "OpenRouter response did not contain transcription text.",
                    "upstream": upstream_payload,
                },
            )

        if normalized_format in TEXT_RESPONSE_FORMATS:
            return PlainTextResponse(content=text)

        if isinstance(upstream_payload, dict) and isinstance(upstream_payload.get("text"), str):
            return JSONResponse(content=upstream_payload)

        return JSONResponse(content={"text": text})
    except httpx.TimeoutException as exc:
        upstream_status = "timeout"
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=(
                "Timed out while waiting for OpenRouter. "
                "Try a smaller file or increase OPENROUTER_TIMEOUT_SECONDS."
            ),
        ) from exc
    except httpx.HTTPError as exc:
        upstream_status = "http_error"
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reach OpenRouter: {exc}",
        ) from exc
    finally:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            "Completed transcription filename=%s size_bytes=%s model=%s upstream_status=%s duration_ms=%s",
            file.filename,
            len(file_bytes),
            selected_model if "selected_model" in locals() else model,
            upstream_status,
            duration_ms,
        )
        await file.close()
