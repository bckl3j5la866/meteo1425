import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Optional
import pytz

from parsing.site_parser import SiteParser
from parsing.meteo import get_weather, get_current_temperature, determine_activated_days
from telegram_notifier import send_telegram_notification

logger = logging.getLogger(__name__)

# Устанавливаем временную зону Якутска (UTC+9)
YAKUTSK_TZ = pytz.timezone('Asia/Yakutsk')

def format_task_count(count: int) -> str:
    """
    Форматирует количество задач с учетом правил русского языка.
    """
    if count == 1:
        return f"{count} задача"
    elif 2 <= count <= 4:
        return f"{count} задачи"
    else:
        return f"{count} задач"

class Scheduler:
    def __init__(self, config):
        self.tasks = []
        self.parsers = []  # Список парсеров для обновления расписания
        self.config = config  # Сохраняем конфигурацию
        self.site_names = self._load_site_names()  # Загружаем названия сайтов
        self.last_check_time = None  # Время последней проверки

    def _load_site_names(self) -> dict:
        """
        Загружает названия сайтов из конфигурации.
        Возвращает словарь, где ключ — URL, а значение — название сайта.
        """
        site_names = {}
        if hasattr(self.config, "sites") and isinstance(self.config.sites, list):
            for site in self.config.sites:
                if hasattr(site, "url") and hasattr(site, "name"):
                    site_names[site.url] = site.name
        return site_names

    async def update_config(self, new_config):
        """Обновляет конфигурацию и перезагружает задачи"""
        logger.info("Обновление конфигурации планировщика...")
        
        # Останавливаем все текущие задачи
        for task in self.tasks:
            task.cancel()
        self.tasks.clear()
        self.parsers.clear()
        
        # Обновляем конфиг
        self.config = new_config
        self.site_names = self._load_site_names()
        
        # Пересоздаем парсеры и задачи
        for site in self.config.sites:
            parser = SiteParser(
                url=site.url,
                site_type=site.type,
                cookies=site.cookies,
                schedules=site.schedules
            )
            self.parsers.append(parser)
            await self.add_job(parser)
        
        logger.info("Конфигурация планировщика успешно обновлена")

    async def add_job(self, parser: SiteParser):
        # Получаем название сайта из конфигурации или используем URL, если название не найдено
        site_name = self.site_names.get(parser.url, parser.url)
        logger.info(f"Добавление задач для сайта: {site_name}")

        if not parser.schedules:
            logger.warning(f"Для сайта {site_name} нет расписания.")
            return

        # Получаем текущее время в Якутске (UTC+9)
        now_yakutsk = datetime.now(YAKUTSK_TZ)
        today = now_yakutsk.weekday()
        
        schedule = parser.schedules.sunday if today == 6 else parser.schedules.weekdays
        logger.debug(f"Расписание для сайта {site_name}: {schedule}")

        tasks_added = 0
        for time_str in schedule:
            task = asyncio.create_task(self._run_parser_task(parser, time_str))
            task.time_str = time_str
            task.parser = parser
            self.tasks.append(task)
            tasks_added += 1

        if tasks_added > 0:
            formatted_tasks = format_task_count(tasks_added)
            logger.info(f"Добавлено {formatted_tasks} для сайта {site_name}.")
            self.parsers.append(parser)  # Сохраняем парсер для обновления расписания

        # Логируем время следующей проверки
        await self.log_next_check_time()

    async def _run_parser_task(self, parser: SiteParser, time_str: str):
        site_name = self.site_names.get(parser.url, parser.url)
        logger.debug(f"Задача для сайта {site_name} (время: {time_str}) запущена.")

        while True:
            delay = self._get_delay_until(time_str)
            await asyncio.sleep(delay)
            logger.info(f"Запуск парсера для сайта: {site_name}")

            try:
                weather_data = await parser.fetch_and_parse()
                if weather_data:
                    logger.info(f"Получены данные о погоде для сайта: {site_name}.")
                    await self._send_weather_message(weather_data)
                else:
                    logger.warning(f"Данные о погоде не найдены для сайта: {site_name}.")
            except Exception as e:
                logger.error(f"Ошибка при выполнении задачи для сайта {site_name}: {e}")

            # Добавляем задержку между задачами
            await asyncio.sleep(3)  # Задержка 3 секунды

    def _get_delay_until(self, time_str: str) -> int:
        """Вычисляет задержку до указанного времени в Якутске (UTC+9)"""
        now_yakutsk = datetime.now(YAKUTSK_TZ)
        
        # Парсим целевое время (в Якутске)
        target_time_naive = datetime.strptime(time_str, "%H:%M").time()
        
        # Создаем datetime с сегодняшней датой и целевым временем в Якутске
        target_time_yakutsk = YAKUTSK_TZ.localize(
            datetime.combine(now_yakutsk.date(), target_time_naive)
        )
        
        # Если целевое время уже прошло сегодня, планируем на завтра
        if target_time_yakutsk < now_yakutsk:
            target_time_yakutsk += timedelta(days=1)
            
        # Вычисляем разницу в секундах
        delay_seconds = (target_time_yakutsk - now_yakutsk).total_seconds()
        
        logger.debug(f"Текущее время Якутск: {now_yakutsk.strftime('%H:%M')}, "
                    f"Целевое время: {time_str}, "
                    f"Задержка: {delay_seconds:.0f} сек")
        
        return max(0, delay_seconds)

    def _get_next_check_time(self) -> Optional[datetime]:
        next_check = None
        try:
            for task in self.tasks:
                if not task.done() and hasattr(task, "time_str") and hasattr(task, "parser"):
                    delay = self._get_delay_until(task.time_str)
                    # Время задачи в Якутске
                    task_time_yakutsk = datetime.now(YAKUTSK_TZ) + timedelta(seconds=delay)

                    if not next_check or task_time_yakutsk < next_check:
                        next_check = task_time_yakutsk
            logger.debug(f"Ближайшая задача: {next_check}")
            return next_check
        except Exception as e:
            logger.error(f"Ошибка при расчете времени проверки: {e}")
            return None

    async def log_next_check_time(self) -> Optional[str]:
        """
        Логирует время следующей проверки и возвращает строку с временем.
        """
        next_check = self._get_next_check_time()
        if next_check:
            next_check_time = next_check.strftime("%H:%M")
            current_time_yakutsk = datetime.now(YAKUTSK_TZ).strftime("%H:%M")
            logger.info(f"Текущее время Якутск: {current_time_yakutsk}. Следующая проверка в {next_check_time}.")
            return f"Следующая проверка в {next_check_time} (Якутск)."
        else:
            logger.info("Нет запланированных задач для проверки.")
            return None

    async def _send_weather_message(self, weather_data_list: List[dict]):
        if not isinstance(weather_data_list, list):
            logger.error("Некорректный формат данных. Ожидается список.")
            return

        # Для погоды всегда отправляем первое (и единственное) сообщение
        if len(weather_data_list) == 0:
            logger.warning("Нет данных о погоде для отправки.")
            return

        weather_data = weather_data_list[0]
        
        if not isinstance(weather_data, dict):
            logger.error("Данные о погоде не являются словарем.")
            return

        # Формируем сообщение о погоде
        message = self._format_weather_message(weather_data)

        # Отправляем сообщение в Telegram
        await send_telegram_notification(message)
        logger.info(f"Данные о погоде отправлены в Telegram канал.")

        # Логируем время следующей проверки
        next_check_message = await self.log_next_check_time()
        if next_check_message:
            logger.info(f"Сообщение о следующей проверке: {next_check_message}")

    def _format_weather_message(self, weather_data: dict) -> str:
        """Форматирует сообщение о погоде с дополнительными данными."""
        observation_time = datetime.strptime(
            weather_data["observation_time"], "%d.%m.%Y %H:%M"
        ).strftime("%H:%M")
        
        # Получаем текущую дату в Якутске
        current_date_yakutsk = datetime.now(YAKUTSK_TZ).strftime("%d.%m.%Y")
        
        # Формируем основное сообщение с дополнительными данными
        weather_message = (
            f"🌤️ Погода в с.{weather_data['location']} на {current_date_yakutsk}\n"
            f"ГИДРОМЕТЦЕНТР РОССИИ\n"
            f"⏰ Время наблюдения: {observation_time}\n"
            f"🌡️ Температура воздуха: {weather_data['temperature']}\n"
            f"💧 Влажность: {weather_data.get('humidity', 'N/A')}\n"
            f"🎯 Атмосферное давление: {weather_data.get('pressure', 'N/A')}\n"
            f"🌧️ Осадки: {weather_data.get('precipitation', 'N/A')}\n"
            f"☁️ Облачность: {weather_data.get('cloudiness', 'N/A')}\n"
            f"💨 Ветер: {weather_data.get('wind_direction', 'N/A')}, {weather_data.get('wind_speed', 'N/A')}\n"
            f"📊 Погодные явления: {weather_data.get('weather_condition', 'N/A')}\n"
            f"🔗 Подробнее: https://meteoinfo.ru/pogoda/russia/republic-saha-yakutia/ytyk-kel"
        )

        # Проверяем, нужно ли добавлять информацию об актированных днях
        # Только при температуре <= -45°C и только в период 6:00-7:30 в рабочие дни по Якутску
        now_yakutsk = datetime.now(YAKUTSK_TZ)
        today = now_yakutsk.weekday()
        current_time_yakutsk = now_yakutsk.time()
        
        if today != 6 and (current_time_yakutsk.hour == 6 or (current_time_yakutsk.hour == 7 and current_time_yakutsk.minute <= 30)):
            try:
                # Преобразуем температуру в число
                temperature_str = weather_data['temperature'].replace("°C", "").strip()
                temperature = float(temperature_str)  # Преобразуем в float
            except ValueError:
                logger.error(f"Ошибка при преобразовании температуры в число: {weather_data['temperature']}")
                temperature = None

            # Добавляем информацию об актированных днях только при температуре <= -45°C
            if temperature is not None and temperature <= -45:
                weather_message += "\n\n"
                if temperature <= -45:
                    weather_message += (
                        f"❄️ По данным наблюдения на {observation_time}:\n"
                        f"Актированные дни для 1-4 классов."
                    )
                elif temperature <= -48:
                    weather_message += (
                        f"❄️ По данным наблюдения на {observation_time}:\n"
                        f"Актированные дни для 1-7 классов."
                    )
                elif temperature <= -50:
                    weather_message += (
                        f"❄️ По данным наблюдения на {observation_time}:\n"
                        f"Актированные дни для 1-9 классов."
                    )
                elif temperature <= -52:
                    weather_message += (
                        f"❄️ По данным наблюдения на {observation_time}:\n"
                        f"Актированные дни для 1-11 классов."
                    )

        return weather_message