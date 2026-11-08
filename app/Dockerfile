FROM python:3.12-slim
WORKDIR /app
# Speedtest CLI (Ookla) - oficjalny test speedtest.net. Pobierany przy budowie; jeśli się nie uda, aplikacja
# używa zapasowego testu (Cloudflare). Licencja Ookla: użytek osobisty / niekomercyjny.
# Pusta wartość (--build-arg OOKLA_VERSION=) = bez Ookli; tak budowany jest publiczny obraz.
ARG OOKLA_VERSION=1.2.0
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && \
    case "$(uname -m)" in x86_64) A=x86_64;; aarch64|arm64) A=aarch64;; armv7l|armhf) A=armhf;; i386|i686) A=i386;; *) A="";; esac; \
    if [ -n "$A" ] && [ -n "$OOKLA_VERSION" ] && curl -fsSL "https://install.speedtest.net/app/cli/ookla-speedtest-${OOKLA_VERSION}-linux-${A}.tgz" -o /tmp/st.tgz; then \
      tar -xzf /tmp/st.tgz -C /usr/local/bin speedtest && chmod +x /usr/local/bin/speedtest && rm -f /tmp/st.tgz && \
      echo "Ookla speedtest zainstalowany"; \
    else echo "UWAGA: nie udało się pobrać Ookla speedtest - będzie używany test zapasowy"; fi; \
    apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn","main:app","--host","0.0.0.0","--port","8000","--proxy-headers","--forwarded-allow-ips=*","--timeout-keep-alive","75"]
