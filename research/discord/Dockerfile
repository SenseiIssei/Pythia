# Pythia's Discord bot (research/ops/discord-bot.sh builds and runs it).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHIA_DATA=/data PYTHIA_DISCORD_STATE=/state
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pythia_discord ./pythia_discord
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin pythia
USER 10001
CMD ["python", "-m", "pythia_discord.bot"]
