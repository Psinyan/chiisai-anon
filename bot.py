from __future__ import annotations

import logging
from typing import Optional

from telegram import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat, Message, Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackContext,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    MessageReactionHandler,
    filters,
)

from config import load_settings
from db import Database, OutboundTarget

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def is_admin(update: Update, admin_chat_id: int) -> bool:
    return bool(update.effective_chat and update.effective_chat.id == admin_chat_id)


async def post_init(app: Application) -> None:
    settings = app.bot_data["settings"]
    await app.bot.set_my_commands(
        commands=[
            BotCommand("start", "Start the bot"),
        ],
        scope=BotCommandScopeAllPrivateChats(),
    )
    await app.bot.set_my_commands(
        commands=[
            BotCommand("help_admin", "Show admin help"),
            BotCommand("stats", "Show bot stats"),
            BotCommand("ban", "Silently ban user by anon_id"),
            BotCommand("unban", "Unban user by anon_id"),
        ],
        scope=BotCommandScopeChat(chat_id=settings.admin_chat_id),
    )


async def start_user(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(
            "Давай давай нападай"
        )


async def help_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.bot_data["settings"]
    if not is_admin(update, settings.admin_chat_id):
        return
    if not update.message:
        return
    await update.message.reply_text(
        "Admin commands:\n"
        "/ban <anon_id>\n"
        "/unban <anon_id>\n"
        "/stats\n"
        "/help_admin\n\n"
        "Reply to a forwarded anonymous message with text/photo/sticker to answer."
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.bot_data["settings"]
    db: Database = context.bot_data["db"]
    if not is_admin(update, settings.admin_chat_id):
        return
    if not update.message:
        return
    s = db.stats()
    await update.message.reply_text(
        "Stats:\n"
        f"- Users: {s['users']}\n"
        f"- Banned: {s['banned']}\n"
        f"- Message links: {s['linked_messages']}\n"
        f"- Outbound messages: {s['outbound_messages']}"
    )


async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _toggle_ban(update, context, True)


async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _toggle_ban(update, context, False)


async def _toggle_ban(update: Update, context: ContextTypes.DEFAULT_TYPE, is_banned: bool) -> None:
    settings = context.bot_data["settings"]
    db: Database = context.bot_data["db"]
    if not is_admin(update, settings.admin_chat_id):
        return
    if not update.message:
        return
    if not context.args:
        cmd = "ban" if is_banned else "unban"
        await update.message.reply_text(f"Usage: /{cmd} <anon_id>")
        return

    anon_id = context.args[0].strip().upper()
    changed = db.set_ban(anon_id, is_banned=is_banned)
    if not changed:
        await update.message.reply_text(f"Unknown anon_id: {anon_id}")
        return
    await update.message.reply_text(
        f"{'Banned' if is_banned else 'Unbanned'}: {anon_id}"
    )


async def route_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    settings = context.bot_data["settings"]
    db: Database = context.bot_data["db"]

    if is_admin(update, settings.admin_chat_id):
        await handle_admin_reply(update.message, context, db)
    else:
        await handle_user_message(update.message, context, db, settings.admin_chat_id)


async def handle_user_message(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    admin_chat_id: int,
) -> None:
    sender = message.from_user
    if not sender:
        return

    user = db.get_or_create_user(sender.id)
    anon_id = user["anon_id"]

    # Silent ban: user can still send, but admin never receives it.
    if db.is_banned(sender.id):
        return

    admin_msg = await _forward_user_content_to_admin(message, context, admin_chat_id, anon_id)
    if admin_msg:
        db.save_message_link(
            user_id=sender.id,
            admin_message_id=admin_msg.message_id,
            user_message_id=message.message_id,
            direction="user_to_admin",
        )


async def _forward_user_content_to_admin(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    admin_chat_id: int,
    anon_id: str,
) -> Optional[Message]:
    prefix = f"[{anon_id}]"

    if message.text:
        return await context.bot.send_message(
            chat_id=admin_chat_id,
            text=f"{prefix}\n{message.text}",
        )

    if message.photo:
        photo = message.photo[-1].file_id
        caption = message.caption or ""
        return await context.bot.send_photo(
            chat_id=admin_chat_id,
            photo=photo,
            caption=f"{prefix}\n{caption}" if caption else prefix,
        )

    if message.sticker:
        notice = await context.bot.send_message(
            chat_id=admin_chat_id,
            text=f"{prefix} sent a sticker:",
        )
        await context.bot.send_sticker(
            chat_id=admin_chat_id,
            sticker=message.sticker.file_id,
        )
        return notice

    if message.animation:
        caption = message.caption or ""
        return await context.bot.send_animation(
            chat_id=admin_chat_id,
            animation=message.animation.file_id,
            caption=f"{prefix}\n{caption}" if caption else prefix,
        )

    if message.voice:
        notice = await context.bot.send_message(
            chat_id=admin_chat_id,
            text=f"{prefix}\nVoice message:",
        )
        await context.bot.send_voice(
            chat_id=admin_chat_id,
            voice=message.voice.file_id,
        )
        return notice

    return await context.bot.send_message(
        chat_id=admin_chat_id,
        text=f"{prefix} sent unsupported content type.",
    )


async def handle_admin_reply(message: Message, context: ContextTypes.DEFAULT_TYPE, db: Database) -> None:
    target = await _resolve_reply_target(message, db)
    if not target:
        return

    sent = await _send_admin_content_to_user(message, context, target.user_id)
    if not sent:
        return

    db.save_message_link(
        user_id=target.user_id,
        admin_message_id=message.message_id,
        user_message_id=sent.message_id,
        direction="admin_to_user",
    )
    db.save_outbound_message(
        user_id=target.user_id,
        anon_id=target.anon_id,
        chat_id=target.user_id,
        message_id=sent.message_id,
    )

    await message.reply_text(f"Sent to {target.anon_id}")


async def _resolve_reply_target(message: Message, db: Database) -> Optional[OutboundTarget]:
    if not message.reply_to_message:
        return None
    return db.get_target_by_admin_message_id(message.reply_to_message.message_id)


async def _send_admin_content_to_user(
    message: Message, context: ContextTypes.DEFAULT_TYPE, target_user_id: int
) -> Optional[Message]:
    if message.text and not message.text.startswith("/"):
        return await context.bot.send_message(chat_id=target_user_id, text=message.text)
    if message.photo:
        return await context.bot.send_photo(
            chat_id=target_user_id,
            photo=message.photo[-1].file_id,
            caption=message.caption or "",
        )
    if message.sticker:
        return await context.bot.send_sticker(
            chat_id=target_user_id,
            sticker=message.sticker.file_id,
        )
    if message.animation:
        return await context.bot.send_animation(
            chat_id=target_user_id,
            animation=message.animation.file_id,
            caption=message.caption or "",
        )
    if message.voice:
        return await context.bot.send_voice(
            chat_id=target_user_id,
            voice=message.voice.file_id,
        )
    return None


def _reactions_for_bot_api(new_reaction: tuple) -> list:
    """Telegram allows bots at most one reaction per message (non-premium bot behavior)."""
    rx = list(new_reaction)
    return rx[:1] if rx else []


async def _mirror_reaction(
    bot,
    *,
    chat_id: int,
    message_id: int,
    new_reaction: tuple,
) -> None:
    payload = _reactions_for_bot_api(new_reaction)
    try:
        await bot.set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=payload,
        )
    except TelegramError as e:
        logger.warning(
            "set_message_reaction failed chat_id=%s message_id=%s: %s",
            chat_id,
            message_id,
            e,
        )


async def on_reaction(update: Update, context: CallbackContext) -> None:
    settings = context.bot_data["settings"]
    db: Database = context.bot_data["db"]

    reaction = update.message_reaction
    if not reaction:
        return

    # Avoid echo when our own mirroring triggers another reaction update.
    if reaction.user and reaction.user.id == context.bot.id:
        return

    tracked = db.find_outbound_message(
        chat_id=reaction.chat.id,
        message_id=reaction.message_id,
    )
    if tracked:
        admin_msg_id = db.get_admin_message_for_outbound_dm(
            user_id=int(tracked["user_id"]),
            user_message_id=reaction.message_id,
        )
        if admin_msg_id is not None:
            await _mirror_reaction(
                context.bot,
                chat_id=settings.admin_chat_id,
                message_id=admin_msg_id,
                new_reaction=reaction.new_reaction,
            )
        return

    if reaction.chat.id != settings.admin_chat_id:
        return

    pair = db.get_user_dm_for_admin_forward(reaction.message_id)
    if not pair:
        return
    user_id, user_message_id = pair
    await _mirror_reaction(
        context.bot,
        chat_id=user_id,
        message_id=user_message_id,
        new_reaction=reaction.new_reaction,
    )


def main() -> None:
    settings = load_settings()
    db = Database(settings.db_path)

    app = Application.builder().token(settings.bot_token).post_init(post_init).build()
    app.bot_data["settings"] = settings
    app.bot_data["db"] = db

    app.add_handler(CommandHandler("start", start_user))
    app.add_handler(CommandHandler("help_admin", help_admin))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(MessageReactionHandler(on_reaction))
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE
            & (
                filters.TEXT
                | filters.PHOTO
                | filters.Sticker.ALL
                | filters.ANIMATION
                | filters.VOICE
            ),
            route_messages,
        )
    )

    logger.info("Bot started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
