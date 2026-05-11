"""Speech-to-text via OpenAI Whisper.

Used by the Telegram voice-message handler in bot.py. Independent of
AI_PROVIDER — always uses OpenAI for STT regardless of which provider
powers the main agent.
"""
from __future__ import annotations
import io
import logging
from openai import AsyncOpenAI
from config import OPENAI_API_KEY, BOT_LANGUAGE

logger = logging.getLogger(__name__)

# Map BOT_LANGUAGE values to ISO 639-1 codes Whisper accepts. Add more here
# if the bot is configured for additional languages.
_LANG_CODE = {
    "hebrew": "he",
    "english": "en",
    "arabic": "ar",
    "russian": "ru",
    "spanish": "es",
    "french": "fr",
}.get((BOT_LANGUAGE or "").lower())


async def transcribe_audio(audio_bytes: bytes, filename: str = "voice.ogg") -> str:
    """Transcribe a voice clip using OpenAI Whisper.

    audio_bytes: raw bytes of the audio file (Telegram voice is OGG/Opus).
    Returns the transcript text. Empty string if Whisper returns nothing.
    """
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not configured — cannot transcribe")

    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = filename  # OpenAI SDK uses filename to detect format

    kwargs = {"model": "whisper-1", "file": audio_file}
    if _LANG_CODE:
        kwargs["language"] = _LANG_CODE

    response = await client.audio.transcriptions.create(**kwargs)
    return (response.text or "").strip()
