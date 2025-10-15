import requests
from bs4 import BeautifulSoup
import logging
from datetime import datetime
import time
import random
import asyncio

logger = logging.getLogger(__name__)

MONTH_TRANSLATION = {
    'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
    'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
    'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
}

def parse_observation_time(time_str):
    try:
        time_str = time_str.split('(')[0].strip().replace('\xa0', ' ')
        day, month_rus, time_part = time_str.split()
        month_rus = month_rus.rstrip(',')
        month = MONTH_TRANSLATION[month_rus.lower()]
        year = datetime.now().year
        return datetime.strptime(f"{day} {month} {year} {time_part}", "%d %m %Y %H:%M")
    except Exception as e:
        logger.error(f"Ошибка парсинга даты: {str(e)}")
        return None

class ExponentialBackoff:
    """
    Класс для реализации экспоненциальной задержки с добавкой случайности (jitter)
    """
    
    def __init__(self, base_delay: float = 1.0, max_delay: float = 60.0, max_retries: int = 5):
        """
        :param base_delay: Базовая задержка в секундах
        :param max_delay: Максимальная задержка в секундах
        :param max_retries: Максимальное количество попыток
        """
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.max_retries = max_retries
        
    def get_delay(self, attempt: int) -> float:
        """
        Вычисляет задержку для текущей попытки с экспоненциальным ростом и jitter
        
        :param attempt: Номер текущей попытки (начинается с 0)
        :return: Задержка в секундах
        """
        if attempt >= self.max_retries:
            return self.max_delay
            
        # Экспоненциальный рост: base_delay * 2^attempt
        exponential_delay = self.base_delay * (2 ** attempt)
        
        # Ограничение максимальной задержки
        delay = min(exponential_delay, self.max_delay)
        
        # Добавляем случайность (jitter) - ±20% от вычисленной задержки
        jitter = random.uniform(-0.2, 0.2) * delay
        final_delay = max(0.1, delay + jitter)  # Минимум 0.1 секунды
        
        logger.debug(f"Попытка {attempt + 1}: задержка {final_delay:.2f} сек (base: {delay:.2f}, jitter: {jitter:.2f})")
        return final_delay

class WeatherFetcher:
    """
    Класс для получения погодных данных с улучшенной retry-логикой
    """
    
    def __init__(self):
        self.backoff = ExponentialBackoff(base_delay=2.0, max_delay=30.0, max_retries=4)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        }
    
    def fetch_with_retry(self):
        """
        Получает данные о погоде с экспоненциальной задержкой между попытками
        """
        url = "https://meteoinfo.ru/pogoda/russia/republic-saha-yakutia/ytyk-kel"
        
        for attempt in range(self.backoff.max_retries):
            try:
                logger.info(f"Попытка {attempt + 1}/{self.backoff.max_retries} получения данных о погоде")
                
                # Увеличиваем timeout с каждой попыткой
                timeout = 10 + (attempt * 5)  # 10, 15, 20, 25 секунд
                response = requests.get(url, headers=self.headers, timeout=timeout)
                response.encoding = 'utf-8'
                
                if response.status_code != 200:
                    raise requests.exceptions.HTTPError(f"HTTP {response.status_code}")
                
                return self.parse_weather_response(response)
                
            except (requests.exceptions.RequestException, AttributeError) as e:
                error_type = type(e).__name__
                logger.warning(f"Попытка {attempt + 1} не удалась ({error_type}): {e}")
                
                # Если это последняя попытка - пробрасываем исключение
                if attempt == self.backoff.max_retries - 1:
                    logger.error(f"Все {self.backoff.max_retries} попыток получения погоды провалились")
                    raise
                
                # Вычисляем и применяем задержку
                delay = self.backoff.get_delay(attempt)
                logger.info(f"Повторная попытка через {delay:.1f} секунд...")
                time.sleep(delay)
                
            except Exception as e:
                logger.error(f"Неожиданная ошибка при получении погоды: {e}")
                if attempt == self.backoff.max_retries - 1:
                    raise
                delay = self.backoff.get_delay(attempt)
                time.sleep(delay)
        
        return None
    
    def parse_weather_response(self, response):
        """
        Парсит HTML ответ с данными о погоде
        """
        soup = BeautifulSoup(response.content, 'html.parser', from_encoding='utf-8')
        
        weather_table = soup.find('div', id='div_4')
        if not weather_table:
            logger.error("Таблица с погодой не найдена.")
            return None

        weather_table = weather_table.find('table')
        if not weather_table:
            logger.error("Таблица с погодой не найдена.")
            return None
        
        time_cell = weather_table.find('td', {'colspan': '2'})
        if not time_cell:
            logger.error("Время наблюдения не найдено.")
            return None

        observation_time = parse_observation_time(time_cell.text)
        if not observation_time:
            return None
        
        data = {}
        for row in weather_table.find_all('tr')[1:]:
            cells = row.find_all('td')
            if len(cells) == 2:
                param = cells[0].text.strip().split(',')[0].strip()
                value = cells[1].text.strip()
                data[param] = value
        
        return {
            "location": "Ытык-Кюель",
            "observation_time": observation_time.strftime("%d.%m.%Y %H:%M"),
            "temperature": data.get('Температура воздуха', 'N/A'),
            "min_temperature": data.get('Минимальная температура', 'N/A'),
            "humidity": data.get('Относительная влажность', 'N/A'),
            "wind_direction": data.get('Направление ветра', 'N/A'),
            "wind_speed": data.get('Средняя скорость ветра', 'N/A')
        }

