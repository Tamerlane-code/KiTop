"""
Varaq — kitob ijarasi va savdosi uchun Telegram bot.

ISHGA TUSHIRISH:
1. pip install -r requirements.txt
2. .env faylga BOT_TOKEN= qiymatini qo'ying (BotFather'dan olinadi)
3. python bot.py

Ro'yxatdan o'tish alohida SMS-kod talab qilmaydi — Telegram foydalanuvchining
ismini va ID'sini avtomatik beradi, biz faqat nickname va hududni so'raymiz.
"""

import os
import logging
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

import database as db

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

REGIONS = ["Toshkent", "Samarqand", "Buxoro", "Andijon", "Farg'ona", "Namangan"]

# --- Conversation bosqichlari (har bir raqam bir "qadam"ni bildiradi) ---
REG_NICKNAME, REG_REGION = range(2)
ADD_TYPE, ADD_TITLE, ADD_AUTHOR, ADD_REGION, ADD_CONDITION, ADD_PRICE, ADD_MARKET_PRICE, ADD_NOTE = range(2, 10)
SEARCH_QUERY = 10


def region_keyboard(prefix: str) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(r, callback_data=f"{prefix}:{r}")] for r in REGIONS]
    return InlineKeyboardMarkup(buttons)


# ============================================================
# RO'YXATDAN O'TISH
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if user:
        await update.message.reply_text(
            f"Xush kelibsiz, {user['nickname']}!\n\n"
            "/qidir — kitob qidirish\n"
            "/qoshish — kitob e'loni joylash\n"
            "/elonlarim — mening e'lonlarim"
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "Assalomu alaykum! Varaq botiga xush kelibsiz.\n\n"
        "Bu yerda siz kitobingizni ijaraga berishingiz, sotishingiz "
        "yoki boshqalarning kitobini topishingiz mumkin.\n\n"
        "Avval tanishib olaylik — sizni qanday chaqirsak bo'ladi? (taxallus/ism)"
    )
    return REG_NICKNAME


async def reg_nickname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nickname = update.message.text.strip()
    if len(nickname) < 2 or len(nickname) > 30:
        await update.message.reply_text("Ism 2-30 belgi orasida bo'lishi kerak. Qaytadan kiriting:")
        return REG_NICKNAME

    context.user_data["nickname"] = nickname
    await update.message.reply_text(
        "Rahmat! Endi qaysi hududda yashaysiz? Bu sizga yaqin takliflarni topishga yordam beradi.",
        reply_markup=region_keyboard("reg_region"),
    )
    return REG_REGION


