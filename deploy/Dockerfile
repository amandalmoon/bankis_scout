FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml /app/
COPY requirements.lock /app/
COPY bankis_scout /app/bankis_scout
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps .
RUN useradd --uid 10001 --create-home bankis && mkdir -p /app/data /app/reports /app/.secrets && chown bankis:bankis /app/data /app/reports /app/.secrets
USER bankis
ENV TZ=Asia/Seoul PYTHONUNBUFFERED=1 BANKIS_HOME=/app
CMD ["python", "-m", "bankis_scout.pipeline", "--collect"]
