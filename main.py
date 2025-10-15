import asyncio
import logging
import os
from aiohttp import web
import time
from bot_core import initialize_bot
from config import ConfigLoader
from telegram_notifier import close_bot_session

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class HealthCheckServer:
    """
    HTTP сервер для health-check эндпоинтов
    """
    
    def __init__(self, port: int = 8080):
        self.port = port
        self.app = web.Application()
        self.runner = None
        self.setup_routes()
        
        # Ссылки на компоненты системы
        self.scheduler = None
        
    def setup_routes(self):
        """Настройка маршрутов HTTP сервера"""
        self.app.router.add_get('/health', self.health_handler)
        self.app.router.add_get('/health/detailed', self.detailed_health_handler)
        self.app.router.add_get('/health/status', self.status_handler)
        
    def set_components(self, scheduler):
        """Устанавливает ссылки на основные компоненты системы"""
        self.scheduler = scheduler
    
    async def health_handler(self, request):
        """Базовый health-check - проверка что сервис жив"""
        return web.json_response({
            "status": "healthy",
            "timestamp": time.time(),
            "service": "weather_bot",
            "version": "1.0.0"
        })
    
    async def detailed_health_handler(self, request):
        """Детальная проверка здоровья всех компонентов"""
        health_status = {
            "status": "healthy",
            "timestamp": time.time(),
            "service": "weather_bot",
            "checks": {
                "telegram": await self.check_telegram_health(),
                "scheduler": await self.check_scheduler_health(),
                "system": await self.check_system_health()
            }
        }
        
        # Если любой из компонентов нездоров - общий статус "degraded"
        if any(check["status"] == "unhealthy" for check in health_status["checks"].values()):
            health_status["status"] = "degraded"
        elif any(check["status"] == "degraded" for check in health_status["checks"].values()):
            health_status["status"] = "degraded"
            
        return web.json_response(health_status)
    
    async def status_handler(self, request):
        """Текущий статус системы"""
        status = {
            "status": "running",
            "timestamp": time.time(),
            "uptime": getattr(self, '_start_time', time.time()),
            "active_tasks": len([t for t in asyncio.all_tasks() if not t.done()])
        }
        
        if self.scheduler:
            status["scheduler"] = {
                "active_tasks": len(self.scheduler.tasks),
                "parsers_count": len(self.scheduler.parsers)
            }
            
        return web.json_response(status)
    
    async def check_telegram_health(self):
        """Проверка здоровья Telegram компонента"""
        try:
            from telegram_notifier import get_telegram_status
            status = await get_telegram_status()
            return {
                "status": "healthy" if status.get("bot_configured", False) else "unhealthy",
                "details": {
                    "bot_configured": status.get("bot_configured", False)
                }
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
    
    async def check_scheduler_health(self):
        """Проверка здоровья планировщика"""
        try:
            if not self.scheduler:
                return {"status": "unhealthy", "error": "Планировщик не инициализирован"}
            
            active_tasks = len([t for t in self.scheduler.tasks if not t.done()])
            return {
                "status": "healthy" if active_tasks > 0 else "degraded",
                "details": {
                    "active_tasks": active_tasks,
                    "total_tasks": len(self.scheduler.tasks),
                    "parsers_count": len(self.scheduler.parsers)
                }
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
    
    async def check_system_health(self):
        """Проверка системных показателей"""
        try:
            import psutil
            process = psutil.Process()
            memory_info = process.memory_info()
            
            return {
                "status": "healthy",
                "details": {
                    "memory_usage_mb": round(memory_info.rss / 1024 / 1024, 2),
                    "cpu_percent": process.cpu_percent(),
                    "threads_count": process.num_threads()
                }
            }
        except ImportError:
            return {
                "status": "healthy", 
                "details": {"message": "psutil не установлен, системные метрики недоступны"}
            }
        except Exception as e:
            return {"status": "degraded", "error": str(e)}
    
    async def start(self):
        """Запуск health-check сервера"""
        self._start_time = time.time()
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        
        site = web.TCPSite(self.runner, '0.0.0.0', self.port)
        await site.start()
        
        logger.info(f"✅ Health-check сервер запущен на порту {self.port}")
        logger.info(f"   • http://localhost:{self.port}/health")
        logger.info(f"   • http://localhost:{self.port}/health/detailed")
        
    async def stop(self):
        """Остановка health-check сервера"""
        if self.runner:
            await self.runner.cleanup()
            logger.info("✅ Health-check сервер остановлен")

async def run_bot_async():
    """Основная асинхронная функция запуска бота"""
    logger.info("🚀 Запуск бота...")
    
    # Проверяем обязательные переменные окружения
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    
    if not BOT_TOKEN:
        logger.error("❌ Критическая ошибка: Не задана переменная окружения BOT_TOKEN")
        return

    logger.info("✅ Переменная окружения BOT_TOKEN загружена")

    # Инициализация health-check сервера
    health_server = HealthCheckServer(port=8080)

    # Загрузка конфигурации
    config_loader = ConfigLoader("config.yaml")
    config = config_loader.load()
    
    if not config:
        error_msg = "❌ Критическая ошибка: Не удалось загрузить конфигурацию"
        logger.error(error_msg)
        return
    else:
        logger.info("✅ Конфигурация загружена успешно")

    try:
        # Инициализация бота
        scheduler = await initialize_bot(config)
        logger.info("✅ Бот инициализирован. Задачи добавлены.")

        # Настройка health-check сервера с компонентами
        health_server.set_components(scheduler)
        await health_server.start()

        # Логирование времени следующей проверки
        next_check = await scheduler.log_next_check_time()
        if next_check:
            logger.info(f"⏰ {next_check}")

        # Основной цикл с проверкой изменений конфига
        logger.info("🔄 Запуск основного цикла...")
        
        try:
            while True:
                # Проверяем изменения конфига каждые 30 секунд
                await asyncio.sleep(30)
                
                new_config = config_loader.load_if_changed()
                if new_config and new_config != config:
                    logger.info("🔄 Обнаружены изменения в конфигурации, применяем...")
                    await scheduler.update_config(new_config)
                    config = new_config
                    # Обновляем конфиг в health-check сервере
                    health_server.set_components(scheduler)
                    logger.info("✅ Конфигурация успешно обновлена!")
                    
        except asyncio.CancelledError:
            logger.info("⏹️ Бот остановлен по запросу")
        except Exception as e:
            error_msg = f"❌ Ошибка в основном цикле: {e}"
            logger.error(error_msg)
            raise

    except Exception as e:
        error_msg = f"💥 Критическая ошибка при запуске бота: {e}"
        logger.exception(error_msg)
        raise
        
    finally:
        # Корректное завершение работы
        logger.debug("🔚 Завершение работы бота...")
        
        # Останавливаем health-check сервер
        await health_server.stop()
        
        # Ожидание завершения оставшихся задач
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if tasks:
            logger.info("⏳ Ожидание завершения оставшихся задач...")
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as e:
                error_msg = f"⚠️ Ошибка при завершении задач: {e}"
                logger.error(error_msg)
                
        logger.info("✅ Бот завершил работу")
        await close_bot_session()

async def shutdown():
    """Корректное завершение работы бота"""
    logger.info("🛑 Запуск процедуры остановки бота...")
    
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("✅ Все задачи корректно завершены")
    except Exception as e:
        logger.error(f"⚠️ Ошибка при завершении задач: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(run_bot_async())
    except KeyboardInterrupt:
        logger.info("⏹️ Бот остановлен по запросу пользователя (Ctrl+C)")
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(close_bot_session())
            loop.close()
        except RuntimeError as e:
            logger.error(f"⚠️ Не удалось корректно закрыть сессию: {e}")
    except Exception as e:
        logger.critical(f"💥 Необработанная ошибка: {e}")
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(close_bot_session())
            loop.close()
        except RuntimeError as ex:
            logger.error(f"⚠️ Не удалось корректно закрыть сессию: {ex}")