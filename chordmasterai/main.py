import asyncio
import os
import random
import logging
import sqlite3
import numpy as np
import librosa
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, CallbackQuery, LabeledPrice,
    PreCheckoutQuery, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton,
    ContentType
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from moviepy.video.io.VideoFileClip import VideoFileClip

# --- НАСТРОЙКИ ---
TOKEN = ""
bot = Bot(token=TOKEN)
dp = Dispatcher()
router = Router()

# Тарифы подписки
SUBSCRIPTIONS = {
    "month_1": {"title": "1 месяц PRO", "price": 250, "days": 30},
    "month_3": {"title": "3 месяца PRO", "price": 650, "days": 90},
    "month_6": {"title": "6 месяцев PRO", "price": 1350, "days": 180},
    "year_1": {"title": "1 год PRO", "price": 2850, "days": 365},
}

CHORD_TEMPLATES = {
    'C Major': [1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0],
    'C Minor': [1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0],
    'D Major': [0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 0, 0],
    'D Minor': [0, 0, 1, 0, 0, 1, 0, 0, 0, 1, 0, 0],
    'E Major': [0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1],
    'E Minor': [0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 1],
    'F Major': [1, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0],
    'G Major': [0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 1],
    'A Major': [0, 1, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0],
    'A Minor': [1, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0],
}

NOTES_FILES = {
    "C": "CQACAgIAAxkBAAMgaeaDqrmlEpXkprUf76Oh4Uin6DcAAtebAALWZjlL1VdyNTdD7aU7BA",
    "D": "CQACAgIAAxkBAAMkaeaEr7IBW_1Nv_3WJGyC9lHCk68AAuCbAALWZjlL_qr7Qn341P07BA",
    "E": "CQACAgIAAxkBAAMnaeaE4N5xWen0F72StMiWBb7NaaIAAuKbAALWZjlLqgO6UDJaHww7BA",
    "F": "CQACAgIAAxkBAAMqaeaFCWA7BNrRc-Nnywspewa0AUkAAuSbAALWZjlLfvbsCjmSdwk7BA",
    "G": "CQACAgIAAxkBAAMtaeaFPrwDFbKawMMdHzrJa910r0wAAuebAALWZjlLVaJry8mALPw7BA",
    "A": "CQACAgIAAxkBAAMtaeaFPrwDFbKawMMdHzrJa910r0wAAuebAALWZjlLVaJry8mALPw7BA",
    "B": "CQACAgIAAxkBAAMzaeaFp-YGA17guTb-7Mh7cLYjORoAAvKbAALWZjlLl4umE_-3cCc7BA",
}


# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('chordmaster.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS subscriptions 
                      (user_id INTEGER PRIMARY KEY, expire_date TEXT)''')
    conn.commit()
    conn.close()


def get_subscription_status(user_id):
    conn = sqlite3.connect('chordmaster.db')
    cursor = conn.cursor()
    cursor.execute("SELECT expire_date FROM subscriptions WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    if result:
        expire_date = datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S')
        if expire_date > datetime.now(): return expire_date
    return None


def add_subscription(user_id, days):
    expire_date = datetime.now() + timedelta(days=days)
    expire_date_str = expire_date.strftime('%Y-%m-%d %H:%M:%S')
    conn = sqlite3.connect('chordmaster.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO subscriptions VALUES (?, ?)", (user_id, expire_date_str))
    conn.commit()
    conn.close()


# --- КЛАВИАТУРА ---
main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="🎹 Тренировка слуха")],
    [KeyboardButton(text="⭐️ Купить PRO")]
], resize_keyboard=True)


# --- ЛОГИКА АНАЛИЗА ---
def identify_chord(file_path):
    y, sr = librosa.load(file_path, duration=10)  # Анализируем только первые 10 сек для скорости
    chroma = librosa.feature.chroma_stft(y=y, sr=sr)
    mean_chroma = np.mean(chroma, axis=1)
    best_chord, max_similarity = "Неизвестно", -1
    for chord_name, template in CHORD_TEMPLATES.items():
        similarity = np.dot(mean_chroma, template)
        if similarity > max_similarity:
            max_similarity, best_chord = similarity, chord_name
    return best_chord


# --- ОБРАБОТЧИКИ ---
@router.message(F.content_type.in_({'voice', 'video_note', 'video', 'audio'}))
async def handle_media(message: Message):
    if message.voice:
        file_id = message.voice.file_id
    elif message.audio:
        file_id = message.audio.file_id
    elif message.video_note:
        file_id = message.video_note.file_id
    else:
        file_id = message.video.file_id

    status = await message.answer("🎼 Анализирую вашу игру...")

    file = await bot.get_file(file_id)
    temp_input = f"temp_{file_id}"
    temp_wav = f"{temp_input}.wav"

    await bot.download_file(file.file_path, temp_input)

    try:
        if message.video or message.video_note:
            clip = VideoFileClip(temp_input)
            clip.audio.write_audiofile(temp_wav, logger=None)
            clip.close()
        else:
            os.rename(temp_input, temp_wav)

        chord = identify_chord(temp_wav)
        await status.edit_text(f"🎹 Я слышу здесь: **{chord}**", parse_mode="Markdown")
    except Exception as e:
        await status.edit_text(f"❌ Ошибка: {e}")
    finally:
        for f in [temp_input, temp_wav]:
            if os.path.exists(f): os.remove(f)


@router.message(F.text == "🎹 Тренировка слуха")
async def start_training(message: Message):
    if not get_subscription_status(message.from_user.id):
        await message.answer("🔒 Режим доступен только PRO-пользователям.")
        return
    await send_next_note(message)


async def send_next_note(message_obj):
    correct_note = random.choice(list(NOTES_FILES.keys()))
    builder = InlineKeyboardBuilder()
    for note in NOTES_FILES.keys():
        builder.add(InlineKeyboardButton(text=note, callback_data=f"tr_{note}_{correct_note}"))
    builder.adjust(3)

    text = "Слушай внимательно... Что это за аккорд?"
    if isinstance(message_obj, Message):
        await message_obj.answer_voice(voice=NOTES_FILES[correct_note], caption=text, reply_markup=builder.as_markup())
    else:  # Если это CallbackQuery
        await message_obj.message.answer_voice(voice=NOTES_FILES[correct_note], caption=text,
                                               reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("tr_"))
async def check_answer(callback: CallbackQuery):
    if not get_subscription_status(callback.from_user.id):
        await callback.answer("PRO истек!", show_alert=True)
        return

    _, user_ans, correct_ans = callback.data.split("_")
    if user_ans == correct_ans:
        await callback.message.edit_caption(caption=f"✅ Верно! Это {correct_ans}")
        await send_next_note(callback)
    else:
        await callback.answer(f"❌ Это был {correct_ans}", show_alert=True)
        await send_next_note(callback)


@router.message(F.text == "⭐️ Купить PRO")
async def buy_pro_status(message: Message):
    expiry = get_subscription_status(message.from_user.id)
    if expiry:
        await message.answer(f"✅ PRO активен до: `{expiry.strftime('%d.%m.%Y %H:%M')}`", parse_mode="Markdown")
    else:
        builder = InlineKeyboardBuilder()
        for key, sub in SUBSCRIPTIONS.items():
            builder.add(InlineKeyboardButton(text=f"{sub['title']} — {sub['price']} ⭐️", callback_data=f"buy_{key}"))
        builder.adjust(1)
        await message.answer("Выбери тариф:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("buy_"))
async def send_sub_invoice(callback: CallbackQuery):
    sub_key = callback.data.replace("buy_", "")
    sub = SUBSCRIPTIONS.get(sub_key)
    if not sub: return

    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title=sub['title'],
        description=f"Доступ на {sub['days']} дней.",
        payload=f"pro_{sub_key}",
        currency="XTR",
        prices=[LabeledPrice(label="PRO", amount=sub['price'])]
    )
    await callback.answer()


@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(query.id, ok=True)


@router.message(F.successful_payment)
async def process_success_payment(message: Message):
    sub_key = message.successful_payment.invoice_payload.replace("pro_", "")
    days = SUBSCRIPTIONS[sub_key]["days"]
    add_subscription(message.from_user.id, days)
    await message.answer(f"🚀 PRO активирован на {days} дней!", reply_markup=main_kb)


@router.message(F.text == "/start")
async def cmd_start(message: Message):
    await message.answer("Привет! Я ChordMaster AI. Отправь мне видео или ГС с игрой!", reply_markup=main_kb)


async def main():
    init_db()
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
