import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from config import TELEGRAM_TOKEN, OWNER_CHAT_ID
from memory import init_db, clear_history, get_all_memories, get_usage_stats
from agent import run_agent

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def is_authorized(chat_id: int) -> bool:
    if OWNER_CHAT_ID is None:
        return True  # no restriction if OWNER_CHAT_ID not set
    return chat_id == OWNER_CHAT_ID


async def _on_application_error(update, context):
    """Catch-all PTB error handler — persists exceptions to error_log."""
    from error_log import log_error
    err = context.error
    err_type = type(err).__name__ if err else "UnknownError"
    user_msg = None
    chat_id = OWNER_CHAT_ID
    try:
        if update and getattr(update, "effective_chat", None):
            chat_id = update.effective_chat.id
        if update and getattr(update, "effective_message", None):
            user_msg = update.effective_message.text
    except Exception:
        pass
    logger.error(f"PTB error: {err_type}: {err}", exc_info=err)
    await log_error(
        chat_id,
        "ptb_error",
        "Unhandled exception in PTB application",
        f"{err_type}: {err}",
        user_message=user_msg,
    )


async def _run_pulse_check(context):
    """Periodic job to check if a proactive pulse should be sent."""
    from pulse import generate_pulse
    chat_id = OWNER_CHAT_ID
    if not chat_id:
        return
    try:
        result = await generate_pulse(chat_id)
        if result:
            await context.bot.send_message(chat_id=chat_id, text=result["message"])
            logger.info(f"Pulse sent: {result['topic']} ({result['confidence']:.2f})")
    except Exception as e:
        logger.error(f"Pulse check failed: {e}", exc_info=True)
        from error_log import log_error
        await log_error(chat_id, "pulse_error", "Pulse check failed", str(e))


async def _run_news_digest(context):
    """Morning job to send a personalized news digest."""
    from news_digest import generate_news_digest
    chat_id = OWNER_CHAT_ID
    if not chat_id:
        return
    try:
        digest = await generate_news_digest(chat_id)
        if digest:
            await context.bot.send_message(chat_id=chat_id, text=digest, parse_mode="Markdown")
            logger.info("Morning news digest sent")
    except Exception as e:
        logger.error(f"News digest failed: {e}", exc_info=True)
        from error_log import log_error
        await log_error(chat_id, "news_digest_error", "News digest generation failed", str(e))


