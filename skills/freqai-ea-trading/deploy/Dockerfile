# Freqtrade 2026.10 + FreqAI, pinned from PyPI (same versions the EAs were validated with).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN useradd --create-home --uid 1000 ftuser \
 && pip install "freqtrade[freqai]==2026.10"

USER ftuser
WORKDIR /freqtrade
ENTRYPOINT ["freqtrade"]
CMD ["--help"]
