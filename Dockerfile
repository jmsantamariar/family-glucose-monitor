FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1

WORKDIR /app

# Install Poetry into the system environment.
RUN pip install --no-cache-dir poetry==2.3.3

# Copy dependency manifests first for better layer caching.
COPY pyproject.toml poetry.lock ./

# Install only production dependencies (no dev extras, no editable install).
RUN poetry install --only main --no-root

# Copy the application source.
COPY src ./src

RUN addgroup --system appgroup \
    && adduser --system --ingroup appgroup --no-create-home appuser \
    && chown -R appuser:appgroup /app

USER appuser
EXPOSE 8080
CMD ["python", "-m", "src.main"]
