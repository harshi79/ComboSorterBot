#!/usr/bin/env python3
"""
File Fixer Bot – Universal Cookie & Combo Cleaner
Made by @WhoEvenYori
Deploy on Render / any hosting.
"""

import os
import re
import asyncio
import tempfile
import logging
from aiohttp import web
from telegram import Update, Document
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- Config ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set.")

# ---------- Helper Functions ----------
def is_cookie_file(content: str) -> bool:
    """
    Heuristic: high proportion of lines with '=' and no '@',
    or contains known cookie names.
    """
    lines = content.splitlines()
    eq_lines = 0
    total = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        total += 1
        if '=' in line and '@' not in line:
            eq_lines += 1
    if total == 0:
        return False
    if eq_lines / total > 0.3:
        return True
    # Common cookie names
    if any(key in content for key in [
        'NetflixId', 'session-id', 'ubid-main', 'at-main', 'x-main',
        'sp_t', 'spotify', 'accessToken', 'i18n-prefs', 'sess-at'
    ]):
        return True
    return False

def is_email_pass_combo(content: str) -> bool:
    """
    Heuristic: many lines containing '@' and a separator (: | ; space).
    """
    lines = content.splitlines()
    email_lines = 0
    total = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        total += 1
        if '@' in line and re.search(r'[:;|]', line):
            email_lines += 1
    if total == 0:
        return False
    return (email_lines / total) > 0.4

def extract_cookies(content: str) -> str:
    """Extract all key=value cookie lines."""
    lines = content.splitlines()
    cookies = []
    netscape_pattern = re.compile(r'^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)$')

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Netscape format (7 fields)
        m = netscape_pattern.match(line)
        if m:
            name, value = m.group(6), m.group(7)
            if name and value:
                cookies.append(f"{name}={value}")
            continue

        # Standard "name=value"
        if '=' in line:
            # Avoid JSON, HTML, email lines
            if line.count('=') == 1 and not re.search(r'[<>{}"]', line):
                parts = line.split('=', 1)
                if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                    if '@' not in parts[1]:  # not email
                        cookies.append(line.strip())

        # Also catch lines with known cookie names even if messy
        if any(key in line for key in [
            'NetflixId', 'session-id', 'ubid-main', 'at-main', 'x-main',
            'sp_t', 'spotify', 'accessToken', 'i18n-prefs', 'sess-at'
        ]):
            m = re.search(r'([a-zA-Z0-9_-]+)=([^\s]+)', line)
            if m:
                cookies.append(f"{m.group(1)}={m.group(2)}")

    # If still empty but file looks like cookie (has domain/path/secure)
    if not cookies and any(word in content.lower() for word in ['domain', 'path', 'secure']):
        for line in lines:
            if '=' in line:
                parts = line.split('=', 1)
                if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                    cookies.append(line.strip())

    return '\n'.join(cookies)

def clean_email_pass(content: str) -> str:
    """Extract email:pass from each line."""
    cleaned = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        # Try common separators: : | ; (and space)
        match = re.search(r'([^\s:;|]+@[^\s:;|]+)\s*[:;|]\s*([^\s:;|]+)', line)
        if match:
            email, pwd = match.group(1).strip(), match.group(2).strip()
            cleaned.append(f"{email}:{pwd}")
            continue
        # Space separated: email pass
        parts = line.split()
        if len(parts) >= 2 and '@' in parts[0]:
            cleaned.append(f"{parts[0]}:{parts[1]}")
            continue
        # Already has colon and looks like email:pass
        if ':' in line and '@' in line.split(':')[0]:
            cleaned.append(line.strip())
    return '\n'.join(cleaned)

def fix_file(content: str) -> str:
    """Main fixer logic."""
    if is_cookie_file(content):
        result = extract_cookies(content)
        return result if result else "No cookies found."
    elif is_email_pass_combo(content):
        result = clean_email_pass(content)
        return result if result else "No valid email:pass found."
    else:
        # Fallback: try email:pass cleaning anyway
        result = clean_email_pass(content)
        return result if result else content

# ---------- Bot Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message with branding."""
    await update.message.reply_text(
        "📁 **Universal File Fixer Bot**\n\n"
        "Send me a `.txt` file containing:\n"
        "• **Cookies** (Netflix, Prime Video, Spotify, etc.) → I'll extract all `key=value` cookies.\n"
        "• **Email:Pass combos** → I'll clean and format as `email:pass`.\n\n"
        "I'll return a cleaned version of the file.\n\n"
        "───────\n"
        "**Made by** @WhoEvenYori"
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process uploaded .txt files."""
    document = update.message.document
    if not document:
        await update.message.reply_text("Please send a document.")
        return

    if not document.file_name.lower().endswith('.txt'):
        await update.message.reply_text("Only `.txt` files are supported.")
        return

    # Download file to temp
    file = await context.bot.get_file(document.file_id)
    tmp_in = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
    tmp_in.close()
    await file.download_to_drive(tmp_in.name)

    try:
        with open(tmp_in.name, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception as e:
        logger.error(f"Read error: {e}")
        await update.message.reply_text(f"Error reading file: {e}")
        os.unlink(tmp_in.name)
        return

    # Fix content
    fixed = fix_file(content)
    if not fixed:
        fixed = "No valid content extracted."

    # Prepare output filename
    base, ext = os.path.splitext(document.file_name)
    out_filename = f"{base}_fixed.txt"

    # Write fixed content to temp file
    tmp_out = tempfile.NamedTemporaryFile(delete=False, suffix='.txt', mode='w', encoding='utf-8')
    tmp_out.write(fixed)
    tmp_out.close()

    try:
        with open(tmp_out.name, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=out_filename,
                caption="✅ **Fixed file ready.**"
            )
    except Exception as e:
        logger.error(f"Send error: {e}")
        await update.message.reply_text(f"Error sending file: {e}")
    finally:
        os.unlink(tmp_in.name)
        if os.path.exists(tmp_out.name):
            os.unlink(tmp_out.name)

# ---------- Health Server ----------
async def health_check(request):
    return web.Response(text="OK", status=200)

async def run_health_server():
    app = web.Application()
    app.router.add_get('/health', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host='0.0.0.0', port=8080)
    await site.start()
    logger.info("Health server running on port 8080")
    # Keep running
    await asyncio.Event().wait()

# ---------- Main ----------
async def main():
    """Start bot and health server concurrently."""
    # Bot
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    # Start polling (non-blocking)
    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    logger.info("Bot started polling.")

    # Start health server in the background
    health_task = asyncio.create_task(run_health_server())

    # Wait until both run (health task never ends normally)
    await health_task

if __name__ == "__main__":
    asyncio.run(main())
