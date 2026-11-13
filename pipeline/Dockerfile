FROM python:3.13-slim

WORKDIR /app

# Install Python dependencies (one list, shared with local runs)
COPY pipeline/requirements.txt /app/pipeline/requirements.txt
RUN pip install --no-cache-dir -r pipeline/requirements.txt

# Copy the code and SQL only. The data is NOT copied into the image:
# compose.yaml shares the data/ folder with the container instead.
COPY pipeline/ /app/pipeline/

# Run the whole pipeline: ingest -> clean -> load
CMD ["python", "pipeline/src/pipeline/run.py"]