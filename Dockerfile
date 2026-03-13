FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY docs ./docs
RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "filmstudio.main:app", "--host", "0.0.0.0", "--port", "8000"]
