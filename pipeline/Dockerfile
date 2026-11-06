FROM python:3.13-slim

WORKDIR /app

# Install Python dependencies
RUN pip install --no-cache-dir duckdb "psycopg[binary]" python-dotenv

# Copy project files
COPY pipeline/ /app/pipeline/
COPY data/processed/parquet/ /app/data/processed/parquet/

# Run the pipeline loader
CMD ["python", "pipeline/src/pipeline/load.py"]