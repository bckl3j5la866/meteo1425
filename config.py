# config.py
import os
import yaml
import logging
from pydantic import BaseModel, ValidationError
from typing import List, Optional

logger = logging.getLogger(__name__)

class SiteSchedule(BaseModel):
    weekdays: List[str]  # Расписание для рабочих дней (Пн-Сб)
    sunday: List[str]    # Расписание для воскресенья

class SiteConfig(BaseModel):
    name: str
    url: str
    type: str
    cookies: dict
    schedules: SiteSchedule  # Вложенная структура для расписаний

class TelegramConfig(BaseModel):
    chat_id: str
    bot_token: str  # ДОБАВЛЕНО ЭТО ПОЛЕ!

class Config(BaseModel):
    telegram: TelegramConfig  # Конфигурация для Telegram
    sites: List[SiteConfig]

class ConfigLoader:
    def __init__(self, config_path):
        self.config_path = config_path
        self._last_modified = 0
        self._cached_config = None
        
    def has_changed(self):
        """Проверяет, изменился ли файл конфига"""
        try:
            current_modified = os.path.getmtime(self.config_path)
            if current_modified > self._last_modified:
                return True
        except OSError:
            pass
        return False
    
    def load_if_changed(self):
        """Перезагружает конфиг только если он изменился"""
        if self.has_changed():
            logger.info("Обнаружены изменения в config.yaml, перезагружаем конфигурацию...")
            new_config = self.load()
            if new_config:
                return new_config
        return self._cached_config

    def load(self):
        try:
            with open(self.config_path, "r", encoding="utf-8") as file:
                config_data = yaml.safe_load(file)

                # Получаем токен бота из переменных окружения
                bot_token = os.getenv("BOT_TOKEN")
                if not bot_token:
                    logger.error("Не указан токен бота в переменных окружения BOT_TOKEN.")
                    return None

                # Добавляем токен в конфигурацию
                if "telegram" not in config_data:
                    config_data["telegram"] = {}
                config_data["telegram"]["bot_token"] = bot_token

                # Создание объекта конфигурации
                config = Config(**config_data)
                self._last_modified = os.path.getmtime(self.config_path)
                self._cached_config = config
                logger.info("Конфигурация загружена успешно.")
                return config
        except ValidationError as e:
            logger.error(f"Ошибка валидации: {e}")
            return None
        except Exception as e:
            logger.error(f"Ошибка загрузки: {e}")
            return None