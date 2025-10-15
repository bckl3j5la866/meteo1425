import asyncio
import logging
from aiogram import Bot
import os
from config import ConfigLoader

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация конфигурации
config_loader = ConfigLoader("config.yaml")
config = config_loader.load()

if config and hasattr(config, "telegram"):
    TELEGRAM_BOT_TOKEN = config.telegram.bot_token
    TELEGRAM_CHAT_ID = config.telegram.chat_id
else:
    logger.error("Конфигурация Telegram не загружена.")
    TELEGRAM_BOT_TOKEN = None
    TELEGRAM_CHAT_ID = None

# Инициализация бота
bot = Bot(token=TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None

async def send_telegram_notification(message: str):
    """
    Отправляет уведомление в Telegram канал.
    
    :param message: Текст сообщения для отправки
    """
    if not bot or not TELEGRAM_CHAT_ID:
        logger.error("Токен или ID чата Telegram не настроены.")
        return False

    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
        logger.info(f"✅ Сообщение отправлено в Telegram: {message[:100]}...")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка отправки в Telegram: {e}")
        return False

async def get_telegram_status() -> dict:
    """
    Возвращает статус Telegram бота.
    """
    return {
        "bot_configured": bot is not None and TELEGRAM_CHAT_ID is not None
    }

async def close_bot_session():
    """
    Закрывает сессию бота.
    """
    try:
        if bot and bot.session:
            await bot.session.close()
            logger.info("✅ Сессия бота закрыта.")
    except Exception as e:
        logger.error(f"❌ Ошибка при закрытии сессии: {e}")

# Пример использования
async def main():
    """Демонстрация работы"""
    status = await get_telegram_status()
    logger.info(f"Статус Telegram: {status}")
    
    # Тестовое сообщение
    await send_telegram_notification("🔵 Тестовое сообщение от бота погоды")
    
    await close_bot_session()

if __name__ == "__main__":
    asyncio.run(main())