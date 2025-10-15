import aiohttp
import asyncio
import logging
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
import random
import sys
import os
import re
import datetime
import pytz
import ssl
import certifi

# Импортируем только метео парсер
from parsing.meteo import get_weather, get_current_temperature, determine_activated_days

logger = logging.getLogger(__name__)

# Устанавливаем временную зону Якутска (UTC+9)
yakutsk_tz = pytz.timezone('Asia/Yakutsk')

# Статический список User-Agent
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
]

def get_random_user_agent():
    """Возвращает случайный User-Agent из статического списка."""
    return random.choice(USER_AGENTS)

class SiteParser:
    def __init__(self, url, site_type, cookies=None, schedules=None):
        self.url = url
        self.site_type = site_type
        self.cookies = cookies or {}
        self.schedules = schedules
        self.last_parsed_time = None

    async def is_site_available(self):
        """Проверяет доступность сайта."""
        try:
            headers = {
                "User-Agent": get_random_user_agent(),
                "Referer": self.url,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
                "Connection": "keep-alive",
            }

            ssl_context = ssl.create_default_context(cafile=certifi.where())

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.url, 
                    headers=headers, 
                    cookies=self.cookies, 
                    timeout=30, 
                    ssl=ssl_context
                ) as response:
                    response.raise_for_status()
                    return True
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка HTTP при запросе к {self.url}: {e}")
            return False
        except Exception as e:
            logger.error(f"Сайт {self.url} недоступен: {e}")
            return False

    async def fetch_and_parse(self):
        """Загружает и парсит данные с сайта."""
        logger.debug(f"Запрос к сайту: {self.url}")
        if not await self.is_site_available():
            logger.error(f"Сайт {self.url} недоступен. Пропускаем парсинг.")
            return []

        headers = {
            "User-Agent": get_random_user_agent(),
            "Referer": self.url,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
            "Connection": "keep-alive",
        }

        ssl_context = ssl.create_default_context(cafile=certifi.where())

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        self.url, 
                        headers=headers, 
                        cookies=self.cookies, 
                        timeout=60, 
                        ssl=ssl_context
                    ) as response:
                        response.raise_for_status()
                        html = await response.text()
                        logger.debug(f"Успешный ответ от сайта: {self.url}")
                        await self._simulate_human_behavior()
                        
                        # Всегда используем парсинг погоды
                        return self._parse_weather(html)
            except Exception as e:
                logger.error(f"Ошибка при запросе к {self.url} (попытка {attempt + 1}): {e}")
                await asyncio.sleep(5)
        return []

    def _parse_weather(self, html):
        """Парсит данные о погоде."""
        logger.debug(f"Парсинг HTML для сайта: {self.url}")
        if not html:
            logger.warning(f"HTML пуст для сайта: {self.url}")
            return []

        try:
            weather_data = get_weather()
            if weather_data:
                return [weather_data]
            else:
                logger.warning("Не удалось получить данные о погоде.")
                return []
        except Exception as e:
            logger.exception(f"Ошибка при парсинге сайта {self.url}: {e}")
            return []

    async def _simulate_human_behavior(self):
        """Имитирует человеческое поведение, добавляя случайную задержку."""
        delay = random.uniform(3, 5)
        await asyncio.sleep(delay)