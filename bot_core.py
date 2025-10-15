import asyncio
import logging
from parsing.scheduler import Scheduler
from parsing.site_parser import SiteParser  # Импорт SiteParser
from config import ConfigLoader

logger = logging.getLogger(__name__)

async def initialize_bot(config):
    """
    Инициализирует бота и возвращает планировщик задач.

    :param config: Конфигурация бота, загруженная из config.yaml.
    :return: Экземпляр Scheduler.
    """
    # Создаем список парсеров для каждого сайта из конфигурации
    parsers = []
    failed_sites = []
    
    for site in config.sites:
        try:
            parser = SiteParser(
                url=site.url,
                site_type=site.type,
                cookies=site.cookies,  # Передаем cookies из конфигурации
                schedules=site.schedules  # Передаем расписание из конфигурации
            )
            parsers.append(parser)
            logger.info(f"Создан парсер для сайта: {site.name} ({site.url})")
            
        except Exception as e:
            error_msg = f"Ошибка создания парсера для {site.name} ({site.url}): {e}"
            logger.error(error_msg)
            failed_sites.append(site.name)
            continue

    # Создаем экземпляр Scheduler
    try:
        scheduler = Scheduler(config)
        logger.info("Планировщик задач успешно создан.")
    except Exception as e:
        error_msg = f"Ошибка создания планировщика: {e}"
        logger.error(error_msg)
        raise

    # Добавляем задачи для каждого парсера в планировщик
    successful_jobs = 0
    failed_jobs = 0
    
    for parser in parsers:
        try:
            await scheduler.add_job(parser)
            logger.info(f"Задача для сайта {parser.url} добавлена в планировщик.")
            successful_jobs += 1
            
        except Exception as e:
            error_msg = f"Ошибка добавления задачи для {parser.url}: {e}"
            logger.error(error_msg)
            failed_jobs += 1
            continue

    # Логируем итоговый отчет
    summary_msg = (
        f"✅ Инициализация завершена:\n"
        f"• Успешных парсеров: {successful_jobs}\n"
        f"• Неудачных задач: {failed_jobs}\n"
        f"• Не созданных парсеров: {len(failed_sites)}"
    )
    
    if failed_sites:
        summary_msg += f"\n• Проблемные сайты: {', '.join(failed_sites)}"
    
    logger.info(summary_msg)

    return scheduler

async def update_bot_config(scheduler, new_config):
    """
    Обновляет конфигурацию бота
    """
    try:
        await scheduler.update_config(new_config)
        logger.info("Конфигурация бота успешно обновлена")
        return scheduler
    except Exception as e:
        error_msg = f"Ошибка обновления конфигурации: {e}"
        logger.error(error_msg)
        raise