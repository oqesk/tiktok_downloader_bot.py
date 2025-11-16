import telebot
import sqlite3
import time 
import requests
import re
import os
from urllib.parse import urlparse

# --- КОНФИГУРАЦИЯ БОТА ---
# Токен бота
TOKEN = '8455959886:AAGqbIM-BF32QqPhS4u-R-N602oik7nZFxE' 
# ID владельца (для доступа к /admin)
OWNER_ID = 8034775567 
DB_NAME = 'bot_data.db'

bot = telebot.TeleBot(TOKEN)
TIKTOK_URL_PATTERN = re.compile(r'^(https?://)?(www\.|vm\.|vt\.)?(tiktok\.com|vt\.tiktok\.com)/[a-zA-Z0-9\-\.\/\?\_=&%]+')

# --- ФУНКЦИИ БАЗЫ ДАННЫХ (SQLite) ---

def init_db():
    """Инициализирует базу данных и создает таблицу пользователей."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            join_date TEXT,
            tiktok_downloads INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def db_execute(query, params=()):
    """Универсальная функция для выполнения запросов и закрытия соединения."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(query, params)
    conn.commit()
    return cursor

def add_user(user_id):
    """Добавляет нового пользователя в базу данных."""
    try:
        db_execute("INSERT INTO users (id, join_date) VALUES (?, datetime('now'))", (user_id,))
    except sqlite3.IntegrityError:
        pass

def increment_downloads(user_id):
    """Увеличивает счетчик загрузок для статистики."""
    db_execute("UPDATE users SET tiktok_downloads = tiktok_downloads + 1 WHERE id = ?", (user_id,))

def get_total_users():
    """Получает общее количество пользователей."""
    cursor = db_execute("SELECT COUNT(id) FROM users")
    count = cursor.fetchone()[0]
    return count

def get_total_downloads():
    """Получает общее количество загрузок."""
    cursor = db_execute("SELECT SUM(tiktok_downloads) FROM users")
    total = cursor.fetchone()[0]
    return total if total else 0

def get_all_user_ids(limit=None):
    """Возвращает список ID пользователей для рассылки."""
    if limit is None:
        query = "SELECT id FROM users"
        params = ()
    else:
        query = "SELECT id FROM users LIMIT ?"
        params = (limit,)
        
    cursor = db_execute(query, params)
    ids = [row[0] for row in cursor.fetchall()]
    return ids

# --- УТИЛИТЫ И API ДЛЯ TIKTOK ---

def get_full_url(url):
    """Преобразует короткую ссылку (vt.tiktok.com) в полную."""
    try:
        if 'vt.tiktok.com' in url or 'vm.tiktok.com' in url:
            response = requests.get(url, allow_redirects=True, timeout=10)
            return response.url
        return url
    except Exception:
        return url

def get_tiktok_video_no_watermark(url):
    """Получение ссылки на контент без водяного знака с помощью tikwm.com."""
    full_url = get_full_url(url)
    api_endpoint = "https://www.tikwm.com/api/" 
    
    payload = {'url': full_url, 'hd': 1}
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        response = requests.post(api_endpoint, data=payload, headers=headers, timeout=20)
        response.raise_for_status() 
        data = response.json()
        audio_url = None
        
        if data.get('code') == 0 and 'data' in data:
            result = data['data']
            
            if result.get('music'):
                audio_url = result['music']
            
            # 1. Фотопост
            if result.get('images'):
                 return "photo", result['images'], audio_url
            
            # 2. Видео
            if result.get('hdplay'):
                 return "video", result['hdplay'], audio_url
            elif result.get('play'):
                 return "video", result['play'], audio_url
                 
            return "error", "API вернул данные, но не нашел ссылок.", None
            
        else:
            return "error", f"API-сервис отклонил запрос: {data.get('msg', 'Неизвестная ошибка')}", None

    except requests.exceptions.RequestException as e:
        return "error", f"Ошибка при подключении к API: {e}", None
    except Exception as e:
        return "error", f"Критическая ошибка: {e}", None


# --- ОБРАБОТЧИКИ КОМАНД И СООБЩЕНИЙ ---

@bot.message_handler(commands=['start', 'help'])
def handle_start(message):
    add_user(message.from_user.id)
    bot.send_message(message.chat.id, 
                     "👋 Привет! Я скачиваю контент из TikTok без водяного знака.\n"
                     "Просто отправь мне ссылку.")

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    """Админ-панель: доступ только для OWNER_ID."""
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "Доступ запрещен.")
        return

    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    btn_stats = telebot.types.KeyboardButton('/stats')
    btn_mailing = telebot.types.KeyboardButton('/mailing')
    markup.add(btn_stats, btn_mailing)
    bot.send_message(message.chat.id, 
                     "🔐 **Админ-панель**\n\nВыберите действие:",
                     reply_markup=markup,
                     parse_mode='Markdown')

@bot.message_handler(commands=['stats'])
def show_stats(message):
    """Статистика: доступ только для OWNER_ID."""
    if message.from_user.id != OWNER_ID: return
    
    total_users = get_total_users()
    total_downloads = get_total_downloads()
    
    stats_message = (
        "📊 **Статистика бота**\n"
        f"**Всего пользователей:** `{total_users}`\n"
        f"**Всего загрузок TikTok:** `{total_downloads}`"
    )
    bot.send_message(message.chat.id, stats_message, parse_mode='Markdown')

@bot.message_handler(commands=['mailing'])
def start_mailing(message):
    """Начало рассылки: запрашивает текст."""
    if message.from_user.id != OWNER_ID: return

    msg = bot.send_message(message.chat.id, 
                           "📝 **Начало рассылки**\n\n"
                           "Пришлите текст сообщения.")
    bot.register_next_step_handler(msg, ask_for_mailing_limit)

