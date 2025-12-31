# Gunakan image python yang ringan
FROM python:3.11-slim

# Set environtment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set working direktori
WORKDIR /app

# Install dependensi yang dibutuhkan
# - gcc & libpq-dev: Wajib untuk menginstall driver PostgreSQL (psycopg2)
# - netcat-openbsd: Opsional, berguna untuk script pengecekan database
RUN apt-get update && apt-get install -y --no-install-recommends \
  gcc \
  libpq-dev \
  netcat-openbsd \
  && rm -rf /var/lib/apt/lists/*

# Copy file requirements.txt terlebih dahulu
# Tujuannya agar Docker bisa melakukan caching pada layer install pip
COPY requirements.txt /app/

# Install dependensi python
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy sisa source code ke container
COPY . /app/

COPY ./entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
