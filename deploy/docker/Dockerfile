FROM python:3.11-slim

WORKDIR /opt/hermes-link-server
COPY pyproject.toml ./
COPY src ./src
RUN HTTP_PROXY= HTTPS_PROXY= ALL_PROXY= http_proxy= https_proxy= all_proxy= \
    pip install --no-cache-dir --retries 5 --timeout 120 . \
    && useradd --system --uid 10001 --create-home hermes-link \
    && install -d -o hermes-link -g hermes-link /var/lib/hermes-link-server

USER 10001:10001
ENV PYTHONDONTWRITEBYTECODE=1
ENV HERMES_LINK_PAIRING_DB=/var/lib/hermes-link-server/pairing.db

CMD ["python", "-m", "hermes_link.integrations.hermes_agent.bridge"]
