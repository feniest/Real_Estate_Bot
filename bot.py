import os
import asyncio
import configparser
import psycopg2
from psycopg2.extras import RealDictCursor
from ftplib import FTP
from io import BytesIO
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import BufferedInputFile, InputMediaPhoto

# Загрузка конфигурации из общего файла config.ini
config = configparser.ConfigParser()
config.read("config.ini", encoding="utf-8")

TOKEN = config.get("Telegram", "token")
DEFAULT_PHONE = config.get("Telegram", "default_phone", fallback="+998900000000")
MAX_VIDEO_SIZE = int(config.get("Limits", "max_video_size_mb", fallback=50)) * 1024 * 1024

bot = Bot(token=TOKEN)
dp = Dispatcher()

def get_db_connection():
    """Подключение к общей базе данных PostgreSQL"""
    return psycopg2.connect(
        host=config.get('Database', 'host', fallback='127.0.0.1'),
        port=config.getint('Database', 'port', fallback=5432),
        database=config.get('Database', 'dbname', fallback='estate_db'),
        user=config.get('Database', 'user', fallback='postgres'),
        password=config.get('Database', 'password', fallback=''),
        cursor_factory=RealDictCursor
    )

def get_ftp_connection():
    """Подключение к FTP-серверу для скачивания медиа"""
    ftp = FTP()
    ftp.connect(config.get('Server', 'host'), config.getint('Server', 'port', fallback=21))
    ftp.login(config.get('Server', 'username'), config.get('Server', 'password'))
    return ftp

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🏢 Аренда недвижимости", callback_data="cat_Rent"),
        types.InlineKeyboardButton(text="🏠 Продажа недвижимости", callback_data="cat_Sales")
    )
    builder.row(
        types.InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help"),
        types.InlineKeyboardButton(text="📞 Звонок оператору", callback_data="call_operator")
    )
    await message.answer(
        f"<b>{message.from_user.first_name}</b>, добро пожаловать в систему поиска недвижимости!",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("cat_"))
async def choose_property_type(callback: types.CallbackQuery):
    await callback.answer()
    category = callback.data.split("_")[1] # Rent или Sales
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="Квартиры", callback_data=f"type_{category}_Apartments"),
        types.InlineKeyboardButton(text="Дома и участки", callback_data=f"type_{category}_Houses")
    )
    builder.row(types.InlineKeyboardButton(text="🔙 НАЗАД", callback_data="back_to_main"))
    
    title = "АРЕНДА НЕДВИЖИМОСТИ" if category == "Rent" else "ПРОДАЖА НЕДВИЖИМОСТИ"
    await callback.message.edit_text(f"<b>{title}</b>", parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("type_"))
