# Fallback deployment (Render / any container host). Streamlit Community Cloud
# does not need this file.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV PORT=8501
EXPOSE 8501
# Render injects $PORT; default to 8501 elsewhere.
CMD streamlit run app.py --server.port ${PORT} --server.address 0.0.0.0 --server.headless true
