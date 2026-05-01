"""Prompt Master Telegram Bot — main entry point."""
import asyncio
import logging
import os
from typing import Optional

import anthropic
from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import prompt_master as pm
from storage import Prompt, PromptStorage

load_dotenv()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
DATA_FILE = os.getenv("DATA_FILE", "prompts.json")

# ConversationHandler states
ADD_NAME, ADD_TEMPLATE, ADD_DESC, ADD_CATEGORY = range(4)
USE_VARS = 10
ASK_INPUT = 20


def storage() -> PromptStorage:
    if not hasattr(storage, "_instance"):
        storage._instance = PromptStorage(DATA_FILE)
    return storage._instance


def claude_client() -> anthropic.AsyncAnthropic:
    if not hasattr(claude_client, "_instance"):
        claude_client._instance = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    return claude_client._instance


def _prompt_list_keyboard(prompts: list[Prompt], action: str = "use") -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(f"📝 {p.name}", callback_data=f"{action}:{p.name}")]
        for p in prompts
    ]
    return InlineKeyboardMarkup(buttons)


# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Prompt Master* 🤖\n\n"
        "Manage prompt templates and chat with Claude.\n\n"
        "Commands:\n"
        "• /list — browse all prompts\n"
        "• /add — create a new prompt\n"
        "• /use `<name>` — activate a prompt\n"
        "• /active — show your active prompt\n"
        "• /clear — deactivate prompt\n"
        "• /ask `<text>` — ask Claude (uses active prompt)\n"
        "• /delete `<name>` — delete a prompt\n"
        "• /help — show this message",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /list ─────────────────────────────────────────────────────────────────────

async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    prompts = storage().list_all()
    if not prompts:
        await update.message.reply_text("No prompts saved yet. Use /add to create one.")
        return
    lines = []
    for p in prompts:
        vars_ = pm.extract_variables(p.template)
        var_str = f" `{{{', '.join(vars_)}}}`" if vars_ else ""
        lines.append(f"• *{p.name}* [{p.category}]{var_str}\n  _{p.description}_")
    await update.message.reply_text(
        "\n\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_prompt_list_keyboard(prompts, action="use"),
    )


# ── /use <name> ───────────────────────────────────────────────────────────────