async def post_init(application: Application) -> None:
    await init_db()
    from tools.scheduler import set_app
    set_app(application)
    from tools.browser import set_app as set_browser_app
    set_browser_app(application)

    application.add_error_handler(_on_application_error)

    # Default misfire_grace_time is 1s — too tight when the event loop briefly stalls
    # on Telegram long-polling or transient network errors. Without this, scheduled
    # jobs (morning_weather, daily_news, etc.) get silently dropped as "missed".
    # NOTE: scheduler.configure() clears executors/jobstores — must pass PTB's
    # scheduler_configuration back in, otherwise PTB's AsyncIOExecutor is orphaned
    # and shutdown crashes with AttributeError on _pending_futures.
    application.job_queue.scheduler.configure(
        **application.job_queue.scheduler_configuration,
        job_defaults={"misfire_grace_time": 600, "coalesce": True},
    )

    # Schedule proactive pulse checks every 3 hours (the pulse system has its own cooldowns)
    application.job_queue.run_repeating(
        _run_pulse_check,
        interval=3 * 3600,  # every 3 hours
        first=300,  # first check 5 min after startup
        name="proactive_pulse",
    )

    # Restore user-created scheduled jobs from database
    from tools.scheduler import restore_jobs
    await restore_jobs()

    # Observability (no-op without OTEL_EXPORTER_OTLP_ENDPOINT / PROMETHEUS_PORT)
    try:
        from tools.observability import init_observability
        init_observability()
    except Exception as e:
        logger.warning(f"observability init failed: {e}")

    logger.info("Database initialized, scheduler ready, pulse scheduled")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        await update.message.reply_text("Unauthorized.")
        return

    # Log the chat_id so the user can set OWNER_CHAT_ID
    logger.info(f"Chat started by chat_id: {chat_id}")

    await update.message.reply_text(
        "Hey! I'm your personal AI agent.\n\n"
        "Just send me any message and I'll help you out.\n\n"
        "Commands:\n"
        "/new - Start fresh session (archives current)\n"
        "/clear - Clear conversation history\n"
        "/memories - List stored memories\n"
        "/usage - Show API usage stats & cost\n"
        "/whoami - Show your chat ID\n"
        "\nI can also set reminders, daily scheduled messages, and manage your calendar!"
    )


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start a fresh session - summarizes current conversation then clears it."""
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return

    from memory import load_history
    history = await load_history(chat_id, limit=60)

    if len(history) >= 4:
        # Generate a summary before clearing
        try:
            from agent import generate_daily_summary
            await generate_daily_summary(chat_id)
        except Exception:
            pass

    await clear_history(chat_id)
    await update.message.reply_text("Fresh session started. Previous context has been archived.")


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return
    await clear_history(chat_id)
    await update.message.reply_text("Conversation history cleared.")


async def cmd_memories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return
    memories = await get_all_memories(chat_id)
    if not memories:
        await update.message.reply_text("No memories stored yet.")
        return
    text = "Stored memories:\n\n"
    for m in memories:
        text += f"  {m['key']}: {m['value']}\n"
    await send_long_message(update, text)


async def cmd_whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"Your chat ID: `{chat_id}`", parse_mode="Markdown")


async def cmd_usage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return
    stats = await get_usage_stats(chat_id)

    from config import PRICE_INPUT_PER_M, PRICE_OUTPUT_PER_M
    price_in, price_out = PRICE_INPUT_PER_M, PRICE_OUTPUT_PER_M

    lines = ["*API Usage Stats*\n"]
    labels = {"today": "Today", "last_30_days": "Last 30 days", "total": "All time"}
    for key, label in labels.items():
        d = stats[key]
        cw = d.get("cache_creation_tokens", 0)
        cr = d.get("cache_read_tokens", 0)
        total_tok = d["input_tokens"] + d["output_tokens"] + cw + cr
        cost = (
            d["input_tokens"] * price_in
            + d["output_tokens"] * price_out
            + cw * price_in * 1.25
            + cr * price_in * 0.1
        ) / 1_000_000
        cache_part = f" | cache: w={cw:,} r={cr:,}" if (cw or cr) else ""
        lines.append(
            f"*{label}:* {d['requests']} requests | "
            f"{total_tok:,} tokens{cache_part} | ~${cost:.2f}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_setcredit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return
    args = context.args or []
    if not args:
        from tools.anthropic_billing import get_credit_record
        record = await get_credit_record()
        if record is None:
            await update.message.reply_text(
                "No credit balance recorded yet.\nUsage: /setcredit <usd>  (e.g. /setcredit 9.50)"
            )
            return
        credit, as_of = record
        from datetime import datetime, timezone
        as_of_str = datetime.fromtimestamp(as_of, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        await update.message.reply_text(
            f"Current recorded balance: *${credit:.2f}* (as of {as_of_str})\n"
            f"Usage: /setcredit <usd> to update.",
            parse_mode="Markdown",
        )
        return
    try:
        amount = float(args[0])
    except ValueError:
        await update.message.reply_text(f"Not a valid amount: {args[0]!r}")
        return
    if amount < 0:
        await update.message.reply_text("Amount must be non-negative.")
        return
    from tools.anthropic_billing import set_credit_balance
    await set_credit_balance(amount)
    await update.message.reply_text(
        f"✅ Credit balance set to *${amount:.2f}*. Spend tracking restarts from now.",
        parse_mode="Markdown",
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return

    user_text = update.message.text
    if not user_text:
        return

    logger.info(f"[{chat_id}] User: {user_text[:100]}")

    # Track user activity
    try:
        from habits import track_message
        await track_message(chat_id, len(user_text))
    except Exception:
        pass

    await update.effective_chat.send_action("typing")

    # Status message that gets edited as tools run
    status_msg = None
    last_status = [None]  # Use list to allow mutation in closure

    async def status_callback(text: str):
        nonlocal status_msg
        try:
            if status_msg is None:
                status_msg = await update.message.reply_text(f"⏳ {text}")
                last_status[0] = text
            elif text != last_status[0]:
                await status_msg.edit_text(f"⏳ {text}")
                last_status[0] = text
            await update.effective_chat.send_action("typing")
        except Exception:
            pass

    try:
        response = await run_agent(chat_id, user_text, status_callback=status_callback)
        logger.info(f"[{chat_id}] Agent: {response[:100]}")
    except Exception as e:
        logger.error(f"Agent error: {e}", exc_info=True)
        from error_log import log_error
        await log_error(chat_id, "agent_error", "Top-level agent crash", str(e), user_message=user_text)
        response = f"Something went wrong: {e}"

    # Delete the status message before sending the real response
    if status_msg:
        try:
            await status_msg.delete()
        except Exception:
            pass

    await send_long_message(update, response)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return

    import base64

    # Get the highest resolution photo
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    photo_bytes = bytes(await file.download_as_bytearray())

    caption = update.message.caption or ""
    logger.info(f"[{chat_id}] User sent photo ({len(photo_bytes)} bytes) caption: {caption[:100]}")

    await update.effective_chat.send_action("typing")

    image_data = {
        "base64": base64.b64encode(photo_bytes).decode("utf-8"),
        "media_type": "image/jpeg",
    }

    status_msg = None
    last_status = [None]

    async def status_callback(text: str):
        nonlocal status_msg
        try:
            if status_msg is None:
                status_msg = await update.message.reply_text(f"⏳ {text}")
                last_status[0] = text
            elif text != last_status[0]:
                await status_msg.edit_text(f"⏳ {text}")
                last_status[0] = text
        except Exception:
            pass

    try:
        response = await run_agent(chat_id, caption, image_data=image_data, status_callback=status_callback)
        logger.info(f"[{chat_id}] Agent: {response[:100]}")
    except Exception as e:
        logger.error(f"Agent error: {e}", exc_info=True)
        response = f"Something went wrong: {e}"

    if status_msg:
        try:
            await status_msg.delete()
        except Exception:
            pass

    await send_long_message(update, response)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Transcribe a Telegram voice message via OpenAI Whisper and run it
    through the agent as if it were text."""
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return

    voice = update.message.voice or update.message.audio
    if not voice:
        return

    file = await context.bot.get_file(voice.file_id)
    audio_bytes = bytes(await file.download_as_bytearray())
    logger.info(f"[{chat_id}] User sent voice ({len(audio_bytes)} bytes, ~{getattr(voice, 'duration', '?')}s)")

    await update.effective_chat.send_action("typing")

    # Transcribe
    try:
        from voice_input import transcribe_audio
        transcript = await transcribe_audio(audio_bytes)
    except Exception as e:
        logger.error(f"Transcription failed: {e}", exc_info=True)
        from error_log import log_error
        await log_error(chat_id, "transcription_error", "Whisper transcription failed", str(e))
        await update.message.reply_text(f"⚠️ לא הצלחתי לתמלל את ההקלטה: {e}")
        return

    if not transcript:
        await update.message.reply_text("⚠️ ההקלטה ריקה או לא הצלחתי להבין אותה.")
        return

    logger.info(f"[{chat_id}] Transcript: {transcript[:100]}")
    # Show user what we heard
    await update.message.reply_text(f"🎙 {transcript}")

    # Run agent on the transcript (same flow as handle_message)
    status_msg = None
    last_status = [None]

    async def status_callback(text: str):
        nonlocal status_msg
        try:
            if status_msg is None:
                status_msg = await update.message.reply_text(f"⏳ {text}")
                last_status[0] = text
            elif text != last_status[0]:
                await status_msg.edit_text(f"⏳ {text}")
                last_status[0] = text
            await update.effective_chat.send_action("typing")
        except Exception:
            pass

    try:
        response = await run_agent(chat_id, transcript, status_callback=status_callback)
        logger.info(f"[{chat_id}] Agent: {response[:100]}")
    except Exception as e:
        logger.error(f"Agent error: {e}", exc_info=True)
        from error_log import log_error
        await log_error(chat_id, "agent_error", "Top-level agent crash (voice)", str(e), user_message=transcript)
        response = f"Something went wrong: {e}"

    if status_msg:
        try:
            await status_msg.delete()
        except Exception:
            pass

    await send_long_message(update, response)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle document uploads (PDF, text files, etc.)."""
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return

    doc = update.message.document
    if not doc:
        return

    file_name = doc.file_name or "document"
    mime_type = doc.mime_type or ""
    file_size = doc.file_size or 0

    # Supported document types
    supported_mimes = {
        "application/pdf", "text/plain", "text/csv", "text/html",
        "application/json", "text/markdown",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }

    # Cap document size at 10MB
    if file_size > 10 * 1024 * 1024:
        await update.message.reply_text("File is too large (max 10MB). Please send a smaller file.")
        return

    # Check if we can handle this type
    is_supported = mime_type in supported_mimes or file_name.endswith(('.pdf', '.txt', '.csv', '.json', '.md', '.html'))
    if not is_supported:
        await update.message.reply_text(
            f"I can't process this file type ({mime_type or 'unknown'}). "
            "I support: PDF, TXT, CSV, JSON, MD, HTML files."
        )
        return

    logger.info(f"[{chat_id}] User sent document: {file_name} ({mime_type}, {file_size} bytes)")

    file = await context.bot.get_file(doc.file_id)
    doc_bytes = bytes(await file.download_as_bytearray())

    caption = update.message.caption or f"I'm sending you this file: {file_name}. Please analyze it."

    await update.effective_chat.send_action("typing")

    import base64
    # For text-based files, send as text content
    text_mimes = {"text/plain", "text/csv", "text/html", "application/json", "text/markdown"}
    is_text = mime_type in text_mimes or file_name.endswith(('.txt', '.csv', '.json', '.md', '.html'))

    status_msg = None
    last_status = [None]

    async def status_callback(text: str):
        nonlocal status_msg
        try:
            if status_msg is None:
                status_msg = await update.message.reply_text(f"\u23f3 {text}")
                last_status[0] = text
            elif text != last_status[0]:
                await status_msg.edit_text(f"\u23f3 {text}")
                last_status[0] = text
        except Exception:
            pass

    try:
        if is_text:
            # Send text content directly
            try:
                file_text = doc_bytes.decode("utf-8")
            except UnicodeDecodeError:
                file_text = doc_bytes.decode("latin-1")

            # Truncate very long files
            if len(file_text) > 50000:
                file_text = file_text[:50000] + "\n\n[... truncated, file too long ...]"

            user_text = f"{caption}\n\n--- File: {file_name} ---\n{file_text}"
            response = await run_agent(chat_id, user_text, status_callback=status_callback)
        else:
            # Binary files (PDF, docx, xlsx) — send as base64 to the model
            image_data = {
                "base64": base64.b64encode(doc_bytes).decode("utf-8"),
                "media_type": mime_type or "application/pdf",
            }
            response = await run_agent(chat_id, caption, image_data=image_data, status_callback=status_callback)

        logger.info(f"[{chat_id}] Agent: {response[:100]}")
    except Exception as e:
        logger.error(f"Document processing error: {e}", exc_info=True)
        from error_log import log_error
        await log_error(chat_id, "document_error", f"Document processing failed: {file_name}", str(e))
        response = f"Failed to process the document: {e}"

    if status_msg:
        try:
            await status_msg.delete()
        except Exception:
            pass

    await send_long_message(update, response)


async def send_long_message(update: Update, text: str, chunk_size: int = 4000) -> None:
    if not text:
        await update.message.reply_text("(empty response)")
        return

    while text:
        if len(text) <= chunk_size:
            await _send_markdown(update, text)
            break

        split_at = text.rfind("\n", 0, chunk_size)
        if split_at == -1 or split_at < chunk_size // 2:
            split_at = chunk_size

        chunk = text[:split_at]
        text = text[split_at:].lstrip("\n")
        await _send_markdown(update, chunk)


async def _send_markdown(update: Update, text: str) -> None:
    """Send with Markdown parsing, fall back to plain text if parsing fails."""
    try:
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(text)


async def cmd_errors(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return
    from error_log import get_error_summary
    summary = await get_error_summary()
    await send_long_message(update, f"*Recent Errors*\n\n{summary}")


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("memories", cmd_memories))
    app.add_handler(CommandHandler("whoami", cmd_whoami))
    app.add_handler(CommandHandler("usage", cmd_usage))
    app.add_handler(CommandHandler("setcredit", cmd_setcredit))
    app.add_handler(CommandHandler("errors", cmd_errors))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
