FROM python:3.12-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py config.py ./

EXPOSE 9000

CMD ["python", "server.py"]