# Глобальный экземпляр для обратной совместимости
_weather_fetcher = WeatherFetcher()

def get_weather():
    """
    Основная функция для получения данных о погоде с улучшенной retry-логикой
    """
    try:
        return _weather_fetcher.fetch_with_retry()
    except Exception as e:
        logger.error(f"Критическая ошибка при получении погоды: {e}")
        return None

async def get_weather_async():
    """
    Асинхронная версия функции получения погоды
    """
    # Запускаем в отдельном потоке чтобы не блокировать event loop
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, get_weather)
    except Exception as e:
        logger.error(f"Ошибка в асинхронном получении погоды: {e}")
        return None

def get_current_temperature():
    """
    Получает текущую температуру с улучшенной обработкой ошибок
    """
    weather_data = get_weather()
    if weather_data:
        logger.info(f"Данные о погоде получены: {weather_data}")
        try:
            # Убираем градусы и пробелы, преобразуем в число с плавающей точкой
            temperature_str = weather_data['temperature'].replace('°C', '').strip()
            return float(temperature_str)  # Преобразуем в float
        except (ValueError, KeyError) as e:
            logger.error(f"Ошибка при преобразовании температуры в число: {e}")
            return None
    else:
        logger.warning("Не удалось получить данные о погоде.")
        return None

def determine_activated_days(temperature):
    """
    Определяет актированные дни на основе температуры
    """
    if temperature is None:
        return []
        
    activated_classes = []
    if temperature <= -45:
        activated_classes.append("1-4 классы")
    if temperature <= -48:
        activated_classes.append("1-7 классы")
    if temperature <= -50:
        activated_classes.append("1-9 классы")
    if temperature <= -52:
        activated_classes.append("1-11 классы")
    return activated_classes

# Пример использования и тестирования
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Тестирование экспоненциальной задержки
    backoff = ExponentialBackoff(base_delay=1.0, max_delay=10.0, max_retries=5)
    print("Тест экспоненциальной задержки:")
    for i in range(5):
        delay = backoff.get_delay(i)
        print(f"Попытка {i+1}: {delay:.2f} сек")
    
    # Тестирование получения погоды
    print("\nТест получения погоды:")
    weather = get_weather()
    if weather:
        print(f"Погода: {weather}")
    else:
        print("Не удалось получить данные о погоде")