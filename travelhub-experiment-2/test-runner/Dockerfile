FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir requests PyJWT cryptography

COPY test_runner.py .

CMD ["python", "test_runner.py", \
     "--autorizador", "http://autorizador:5001", \
     "--reservas", "http://reservas:5003"]
