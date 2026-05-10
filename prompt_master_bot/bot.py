"""Prompt Master Telegram Bot — main entry point."""
import logging
import os
import re
from typing import Optional

import anthropic
from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest
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
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

_storage: Optional[PromptStorage] = None
_claude: Optional[anthropic.AsyncAnthropic] = None

# ConversationHandler states
ADD_NAME, ADD_TEMPLATE, ADD_DESC, ADD_CATEGORY = range(4)
EDIT_TEMPLATE = 5

_NAME_RE = re.compile(r"^[\w-]{1,48}$")


def storage() -> PromptStorage:
    global _storage
    if _storage is None:
        _storage = PromptStorage(DATA_FILE)
    return _storage


def claude_client() -> anthropic.AsyncAnthropic:
    global _claude
    if _claude is None:
        _claude = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    return _claude


async def _safe_reply(msg, text: str, **kwargs) -> None:
    """Reply with Markdown; fall back to plain text on parse error."""
    try:
        await msg.reply_text(text, parse_mode=ParseMode.MARKDOWN, **kwargs)
    except BadRequest:
        kwargs.pop("parse_mode", None)
        await msg.reply_text(text, **kwargs)


async def _safe_edit(msg, text: str, **kwargs) -> None:
    """Edit with Markdown; fall back to plain text on parse error."""
    try:
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN, **kwargs)
    except BadRequest:
        kwargs.pop("parse_mode", None)
        try:
            await msg.edit_text(text, **kwargs)
        except BadRequest:
            pass


def _prompt_list_keyboard(prompts: list[Prompt], action: str = "use") -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(f"\U0001f4dd {p.name}", callback_data=f"{action}:{p.name}")]
        for p in prompts
    ]
    return InlineKeyboardMarkup(buttons)


# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _safe_reply(
        update.message,
        "*Prompt Master* \U0001f916\n\n"
        "Manage prompt templates and chat with Claude.\n\n"
        "Commands:\n"
        "• /list — browse all prompts\n"
        "• /add — create a new prompt\n"
        "• /edit `<name>` — edit an existing prompt's template\n"
        "• /use `<name>` — activate a prompt\n"
        "• /active — show your active prompt\n"
        "• /clear — deactivate prompt\n"
        "• /search `<query>` — search prompts by keyword\n"
        "• /category `<name>` — filter prompts by category\n"
        "• /ask `<text>` — ask Claude (uses active prompt)\n"
        "• /delete `<name>` — delete a prompt\n"
        "• /help — show this message",
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
    await _safe_reply(
        update.message,
        "\n\n".join(lines),
        reply_markup=_prompt_list_keyboard(prompts, action="use"),
    )


# ── /search <query> ───────────────────────────────────────────────────────────

async def cmd_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /search <keyword>")
        return
    query = " ".join(ctx.args)
    results = storage().search(query)
    if not results:
        await _safe_reply(update.message, f"No prompts found for `{query}`.")
        return
    lines = [f"• *{p.name}* [{p.category}]\n  _{p.description}_" for p in results]
    await _safe_reply(
        update.message,
        f"Search results for `{query}`:\n\n" + "\n\n".join(lines),
        reply_markup=_prompt_list_keyboard(results, action="use"),
    )


# ── /category [name] ──────────────────────────────────────────────────────────

async def cmd_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        cats = storage().categories()
        if not cats:
            await update.message.reply_text("No categories yet.")
            return
        await _safe_reply(
            update.message,
            "Available categories:\n" + "\n".join(f"• `{c}`" for c in sorted(cats)),
        )
        return
    cat = ctx.args[0].lower()
    results = storage().list_by_category(cat)
    if not results:
        await _safe_reply(update.message, f"No prompts in category `{cat}`.")
        return
    lines = [f"• *{p.name}*\n  _{p.description}_" for p in results]
    await _safe_reply(
        update.message,
        f"Category *{cat}*:\n\n" + "\n\n".join(lines),
        reply_markup=_prompt_list_keyboard(results, action="use"),
    )


# ── /use <name> ───────────────────────────────────────────────────────────────