async def reg_region(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    region = query.data.split(":")[1]

    nickname = context.user_data.get("nickname", query.from_user.first_name)
    db.upsert_user(query.from_user.id, nickname, region)

    await query.edit_message_text(
        f"Tabriklaymiz, {nickname}! Ro'yxatdan muvaffaqiyatli o'tdingiz.\n"
        f"Hududingiz: {region}\n\n"
        "Endi quyidagilardan foydalanishingiz mumkin:\n"
        "/qidir — kitob qidirish\n"
        "/qoshish — kitob e'loni joylash\n"
        "/elonlarim — mening e'lonlarim"
    )
    return ConversationHandler.END


def require_registration(func):
    """Foydalanuvchi ro'yxatdan o'tmagan bo'lsa, oldin /start qilishni so'raydi."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = db.get_user(update.effective_user.id)
        if not user:
            await update.message.reply_text("Iltimos, avval /start buyrug'i bilan ro'yxatdan o'ting.")
            return ConversationHandler.END
        context.user_data["_current_user"] = user
        return await func(update, context)
    return wrapper


# ============================================================
# KITOB QIDIRISH
# ============================================================

@require_registration
async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Qaysi kitobni qidirmoqchisiz? Nomi yoki muallifini yozing.\n"
        "(Barcha kitoblarni ko'rish uchun \"hammasi\" deb yozing)"
    )
    return SEARCH_QUERY


async def search_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_text = update.message.text.strip()
    user = context.user_data["_current_user"]

    search_term = "" if query_text.lower() == "hammasi" else query_text
    results = db.search_books(query=search_term, user_region=user["region"], sort_asc=True)

    if not results:
        await update.message.reply_text(
            "Hech narsa topilmadi. Boshqa kalit so'z bilan urinib ko'ring yoki "
            "/qoshish orqali o'zingiz birinchi bo'lib e'lon joylang."
        )
        return ConversationHandler.END

    await update.message.reply_text(f"{len(results)} ta natija topildi:")

    for book in results[:10]:
        is_local = book["region"] == user["region"]
        type_label = "Ijara" if book["listing_type"] == "rent" else "Sotuv"
        price_unit = "so'm/hafta" if book["listing_type"] == "rent" else "so'm"

        text = (
            f"<b>{book['title']}</b>\n"
            f"{book['author']}\n"
            f"{type_label}{' · mahalliy' if is_local else ''} · {book['region']}\n"
            f"<b>{book['price']:,} {price_unit}</b>".replace(",", " ")
        )

        if book["listing_type"] == "rent" and book["market_price"]:
            if book["price"] / book["market_price"] > 0.55:
                text += f"\nSotib olish narxi: {book['market_price']:,} so'm".replace(",", " ")

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Egasi bilan bog'lanish", callback_data=f"contact:{book['id']}")
        ]])
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)

    return ConversationHandler.END


async def contact_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    book_id = int(query.data.split(":")[1])
    book = db.get_book(book_id)

    if not book:
        await query.message.reply_text("Bu e'lon topilmadi, ehtimol o'chirilgan.")
        return

    await query.message.reply_text(
        f"\"{book['title']}\" kitobi egasi: {book['owner_nickname']}\n\n"
        "Demo rejimida real bog'lanish ishlamaydi. "
        "Haqiqiy versiyada bu yerda egasiga to'g'ridan-to'g'ri xabar yuborish "
        "yoki yetkazib berish usulini tanlash imkoniyati bo'ladi."
    )


# ============================================================
# KITOB QO'SHISH
# ============================================================

@require_registration
async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Ijaraga beraman", callback_data="add_type:rent"),
        InlineKeyboardButton("Sotaman", callback_data="add_type:sale"),
    ]])
    await update.message.reply_text("Kitobingizni qanday joylashtirmoqchisiz?", reply_markup=keyboard)
    return ADD_TYPE


async def add_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["new_book"] = {"listing_type": query.data.split(":")[1]}
    await query.edit_message_text("Kitobning nomi nima?")
    return ADD_TITLE


async def add_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_book"]["title"] = update.message.text.strip()
    await update.message.reply_text("Muallifi kim?")
    return ADD_AUTHOR


async def add_author(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_book"]["author"] = update.message.text.strip()
    await update.message.reply_text("Qaysi hududdasiz?", reply_markup=region_keyboard("add_region"))
    return ADD_REGION


async def add_region(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["new_book"]["region"] = query.data.split(":")[1]

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Yangidek", callback_data="cond:Yangidek")],
        [InlineKeyboardButton("Yaxshi", callback_data="cond:Yaxshi")],
        [InlineKeyboardButton("O'rtacha (izlar bor)", callback_data="cond:O'rtacha")],
    ])
    await query.edit_message_text("Kitobning holati qanday?", reply_markup=keyboard)
    return ADD_CONDITION


async def add_condition(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["new_book"]["condition"] = query.data.split(":")[1]

    listing_type = context.user_data["new_book"]["listing_type"]
    label = "Ijara narxini" if listing_type == "rent" else "Sotuv narxini"
    await query.edit_message_text(f"{label} so'mda kiriting (faqat raqam, masalan: 15000):")
    return ADD_PRICE


async def add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text.strip().replace(" ", ""))
        if price <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Iltimos, faqat musbat raqam kiriting (masalan: 15000):")
        return ADD_PRICE

    context.user_data["new_book"]["price"] = price

    if context.user_data["new_book"]["listing_type"] == "rent":
        await update.message.reply_text(
            "Kitobning taxminiy tan narxini ham kiriting (so'mda).\n"
            "Bu — ijara narxi tan narxga yaqinlashganda foydalanuvchiga "
            "\"sotib olish\" taklifini ko'rsatish uchun kerak."
        )
        return ADD_MARKET_PRICE
    else:
        context.user_data["new_book"]["market_price"] = None
        await update.message.reply_text("Qisqacha izoh qo'shmoqchimisiz? (yo'q bo'lsa \"yo'q\" deb yozing)")
        return ADD_NOTE


async def add_market_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        market_price = int(update.message.text.strip().replace(" ", ""))
        if market_price <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Iltimos, faqat musbat raqam kiriting:")
        return ADD_MARKET_PRICE

    context.user_data["new_book"]["market_price"] = market_price
    await update.message.reply_text("Qisqacha izoh qo'shmoqchimisiz? (yo'q bo'lsa \"yo'q\" deb yozing)")
    return ADD_NOTE


async def add_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    note_text = update.message.text.strip()
    note = "" if note_text.lower() == "yo'q" else note_text

    book_data = context.user_data["new_book"]
    user_id = update.effective_user.id

    book_id = db.add_book(
        owner_id=user_id,
        title=book_data["title"],
        author=book_data["author"],
        region=book_data["region"],
        listing_type=book_data["listing_type"],
        price=book_data["price"],
        market_price=book_data.get("market_price"),
        condition=book_data["condition"],
        note=note,
    )

    type_label = "ijaraga" if book_data["listing_type"] == "rent" else "sotuvga"
    await update.message.reply_text(
        f"E'lon muvaffaqiyatli joylandi (#{book_id})!\n\n"
        f"\"{book_data['title']}\" kitobi endi {type_label} qo'yildi va "
        "qidiruvda boshqa foydalanuvchilarga ko'rinadi.\n\n"
        "/elonlarim orqali barcha e'lonlaringizni ko'rishingiz mumkin."
    )
    context.user_data.pop("new_book", None)
    return ConversationHandler.END


# ============================================================
# MENING E'LONLARIM
# ============================================================

@require_registration
async def my_listings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    books = db.get_user_books(update.effective_user.id)
    if not books:
        await update.message.reply_text("Sizda hali e'lon yo'q. /qoshish orqali birinchisini joylang.")
        return

    for book in books:
        type_label = "Ijara" if book["listing_type"] == "rent" else "Sotuv"
        price_unit = "so'm/hafta" if book["listing_type"] == "rent" else "so'm"
        text = (
            f"<b>{book['title']}</b> ({type_label})\n"
            f"{book['price']:,} {price_unit}".replace(",", " ")
        )
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("E'lonni o'chirish", callback_data=f"remove:{book['id']}")
        ]])
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


async def remove_listing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    book_id = int(query.data.split(":")[1])

    success = db.deactivate_book(book_id, query.from_user.id)
    if success:
        await query.edit_message_text("E'lon o'chirildi.")
    else:
        await query.edit_message_text("Bu e'lonni o'chira olmadingiz (ehtimol sizga tegishli emas).")


# ============================================================
# UMUMIY
# ============================================================

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Bekor qilindi.")
    return ConversationHandler.END


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN topilmadi. .env faylga BOT_TOKEN=... qiymatini qo'shing."
        )

    db.init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    registration_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            REG_NICKNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_nickname)],
            REG_REGION: [CallbackQueryHandler(reg_region, pattern="^reg_region:")],
        },
        fallbacks=[CommandHandler("bekor", cancel)],
    )

    search_handler = ConversationHandler(
        entry_points=[CommandHandler("qidir", search_start)],
        states={
            SEARCH_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_results)],
        },
        fallbacks=[CommandHandler("bekor", cancel)],
    )

    add_handler = ConversationHandler(
        entry_points=[CommandHandler("qoshish", add_start)],
        states={
            ADD_TYPE: [CallbackQueryHandler(add_type, pattern="^add_type:")],
            ADD_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_title)],
            ADD_AUTHOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_author)],
            ADD_REGION: [CallbackQueryHandler(add_region, pattern="^add_region:")],
            ADD_CONDITION: [CallbackQueryHandler(add_condition, pattern="^cond:")],
            ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_price)],
            ADD_MARKET_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_market_price)],
            ADD_NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_note)],
        },
        fallbacks=[CommandHandler("bekor", cancel)],
    )

    app.add_handler(registration_handler)
    app.add_handler(search_handler)
    app.add_handler(add_handler)
    app.add_handler(CommandHandler("elonlarim", my_listings))
    app.add_handler(CallbackQueryHandler(contact_owner, pattern="^contact:"))
    app.add_handler(CallbackQueryHandler(remove_listing, pattern="^remove:"))

    logger.info("Bot ishga tushdi...")
    app.run_polling()


if __name__ == "__main__":
    main()
