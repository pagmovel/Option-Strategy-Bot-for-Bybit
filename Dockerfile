# Usa a imagem oficial do Python mais recente
FROM python:latest

# Define o diretório de trabalho no contêiner
WORKDIR /app

# Copia o arquivo requirements.txt para o contêiner
COPY requirements.txt .

# Instala as dependências do Python
RUN pip install --no-cache-dir -r requirements.txt

# Copia o restante dos arquivos do projeto para o contêiner
COPY . .

# Comando padrão para rodar o contêiner com o watchdog
CMD ["watchmedo", "auto-restart", "--patterns=*.py", "--recursive", "python", "app.py"]