@bot.message_handler(func=lambda message: TIKTOK_URL_PATTERN.search(message.text.strip()))
def handle_tiktok_link(message):
    """Обработка ссылки на TikTok."""
    add_user(message.chat.id) 
    increment_downloads(message.from_user.id)
    link = message.text.strip()

    try:
        processing_msg = bot.send_message(message.chat.id, "🤖 Обрабатываю ссылку...")
        
        content_type, content_data, audio_url = get_tiktok_video_no_watermark(link)
        
        bot.delete_message(message.chat.id, processing_msg.message_id)
        
        # --- ФОРМИРОВАНИЕ КНОПКИ ТРЕКА ---
        keyboard = None
        if audio_url:
            keyboard = telebot.types.InlineKeyboardMarkup()
            keyboard.add(telebot.types.InlineKeyboardButton(text="🎵 Трек", url=audio_url))

        if content_type == "video" and content_data:
            bot.send_chat_action(message.chat.id, 'upload_video')
            video_headers = {'User-Agent': 'Mozilla/5.0'} 
            video_file = requests.get(content_data, headers=video_headers, stream=True, timeout=60)
            
            bot.send_video(message.chat.id, 
                           video_file.content, 
                           caption="✅  Видео скачано",
                           reply_markup=keyboard,
                           supports_streaming=True)
                           
        elif content_type == "photo" and isinstance(content_data, list) and content_data:
            # Отправка медиагруппы (до 10 фото)
            media = []
            photo_headers = {'User-Agent': 'Mozilla/5.0'} 
            
            for i, url in enumerate(content_data):
                if i < 10: 
                    photo_bytes = requests.get(url, headers=photo_headers, timeout=10).content
                    photo_media = telebot.types.InputMediaPhoto(photo_bytes, caption="✅ Фотографии скачаны" if i == 0 else "")
                    media.append(photo_media)

            if media:
                bot.send_media_group(message.chat.id, media)
                if keyboard:
                    bot.send_message(message.chat.id, "🎵 Аудио-трек:", reply_markup=keyboard, disable_notification=True)
            else:
                 bot.reply_to(message, "Не удалось найти фотографии в посте.")
            
        elif content_type == "error":
             bot.reply_to(message, f"❌ Ошибка: {content_data}")
             
        else:
            bot.reply_to(message, "❌ Не удалось получить контент. Попробуйте другую ссылку.")

    except Exception as e:
        print(f"Критическая ошибка при обработке: {e}")
        bot.reply_to(message, "Критическая ошибка при обработке запроса.")

# --- ФУНКЦИИ РАССЫЛКИ (Многошаговый процесс) ---

def ask_for_mailing_limit(message):
    """Запрашивает у администратора лимит получателей."""
    if message.text.startswith('/') or message.from_user.id != OWNER_ID:
        bot.send_message(message.chat.id, "Действие отменено.")
        return

    mailing_message = message.text
    
    msg = bot.send_message(message.chat.id, 
                           "🔢 Укажите лимит.\n"
                           "Введите число (напр., `100`), или **'ВСЕ'**.",
                           parse_mode='Markdown')
                           
    bot.register_next_step_handler(msg, execute_mass_mailing, mailing_message=mailing_message)

def execute_mass_mailing(message, mailing_message):
    """Выполняет рассылку."""
    if message.from_user.id != OWNER_ID: return
    
    limit_text = message.text.strip().upper()
    limit = None
    
    if limit_text == 'ВСЕ':
        limit = None
    else:
        try:
            limit = int(limit_text)
            if limit <= 0: raise ValueError
        except ValueError:
            msg = bot.send_message(message.chat.id, "❌ Некорректный лимит. Введите число или 'ВСЕ'.")
            bot.register_next_step_handler(msg, execute_mass_mailing, mailing_message=mailing_message)
            return

    user_ids = get_all_user_ids(limit)
    
    if not user_ids:
        bot.send_message(message.chat.id, "🤷‍♂️ В базе данных нет пользователей.")
        return

    sent_count = 0
    blocked_count = 0
    
    bot.send_message(message.chat.id, f"🚀 Начинаю рассылку. Целевое количество: **{len(user_ids)}**", parse_mode='Markdown')

    for user_id in user_ids:
        try:
            bot.send_message(user_id, mailing_message)
            sent_count += 1
            time.sleep(0.1) # Задержка для защиты от бана
        except telebot.apihelper.Api400Exception as e:
            if 'bot was blocked by the user' in str(e) or 'chat not found' in str(e):
                blocked_count += 1
            else:
                print(f"Ошибка при отправке пользователю {user_id}: {e}")
        except Exception as e:
             print(f"Непредвиденная ошибка для {user_id}: {e}")
             
    final_report = (
        "✅ **Рассылка завершена!**\n\n"
        f"**Отправлено сообщений:** `{sent_count}`\n"
        f"**Заблокировано:** `{blocked_count}`"
    )
    bot.send_message(message.chat.id, final_report, parse_mode='Markdown')


# --- УНИВЕРСАЛЬНЫЙ ОБРАБОТЧИК ---

@bot.message_handler(func=lambda message: True)
def default_response(message):
    add_user(message.chat.id)
    bot.reply_to(message, "Пожалуйста, отправьте корректную ссылку на TikTok.")


# --- ЗАПУСК БОТА ---

if __name__ == '__main__':
    print("[DIX]: Инициализация базы данных и запуск...")
    init_db()
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        print(f"Критическая ошибка в работе бота: {e}")
