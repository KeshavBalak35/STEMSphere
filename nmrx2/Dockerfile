FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY . .
RUN pip install --no-cache-dir '.[quantum,docking]' pyscf-properties==0.1.0 && useradd -m nmrx && mkdir -p data && chown -R nmrx:nmrx /app
USER nmrx
EXPOSE 8000
CMD ["uvicorn", "nmrx.api:app", "--host", "0.0.0.0", "--port", "8000"]
