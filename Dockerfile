# Bresaola Tracker for a home server (Synology Container Manager or any Docker host)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    BRESAOLA_DATA=/data \
    BRESAOLA_MODE=persistent \
    BRESAOLA_TZ=Europe/Berlin \
    TZ=Europe/Berlin

WORKDIR /app
COPY requirements.txt requirements-local.txt ./
RUN pip install -r requirements-local.txt
COPY . .

VOLUME /data
EXPOSE 8501
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://localhost:%s/_stcore/health' % os.environ.get('PORT', '8501'))"
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0", \
     "--server.headless=true", "--browser.gatherUsageStats=false"]
