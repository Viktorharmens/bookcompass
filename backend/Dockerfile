FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# De API draait niet als root. De entrypoint start nog wel als root, alleen om de datamap (een volume van de host)
# aan de gebruiker 'app' te geven; daarna laat hij alle rechten vallen.
RUN useradd --system --uid 10001 --no-create-home app && chmod +x /app/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
