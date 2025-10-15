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
        
        # Парсим время наблюдения
        time_cell = weather_table.find('td', {'colspan': '2'})
        if not time_cell:
            logger.error("Время наблюдения не найдено.")
            return None

        observation_time = parse_observation_time(time_cell.text)
        if not observation_time:
            return None
        
        # Парсим все строки таблицы
        data = {}
        rows = weather_table.find_all('tr')[1:]  # Пропускаем строку с временем
        
        for row in rows:
            cells = row.find_all('td')
            if len(cells) == 2:
                param = cells[0].text.strip()
                value = cells[1].text.strip()
                
                # Нормализуем названия параметров
                if 'Атмосферное давление' in param:
                    data['pressure'] = value + ' мм рт.ст.'
                elif 'Температура воздуха' in param:
                    data['temperature'] = value + '°C'
                elif 'Минимальная температура' in param:
                    data['min_temperature'] = value + '°C'
                elif 'Относительная влажность' in param:
                    data['humidity'] = value + '%'
                elif 'Направление ветра' in param:
                    data['wind_direction'] = value
                elif 'Средняя скорость ветра' in param:
                    data['wind_speed'] = value + ' м/с'
                elif 'Балл общей облачности' in param:
                    data['cloudiness'] = value + ' баллов'
                elif 'Горизонтальная видимость' in param:
                    data['visibility'] = value + ' км'
        
        # Парсим осадки (особая структура)
        precipitation_data = self._parse_precipitation(rows)
        if precipitation_data:
            data['precipitation'] = precipitation_data
        
        return {
            "location": "Ытык-Кюель",
            "observation_time": observation_time.strftime("%d.%m.%Y %H:%M"),
            "temperature": data.get('temperature', 'N/A'),
            "min_temperature": data.get('min_temperature', 'N/A'),
            "humidity": data.get('humidity', 'N/A'),
            "wind_direction": data.get('wind_direction', 'N/A'),
            "wind_speed": data.get('wind_speed', 'N/A'),
            "pressure": data.get('pressure', 'N/A'),
            "precipitation": data.get('precipitation', 'N/A'),
            "cloudiness": data.get('cloudiness', 'N/A'),
            "visibility": data.get('visibility', 'N/A')
        }
    
    def _parse_precipitation(self, rows):
        """
        Парсит данные об осадках из специальной структуры таблицы
        """
        try:
            for i, row in enumerate(rows):
                cells = row.find_all('td')
                
                # Ищем строку с rowspan="2" (это первая часть блока осадков)
                if len(cells) == 2 and cells[0].get('rowspan') == '2':
                    # Следующая строка должна содержать текстовое описание осадков
                    if i + 1 < len(rows):
                        next_row = rows[i + 1]
                        next_cells = next_row.find_all('td')
                        if len(next_cells) == 1:  # Одна ячейка с текстом осадков
                            precipitation_text = next_cells[0].text.strip()
                            if precipitation_text:
                                return precipitation_text
            
            # Альтернативный поиск: строка с одной ячейкой, содержащей текст осадков
            for row in rows:
                cells = row.find_all('td')
                if len(cells) == 1:
                    text = cells[0].text.strip()
                    # Проверяем, что это описание погодных явлений (осадки)
                    if text and any(keyword in text.lower() for keyword in 
                                   ['снег', 'дождь', 'осадк', 'туман', 'метель', 'град', 'мокрый', 'ливень']):
                        return text
                    
        except Exception as e:
            logger.error(f"Ошибка при парсинге осадков: {e}")
    
        return 'Без осадков'

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
    
    # Тестирование получения погоды
    print("\nТест получения погоды:")
    weather = get_weather()
    if weather:
        print(f"Погода: {weather}")
    else:
        print("Не удалось получить данные о погоде")