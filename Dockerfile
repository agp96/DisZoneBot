FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias del sistema necesarias para compilar librerías C/C++ y herramientas espaciales
RUN apt-get update && apt-get install -y \
    build-essential \
    libproj-dev \
    proj-data \
    proj-bin \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# --no-cache-dir ahorra espacio en la imagen
RUN pip install --no-cache-dir -r requirements.txt

# Copiamos el resto del código
COPY . .

# Comando de ejecución principal
CMD ["python", "main.py"]