async def cmd_use(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        prompts = storage().list_all()
        if not prompts:
            await update.message.reply_text("No prompts available. Use /add first.")
            return
        await update.message.reply_text(
            "Choose a prompt to activate:",
            reply_markup=_prompt_list_keyboard(prompts, action="use"),
        )
        return
    await _activate_prompt(update, ctx, ctx.args[0])


async def _activate_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE, name: str):
    prompt = storage().get(name)
    msg = update.message or update.callback_query.message
    if not prompt:
        await _safe_reply(msg, f"Prompt `{name}` not found.")
        return
    storage().set_active(update.effective_user.id, name)
    vars_ = pm.extract_variables(prompt.template)
    var_note = (
        f"\n\nThis template has variables: `{', '.join(vars_)}`\n"
        "When you /ask, prefix your message with `var=value` pairs, e.g.:\n"
        "`language=Python\nreview this code...`"
        if vars_ else ""
    )
    await _safe_reply(
        msg,
        f"✅ Active prompt set to *{name}*\n_{prompt.description}_{var_note}",
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
    await _safe_reply(
        update.message,
        f"*Active:* {prompt.name}\n_{prompt.description}_\n\n"
        f"```\n{prompt.template}\n```"
        + (f"\n\nVariables: `{', '.join(vars_)}`" if vars_ else ""),
    )


async def cmd_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    storage().clear_active(update.effective_user.id)
    await update.message.reply_text("Active prompt cleared.")


# ── /ask <text> ───────────────────────────────────────────────────────────────

async def cmd_ask(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /ask <your question>")
        return
    await _handle_ask(update, ctx, " ".join(ctx.args))


async def handle_plain_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Route plain messages to Claude only when an active prompt is set."""
    if not storage().get_active(update.effective_user.id):
        return
    await _handle_ask(update, ctx, update.message.text)


async def _handle_ask(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user_text: str):
    prompt = storage().get_active(update.effective_user.id)

    variables: dict[str, str] = {}
    message_body = user_text

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
        system = "You are a helpful assistant."
        messages = [{"role": "user", "content": message_body}]

    thinking_msg = await update.message.reply_text("⏳ Thinking…")

    try:
        chunks: list[str] = []
        async for chunk in pm.ask_claude(claude_client(), system, messages, model=CLAUDE_MODEL):
            chunks.append(chunk)

        full_response = "".join(chunks)
        prefix = f"*[{prompt.name}]* " if prompt else ""
        await _safe_edit(thinking_msg, prefix + full_response)
    except anthropic.APIStatusError as e:
        logger.exception("Claude API error: %s", e.status_code)
        await thinking_msg.edit_text("Claude API error. Please try again later.")
    except Exception:
        logger.exception("Unexpected error in _handle_ask")
        await thinking_msg.edit_text("An unexpected error occurred. Please try again.")


# ── /add (ConversationHandler) ────────────────────────────────────────────────

async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.clear()
    await _safe_reply(
        update.message,
        "Let's create a new prompt.\n\nStep 1/4 — Enter a *name* (letters, digits, hyphens only):",
    )
    return ADD_NAME


async def add_get_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip().replace(" ", "-")
    if not _NAME_RE.match(name):
        await _safe_reply(
            update.message,
            "Name must be 1–48 characters: letters, digits, or hyphens only. Try again:",
        )
        return ADD_NAME
    if storage().get(name):
        await _safe_reply(
            update.message,
            f"A prompt named `{name}` already exists. Choose a different name:",
        )
        return ADD_NAME
    ctx.user_data["name"] = name
    await _safe_reply(
        update.message,
        f"Name: *{name}*\n\nStep 2/4 — Enter the *system prompt template*.\n"
        "Use `{variable}` placeholders for dynamic values.",
    )
    return ADD_TEMPLATE


async def add_get_template(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["template"] = update.message.text.strip()
    vars_ = pm.extract_variables(ctx.user_data["template"])
    var_note = f"\nDetected variables: `{', '.join(vars_)}`" if vars_ else ""
    await _safe_reply(
        update.message,
        f"Template saved.{var_note}\n\nStep 3/4 — Enter a short *description* (or send `-` to skip):",
    )
    return ADD_DESC


async def add_get_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    ctx.user_data["description"] = "" if text == "-" else text
    await _safe_reply(
        update.message,
        "Step 4/4 — Enter a *category* (e.g. coding, writing, language, education) or `-` for general:",
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
    await _safe_reply(
        update.message,
        f"✅ Prompt *{prompt.name}* saved!\nUse /use `{prompt.name}` to activate it.",
    )
    ctx.user_data.clear()
    return ConversationHandler.END


async def add_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.clear()
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


# ── /edit <name> (ConversationHandler) ───────────────────────────────────────

async def cmd_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not ctx.args:
        await update.message.reply_text("Usage: /edit <name>")
        return ConversationHandler.END
    name = ctx.args[0]
    prompt = storage().get(name)
    if not prompt:
        await _safe_reply(update.message, f"Prompt `{name}` not found.")
        return ConversationHandler.END
    ctx.user_data["edit_name"] = name
    await _safe_reply(
        update.message,
        f"Editing *{name}*. Send the new template (or /cancel to abort):\n\n"
        f"Current template:\n```\n{prompt.template}\n```",
    )
    return EDIT_TEMPLATE


async def edit_get_template(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    name = ctx.user_data.pop("edit_name", None)
    if not name:
        return ConversationHandler.END
    prompt = storage().get(name)
    if not prompt:
        await _safe_reply(update.message, f"Prompt `{name}` no longer exists.")
        return ConversationHandler.END
    prompt.template = update.message.text.strip()
    vars_ = pm.extract_variables(prompt.template)
    storage().update(prompt)
    var_note = f"\nVariables: `{', '.join(vars_)}`" if vars_ else ""
    await _safe_reply(update.message, f"✅ Prompt *{name}* updated.{var_note}")
    return ConversationHandler.END


# ── /delete <name> ────────────────────────────────────────────────────────────

async def cmd_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /delete <name>")
        return
    name = ctx.args[0]
    if storage().delete(name):
        await _safe_reply(update.message, f"\U0001f5d1 Prompt `{name}` deleted.")
    else:
        await _safe_reply(update.message, f"Prompt `{name}` not found.")


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

    edit_conv = ConversationHandler(
        entry_points=[CommandHandler("edit", cmd_edit)],
        states={
            EDIT_TEMPLATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_get_template)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("category", cmd_category))
    app.add_handler(CommandHandler("use", cmd_use))
    app.add_handler(CommandHandler("active", cmd_active))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("ask", cmd_ask))
    app.add_handler(CommandHandler("delete", cmd_delete))
    app.add_handler(add_conv)
    app.add_handler(edit_conv)
    app.add_handler(CallbackQueryHandler(cb_use, pattern=r"^use:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_plain_message))

    logger.info("Starting Prompt Master bot…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