async def cmd_use(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args:
        prompts = storage().list_all()
        if not prompts:
            await update.message.reply_text("No prompts available. Use /add first.")
            return
        await update.message.reply_text(
            "Choose a prompt to activate:",
            reply_markup=_prompt_list_keyboard(prompts, action="use"),
        )
        return
    await _activate_prompt(update, ctx, args[0])


async def _activate_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE, name: str):
    prompt = storage().get(name)
    if not prompt:
        msg = update.message or update.callback_query.message
        await msg.reply_text(f"Prompt `{name}` not found.", parse_mode=ParseMode.MARKDOWN)
        return
    storage().set_active(update.effective_user.id, name)
    vars_ = pm.extract_variables(prompt.template)
    var_note = (
        f"\n\nThis template has variables: `{{{', '.join(vars_)}}}`\n"
        "When you /ask, prefix your message with `var=value` pairs, e.g.:\n"
        "`language=Python\nreview this code...`"
        if vars_ else ""
    )
    msg = update.message or update.callback_query.message
    await msg.reply_text(
        f"✅ Active prompt set to *{name}*\n_{prompt.description}_{var_note}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cb_use(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, name = query.data.split(":", 1)
    await _activate_prompt(update, ctx, name)


# ── /active & /clear ──────────────────────────────────────────────────────────

async def cmd_active(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    prompt = storage().get_active(update.effective_user.id)
    if not prompt:
        await update.message.reply_text("No active prompt. Use /use to activate one.")
        return
    vars_ = pm.extract_variables(prompt.template)
    await update.message.reply_text(
        f"*Active:* {prompt.name}\n_{prompt.description}_\n\n"
        f"```\n{prompt.template}\n```"
        + (f"\n\nVariables: `{', '.join(vars_)}`" if vars_ else ""),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    storage().clear_active(update.effective_user.id)
    await update.message.reply_text("Active prompt cleared.")


# ── /ask <text> ───────────────────────────────────────────────────────────────

async def cmd_ask(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /ask <your question>")
        return
    user_text = " ".join(ctx.args)
    await _handle_ask(update, ctx, user_text)


async def handle_plain_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Route plain messages to Claude if an active prompt is set."""
    await _handle_ask(update, ctx, update.message.text)


async def _handle_ask(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user_text: str):
    prompt = storage().get_active(update.effective_user.id)

    variables: dict[str, str] = {}
    message_body = user_text

    # Parse leading key=value lines as variable overrides
    lines = user_text.splitlines()
    body_start = 0
    for i, line in enumerate(lines):
        if "=" in line and not line.startswith(" "):
            k, _, v = line.partition("=")
            variables[k.strip()] = v.strip()
            body_start = i + 1
        else:
            break
    if body_start:
        message_body = "\n".join(lines[body_start:]).strip()

    if not message_body:
        await update.message.reply_text("Please include a message after the variables.")
        return

    if prompt:
        messages, system = pm.build_messages(prompt, message_body, variables)
    else:
        # No active prompt — plain Claude chat
        system = "You are a helpful assistant."
        messages = [{"role": "user", "content": message_body}]

    thinking_msg = await update.message.reply_text("⏳ Thinking…")

    try:
        chunks: list[str] = []
        async for chunk in pm.ask_claude(claude_client(), system, messages):
            chunks.append(chunk)

        full_response = "".join(chunks)
        prefix = f"*[{prompt.name}]* " if prompt else ""
        await thinking_msg.edit_text(
            prefix + full_response,
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.exception("Claude API error")
        await thinking_msg.edit_text(f"Error: {e}")


# ── /add (ConversationHandler) ────────────────────────────────────────────────

async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.clear()
    await update.message.reply_text(
        "Let's create a new prompt.\n\nStep 1/4 — Enter a *name* (no spaces, e.g. `my-prompt`):",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ADD_NAME


async def add_get_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip().replace(" ", "-")
    if storage().get(name):
        await update.message.reply_text(
            f"A prompt named `{name}` already exists. Choose a different name:",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ADD_NAME
    ctx.user_data["name"] = name
    await update.message.reply_text(
        f"Name: *{name}*\n\nStep 2/4 — Enter the *system prompt template*.\n"
        "Use `{variable}` placeholders for dynamic values.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ADD_TEMPLATE


async def add_get_template(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["template"] = update.message.text.strip()
    vars_ = pm.extract_variables(ctx.user_data["template"])
    var_note = f"\nDetected variables: `{', '.join(vars_)}`" if vars_ else ""
    await update.message.reply_text(
        f"Template saved.{var_note}\n\nStep 3/4 — Enter a short *description* (or send `-` to skip):",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ADD_DESC


async def add_get_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    ctx.user_data["description"] = "" if text == "-" else text
    await update.message.reply_text(
        "Step 4/4 — Enter a *category* (e.g. coding, writing, language, education) or `-` for general:",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ADD_CATEGORY


async def add_get_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    category = "general" if text == "-" else text.lower()
    data = ctx.user_data
    prompt = Prompt(
        name=data["name"],
        template=data["template"],
        description=data.get("description", ""),
        category=category,
    )
    storage().add(prompt)
    await update.message.reply_text(
        f"✅ Prompt *{prompt.name}* saved!\n"
        f"Use /use `{prompt.name}` to activate it.",
        parse_mode=ParseMode.MARKDOWN,
    )
    ctx.user_data.clear()
    return ConversationHandler.END


async def add_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.clear()
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


# ── /delete <name> ────────────────────────────────────────────────────────────

async def cmd_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /delete <name>")
        return
    name = ctx.args[0]
    if storage().delete(name):
        await update.message.reply_text(f"🗑 Prompt `{name}` deleted.", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"Prompt `{name}` not found.", parse_mode=ParseMode.MARKDOWN)


# ── Main ──────────────────────────────────────────────────────────────────────

def _seed_defaults():
    store = storage()
    for p in pm.DEFAULT_PROMPTS:
        if not store.get(p.name):
            store.add(p)


def main():
    _seed_defaults()

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", cmd_add)],
        states={
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_get_name)],
            ADD_TEMPLATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_get_template)],
            ADD_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_get_desc)],
            ADD_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_get_category)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("use", cmd_use))
    app.add_handler(CommandHandler("active", cmd_active))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("ask", cmd_ask))
    app.add_handler(CommandHandler("delete", cmd_delete))
    app.add_handler(add_conv)
    app.add_handler(CallbackQueryHandler(cb_use, pattern=r"^use:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_plain_message))

    logger.info("Starting Prompt Master bot…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
