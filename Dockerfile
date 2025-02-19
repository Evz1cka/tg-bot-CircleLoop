# Базовый образ Python (используем версию 3.12)
FROM python:3.12

# Устанавливаем рабочую директорию в контейнере
WORKDIR /bot

# Копируем все файлы бота в контейнер
COPY . .

# Устанавливаем зависимости (из файла requirements.txt)
RUN pip install --no-cache-dir -r requirements.txt

# Запускаем бота
CMD ["python", "BotCircleLoop.py"]
