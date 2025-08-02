import os
from dotenv import load_dotenv
import time
import requests
from bs4 import BeautifulSoup
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from datetime import datetime, timedelta
import asyncio
import json
import logging
import re
from urllib.parse import urljoin

load_dotenv()

# логируем ёпта
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# конфигурация и всякая ***** (по типу сайта пгу)
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    raise ValueError("Не найден TELEGRAM_BOT_TOKEN в переменных окружения")
CHECK_INTERVAL = 300  # делаем проверки каждые 5 мин в секундах
URL = "http://abitur.spsu.ru/"
STATE_FILE = "bot_state.json" 

# Пользовательский User-Agent
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/91.0.4472.124 Safari/537.36'
}

def load_state():
    """Загружает состояние бота из файла"""
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "last_news": "",
            "subscribed_users": {},
            "all_news": {}
        }

def save_state(state):
    """Сохраняет состояние бота в файл"""
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

def fetch_news():
    """Получает и парсит новости с сайта"""
    try:
        response = requests.get(URL, headers=HEADERS, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        news_items = []
        
        # Ищем контейнер карусели новостей
        carousel = soup.select_one('.jtcs119.owl-carousel')
        if not carousel:
            logger.warning("Карусель новостей не найдена")
            return None
            
        # Парсим каждую новость в карусели
        for slide in carousel.select('.slide'):
            try:
                # Заголовок новости
                title_tag = slide.select_one('.jt-title')
                if not title_tag:
                    continue
                title = title_tag.text.strip()
                
                # Ссылка на новость
                link = title_tag.get('href', '')
                if link:
                    link = urljoin(URL, link)
                else:
                    logger.warning(f"Ссылка не найдена для новости: {title}")
                    continue
                
                # Дата новости
                date_tag = slide.select_one('.jtc_introdate')
                date_str = date_tag.text.strip() if date_tag else ""
                
                # Преобразование даты в timestamp
                timestamp = time.time()
                if date_str:
                    try:
                        # Словарь для преобразования русских месяцев
                        months = {
                            'января': '01', 'февраля': '02', 'марта': '03',
                            'апреля': '04', 'мая': '05', 'июня': '06',
                            'июля': '07', 'августа': '08', 'сентября': '09',
                            'октября': '10', 'ноября': '11', 'декабря': '12'
                        }
                        
                        # Преобразование "22 июля 2025" -> "22.07.2025"
                        parts = date_str.split()
                        if len(parts) >= 3:
                            day = parts[0].zfill(2)
                            month_ru = parts[1]
                            year = parts[2]
                            
                            month = months.get(month_ru.lower(), '01')
                            date_obj = datetime.strptime(f"{day}.{month}.{year}", "%d.%m.%Y")
                            timestamp = date_obj.timestamp()
                    except Exception as e:
                        logger.error(f"Ошибка преобразования даты: {e}")
                
                news_items.append({
                    'title': title,
                    'link': link,
                    'date': date_str,
                    'timestamp': timestamp
                })
            except Exception as e:
                logger.error(f"Ошибка парсинга новости: {e}")
                
        return news_items
    except Exception as e:
        logger.error(f"Ошибка получения новостей: {e}")
        return None

def format_news_message(news_list):
    """Форматирует список новостей в сообщение"""
    if not news_list:
        return "Новостей нет"
    
    message = "📰 *Последние новости:*\n\n"
    for news in news_list:
        message += f"• [{news['title']}]({news['link']}) ({news['date']})\n"
    
    return message

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    try:
        user = update.effective_user
        state = load_state()
        
        # Добавляем пользователя в подписчики
        state['subscribed_users'][str(user.id)] = {
            'name': user.full_name,
            'last_notified': ""
        }
        save_state(state)
        
        await update.message.reply_text(
            f"Привет, {user.first_name}!\n"
            "Я буду присылать тебе уведомления о новых новостях с сайта приемной комиссии ПГУ.\n\n"
            "Используй команды:\n"
            "/news - показать последние новости\n"
            "/last24 - показать новости за последние 24 часа",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка в команде /start: {e}")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /news - показывает все доступные новости"""
    try:
        news_list = fetch_news()
        if not news_list:
            await update.message.reply_text("Не удалось получить новости. Попробуйте позже.")
            return
        
        message = format_news_message(news_list)
        await update.message.reply_text(
            message,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Ошибка в команде /news: {e}")
        await update.message.reply_text("⚠️ Произошла ошибка при получении новостей")

async def last24(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /last24 - новости за последние 24 часа"""
    try:
        news_list = fetch_news()
        if not news_list:
            await update.message.reply_text("Не удалось получить новости. Попробуйте позже.")
            return
        
        # Фильтрация новостей за последние 24 часа
        time_24h_ago = time.time() - 86400
        recent_news = [n for n in news_list if n['timestamp'] > time_24h_ago]
        
        if not recent_news:
            await update.message.reply_text("За последние 24 часа новостей нет.")
            return
        
        message = format_news_message(recent_news)
        await update.message.reply_text(
            message,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Ошибка в команде /last24: {e}")
        await update.message.reply_text("⚠️ Произошла ошибка при получении новостей")

async def check_news_updates(context: ContextTypes.DEFAULT_TYPE):
    """Периодическая проверка обновлений новостей"""
    try:
        state = load_state()
        last_news = state.get('last_news', '')
        news_list = fetch_news()
        
        if not news_list:
            return
        
        # Проверяем есть ли новые новости
        current_latest = news_list[0]['link']  # Используем ссылку для сравнения
        if current_latest == last_news:
            return
        
        # Сохраняем новую последнюю новость
        state['last_news'] = current_latest
        state['all_news'] = {n['link']: n for n in news_list}  # Используем ссылку как ключ
        save_state(state)
        
        # Находим новые новости (появившиеся с последней проверки)
        new_news = []
        for news in news_list:
            if news['link'] == last_news:
                break
            new_news.append(news)
        
        # Отправляем уведомления подписчикам
        for user_id in state['subscribed_users']:
            try:
                for news_item in reversed(new_news):  # Отправляем в хронологическом порядке
                    message = (
                        f"🔥 *Новая новость!* ({news_item['date']})\n\n"
                        f"[{news_item['title']}]({news_item['link']})"
                    )
                    
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode="Markdown",
                        disable_web_page_preview=False
                    )
                    await asyncio.sleep(0.5)  # Защита от флуда
            except Exception as e:
                logger.error(f"Ошибка отправки сообщения пользователю {user_id}: {e}")
    except Exception as e:
        logger.error(f"Ошибка в проверке новостей: {e}")

def main():
    """Запуск бота"""
    # Инициализация приложения
    application = Application.builder().token(TOKEN).build()
    
    # Регистрация обработчиков команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("last24", last24))
    
    # Запуск периодической проверки новостей
    job_queue = application.job_queue
    job_queue.run_repeating(
        check_news_updates, 
        interval=CHECK_INTERVAL, 
        first=10  # Запустить первую проверку через 10 сек после старта
    )
    
    # Запуск бота
    application.run_polling()

if __name__ == '__main__':
    main()