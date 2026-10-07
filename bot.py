import os
import re
import asyncio
import logging

from flask import Flask, request, jsonify

from telegram import (
    Bot,
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.environ["BOT_TOKEN"]
SOURCE_CHAT_ID = int(os.environ["SOURCE_CHAT_ID"])
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]

PORT = int(os.environ.get("PORT", "10000"))


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# =========================================================
# FLASK
# =========================================================

app = Flask(__name__)


# =========================================================
# TELEGRAM
# =========================================================

telegram_bot = Bot(BOT_TOKEN)

application = (
    Application.builder()
    .token(BOT_TOKEN)
    .build()
)


# =========================================================
# SIMPLE MEMORY STORAGE
# =========================================================

latest_content = {
    "image_file_id": None,
    "url": None,
    "source_message_id": None,
}


# =========================================================
# URL EXTRACTOR
# =========================================================

def extract_url(text):
    if not text:
        return None

    match = re.search(
        r"https?://[^\s]+",
        text
    )

    if not match:
        return None

    url = match.group(0)

    # Remove common trailing characters
    url = url.rstrip(".,!?)]}")

    return url


# =========================================================
# EXTRACT SOURCE CONTENT
# =========================================================

def extract_content(message):

    text = message.caption or message.text or ""

    url = extract_url(text)

    if not url:
        return None

    image_file_id = None

    # Telegram photo
    if message.photo:
        image_file_id = message.photo[-1].file_id

    # Telegram image document
    elif message.document:
        mime = message.document.mime_type or ""

        if mime.startswith("image/"):
            image_file_id = message.document.file_id

    if not image_file_id:
        return None

    return {
        "image_file_id": image_file_id,
        "url": url,
        "source_message_id": message.message_id,
    }


# =========================================================
# PROCESS TELEGRAM UPDATE
# =========================================================

async def process_update(update_data):

    update = Update.de_json(
        update_data,
        telegram_bot
    )

    message = None

    # New channel post
    if update.channel_post:
        message = update.channel_post

    # Edited channel post
    elif update.edited_channel_post:
        message = update.edited_channel_post

    # Group message
    elif update.message:
        message = update.message

    # Edited group message
    elif update.edited_message:
        message = update.edited_message

    if not message:
        return

    if message.chat.id != SOURCE_CHAT_ID:
        return

    content = extract_content(message)

    if not content:
        logger.info(
            "Ignored source message %s",
            message.message_id
        )
        return

    latest_content.update(content)

    logger.info(
        "Content updated: message_id=%s url=%s",
        content["source_message_id"],
        content["url"],
    )


# =========================================================
# /START
# =========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not latest_content["image_file_id"]:
        await update.message.reply_text(
            "Content is not available yet."
        )
        return

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "▶️ WATCH HERE",
                    url=latest_content["url"]
                )
            ]
        ]
    )

    await update.message.reply_photo(
        photo=latest_content["image_file_id"],
        reply_markup=keyboard
    )


# =========================================================
# REGISTER HANDLERS
# =========================================================

application.add_handler(
    CommandHandler(
        "start",
        start_command
    )
)


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route("/", methods=["GET"])
def home():

    return jsonify({
        "status": "online",
        "bot": "telegram-video-bot"
    })


# =========================================================
# WEBHOOK
# =========================================================

@app.route(
    "/telegram/webhook",
    methods=["POST"]
)
def telegram_webhook():

    # Verify secret
    secret = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token"
    )

    if secret != WEBHOOK_SECRET:
        return jsonify({
            "error": "unauthorized"
        }), 401

    try:

        update_data = request.get_json(
            force=True
        )

        asyncio.run(
            process_update(
                update_data
            )
        )

        return jsonify({
            "ok": True
        })

    except Exception as e:

        logger.exception(
            "Webhook error"
        )

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


# =========================================================
# START WEBHOOK
# =========================================================

@app.route(
    "/setup-webhook",
    methods=["GET"]
)
def setup_webhook():

    base_url = request.host_url.rstrip("/")

    webhook_url = (
        f"{base_url}/telegram/webhook"
    )

    asyncio.run(
        telegram_bot.set_webhook(
            url=webhook_url,
            secret_token=WEBHOOK_SECRET,
            allowed_updates=[
                "message",
                "edited_message",
                "channel_post",
                "edited_channel_post",
            ],
        )
    )

    return jsonify({
        "ok": True,
        "webhook": webhook_url
    })


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=PORT
    )