async def choose_rooms(callback: types.CallbackQuery):
    await callback.answer()
    _, category, prop_type = callback.data.split("_")
    builder = InlineKeyboardBuilder()
    for i in range(1, 6):
        rooms_label = f"{i}-комн." if i < 5 else "5-комн. +"
        rooms_val = str(i) if i < 5 else "5"
        builder.add(types.InlineKeyboardButton(text=rooms_label, callback_data=f"list_{category}_{prop_type}_{rooms_val}"))
    builder.adjust(3, 2)
    builder.row(types.InlineKeyboardButton(text="🔙 ОБРАТНО", callback_data=f"cat_{category}"))
    
    await callback.message.edit_text("Выберите количество комнат:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("list_"))
async def show_ads_list(callback: types.CallbackQuery):
    await callback.answer()
    _, category, prop_type, rooms = callback.data.split("_")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT ad_number, district, price FROM ads WHERE category=%s AND property_type=%s AND rooms=%s AND is_active=1",
        (category, prop_type, rooms)
    )
    ads = cursor.fetchall()
    cursor.close()
    conn.close()
    
    if not ads:
        await callback.message.answer("В данной категории пока нет активных объявлений.")
        return

    builder = InlineKeyboardBuilder()
    for ad in ads:
        builder.row(types.InlineKeyboardButton(
            text=f"№ {ad['ad_number']} | Район: {ad['district']} | Цена: {ad['price']}",
            callback_data=f"view_{category}_{prop_type}_{rooms}_{ad['ad_number']}"
        ))
    builder.row(types.InlineKeyboardButton(text="🔙 ОБРАТНО", callback_data=f"type_{category}_{prop_type}"))
    
    await callback.message.edit_text("Список доступных объявлений:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("view_"))
async def view_ad_details(callback: types.CallbackQuery):
    await callback.answer("Загружаем данные...")
    
    _, category, prop_type, rooms, ad_number = callback.data.split("_")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ads WHERE ad_number=%s AND is_active=1", (ad_number,))
    ad = cursor.fetchone()
    cursor.close()
    conn.close()

    if not ad:
        await callback.message.answer("Объявление не найдено или было удалено.")
        return

    # Формируем текст объявления заранее
    area_or_floor = f"📐 Площадь: {ad['area']} кв.м.\n" if ad['area'] else f"🏢 Этаж: {ad['floor']}/{ad['floors_total']}\n"
    text = (
        f"🏠 <b>Объявление №{ad['ad_number']}</b>\n"
        f"📍 Район: {ad['district']}\n"
        f"🧭 Ориентир: {ad['landmark']}\n"
        f"🚪 Комнат: {rooms}\n"
        f"{area_or_floor}"
        f"💰 Цена: {ad['price']}\n"
        f"📞 Телефон: {DEFAULT_PHONE}"
    )

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔙 К списку", callback_data=f"list_{category}_{prop_type}_{rooms}"))

    # Скачиваем медиафайлы с FTP в память
    photo_media = []
    videos_to_send = []
    
    ftp = None
    try:
        ftp = get_ftp_connection()
        remote_path = f"{category}/{prop_type}/{rooms}-room/{ad_number}"
        
        try:
            ftp.cwd(f"/{remote_path}")
            file_list = ftp.nlst()
        except Exception:
            file_list = []

        for file_name in file_list:
            ext = file_name.lower().split('.')[-1]
            
            if ext in ['jpg', 'jpeg', 'png', 'bmp']:
                img_io = BytesIO()
                ftp.retrbinary(f"RETR {file_name}", img_io.write)
                img_io.seek(0)
                file_bytes = img_io.read()
                
                # Если это самая первая фотка, сразу передаем ей текст и HTML-разметку
                if not photo_media:
                    photo_media.append(InputMediaPhoto(
                        media=BufferedInputFile(file_bytes, filename=file_name),
                        caption=text,
                        parse_mode="HTML"
                    ))
                else:
                    photo_media.append(InputMediaPhoto(
                        media=BufferedInputFile(file_bytes, filename=file_name)
                    ))
                
            elif ext in ['mp4', 'avi', 'mkv', 'mov']:
                vid_io = BytesIO()
                ftp.retrbinary(f"RETR {file_name}", vid_io.write)
                vid_io.seek(0)
                if vid_io.getbuffer().nbytes <= MAX_VIDEO_SIZE:
                    videos_to_send.append((vid_io.read(), file_name))
    except Exception as e:
        print(f"Ошибка получения медиа с FTP: {e}")
    finally:
        if ftp:
            try:
                ftp.quit()
            except:
                pass

    # Отправка контента пользователю
    if photo_media:
        # Отправляем альбом (первая фото идет с текстом)
        for i in range(0, len(photo_media), 10):
            chunk = photo_media[i:i+10]
            await bot.send_media_group(callback.message.chat.id, chunk)
        
        # Кнопки управления выводим отдельным сообщением строго под альбомом
        await callback.message.answer("Управление объявлением:", reply_markup=builder.as_markup())
    else:
        # Если картинок нет вообще, шлем просто текст с кнопками
        await callback.message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())

    # Отправляем видео, если они есть
    for vid_bytes, v_name in videos_to_send:
        await bot.send_chat_action(callback.message.chat.id, "upload_video")
        await callback.message.answer_video(BufferedInputFile(vid_bytes, filename=v_name), caption=f"Видео №{ad_number}")

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    await callback.answer()
    await cmd_start(callback.message)
    await callback.message.delete()

async def main():
    print("Telegram-бот запущен и подключен к облачной базе и FTP...")
    while True:
        try:
            # Увеличиваем таймаут опроса (polling timeout) до 30 секунд
            await dp.start_polling(bot, handle_signals=False, polling_timeout=30)
        except Exception as e:
            print(f"Ошибка соединения с Telegram: {e}. Переподключение через 5 секунд...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен пользователем.")