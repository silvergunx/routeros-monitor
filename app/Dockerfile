FROM python:3.12-slim
WORKDIR /app
# Speedtest CLI (Ookla) - oficjalny test speedtest.net. Pobierany przy budowie; jeśli się nie uda, aplikacja
# używa zapasowego testu (Cloudflare). Licencja Ookla: użytek osobisty / niekomercyjny.
# Pusta wartość (--build-arg OOKLA_VERSION=) = bez Ookli; tak budowany jest publiczny obraz.
ARG OOKLA_VERSION=1.2.0
# LibreSpeed CLI (LGPL-3.0, github.com/librespeed/speedtest-cli): wersja i sumy SHA-256 przypięte do wydania; błędna suma przerywa budowę.
ARG LIBRESPEED_VERSION=1.0.14
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && \
    case "$(uname -m)" in x86_64) A=x86_64;; aarch64|arm64) A=aarch64;; armv7l|armhf) A=armhf;; i386|i686) A=i386;; *) A="";; esac; \
    if [ -n "$A" ] && [ -n "$OOKLA_VERSION" ] && curl -fsSL "https://install.speedtest.net/app/cli/ookla-speedtest-${OOKLA_VERSION}-linux-${A}.tgz" -o /tmp/st.tgz; then \
      tar -xzf /tmp/st.tgz -C /usr/local/bin speedtest && chmod +x /usr/local/bin/speedtest && rm -f /tmp/st.tgz && \
      echo "Ookla speedtest zainstalowany"; \
    else echo "UWAGA: nie udało się pobrać Ookla speedtest - będzie używany test zapasowy"; fi; \
    case "$(uname -m)" in \
      x86_64) L=amd64; H=89800767ac14085c78a20847ebea23340f6c14a78de0a15c2ac7db8b565c961f;; \
      aarch64|arm64) L=arm64; H=75e51a2494d03cb35a92ddbf862b40571a25a1526f3cf3dfa8b1d5d7bc622bd9;; \
      armv7l|armhf) L=armv7; H=527591b4049136feeed73a00203f27362ce6aab7f11973c4985d1507ee469ec4;; \
      i386|i686) L=386; H=e2671230b8b6372df3a5910959dfea960915727b4db05f42856dc66dfb6132b2;; \
      *) L="";; esac; \
    if [ -n "$L" ] && [ "$LIBRESPEED_VERSION" = "1.0.14" ] && curl -fsSL "https://github.com/librespeed/speedtest-cli/releases/download/v${LIBRESPEED_VERSION}/librespeed-cli_${LIBRESPEED_VERSION}_linux_${L}.tar.gz" -o /tmp/ls.tgz; then \
      echo "$H  /tmp/ls.tgz" | sha256sum -c - || exit 1; \
      mkdir -p /usr/share/doc/librespeed-cli && tar -xzf /tmp/ls.tgz -C /usr/local/bin librespeed-cli && tar -xzf /tmp/ls.tgz -C /usr/share/doc/librespeed-cli LICENSE && \
      chmod +x /usr/local/bin/librespeed-cli && rm -f /tmp/ls.tgz && echo "LibreSpeed CLI zainstalowany"; \
    else echo "UWAGA: nie udało się pobrać LibreSpeed CLI - będzie używany test zapasowy"; fi; \
    apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn","main:app","--host","0.0.0.0","--port","8000","--proxy-headers","--forwarded-allow-ips=*","--timeout-keep-alive","75"]
