# Dockerfile
FROM python:3.10-slim

ENV PIP_NO_PROGRESS_BAR=1

WORKDIR /app

COPY requirements.txt .

# Atualiza o pip e instala as dependências
RUN pip install --upgrade pip --progress-bar=off && \
    pip install --no-cache-dir --progress-bar=off -r requirements.txt


COPY . .

CMD ["watchmedo", "auto-restart", "--patterns=*.py", "--recursive", "python", "app.py"]
