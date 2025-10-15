def _format_weather_message(self, weather_data: dict) -> str:
    """Форматирует сообщение о погоде с дополнительными данными."""
    observation_time = datetime.strptime(
        weather_data["observation_time"], "%d.%m.%Y %H:%M"
    ).strftime("%H:%M")
    
    # Получаем текущую дату в Якутске
    current_date_yakutsk = datetime.now(YAKUTSK_TZ).strftime("%d.%m.%Y")
    
    # Формируем основное сообщение в нужном формате
    weather_message = (
        f"Погода в с.{weather_data['location']} на {current_date_yakutsk}\n"
        f"Время наблюдения: {observation_time}\n\n"
        f"Температура воздуха: {weather_data['temperature']}\n"
        f"Относительная влажность: {weather_data.get('humidity', 'N/A')}\n"
        f"Атмосферное давление: {weather_data.get('pressure', 'N/A')}\n"
        f"Осадки: {weather_data.get('precipitation', 'N/A')}\n"
        f"Облачность: {weather_data.get('cloudiness', 'N/A')}\n"
        f"Ветер: {weather_data.get('wind_direction', 'N/A')}, {weather_data.get('wind_speed', 'N/A')}\n"
        f"Видимость: {weather_data.get('visibility', 'N/A')}\n\n"
        f"Подробнее: https://meteoinfo.ru/pogoda/russia/republic-saha-yakutia/ytyk-kel"
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

        # Добавляем информацию об актированных днями только при температуре <= -45°C
        if temperature is not None and temperature <= -45:
            weather_message += "\n\n"
            if temperature <= -45:
                weather_message += (
                    f"По данным наблюдения на {observation_time}:\n"
                    f"Актированный день: 1-4 классы."
                )
            elif temperature <= -48:
                weather_message += (
                    f"По данным наблюдения на {observation_time}:\n"
                    f"Актированный день: 1-7 классы."
                )
            elif temperature <= -50:
                weather_message += (
                    f"По данным наблюдения на {observation_time}:\n"
                    f"Актированный день: 1-9 классы."
                )
            elif temperature <= -52:
                weather_message += (
                    f"По данным наблюдения на {observation_time}:\n"
                    f"Актированный день: 1-11 классы."
                )

    return weather_message