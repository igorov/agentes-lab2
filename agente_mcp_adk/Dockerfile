FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

# adk web descubre agent.py en el directorio actual
CMD ["adk", "web", ".", "--host", "0.0.0.0", "--port", "8080"]
