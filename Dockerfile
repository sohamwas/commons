# The Commons gateway, and the reference messaging vendor, which share this image and
# differ only by the command compose gives them.
#
# Nothing about Razorpay or Resend is baked in: those are remote MCP servers reached over
# HTTPS, configured at runtime from vendors.yaml. The image holds the gateway and nothing
# a merchant would have to trust us about.

FROM python:3.12-slim

# Keeps the image quiet and small: no .pyc trees, unbuffered logs so `docker compose logs`
# shows output as it happens rather than in bursts when a buffer fills.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependency metadata first, so editing a rule or a manifest does not reinstall the world.
COPY pyproject.toml ./
COPY commons/ ./commons/
COPY mcp_servers/ ./mcp_servers/

RUN pip install --no-cache-dir -e .

COPY scripts/ ./scripts/
COPY examples/ ./examples/

# Written state lives on a volume, never in the image. The gateway creates commons.db,
# agents.yaml and vendors.yaml on first run; if they were written into the image layer
# they would vanish on every rebuild, taking the decision history with them.
ENV COMMONS_DB=/data/commons.db \
    COMMONS_AGENTS=/data/agents.yaml \
    COMMONS_VENDORS=/data/vendors.yaml \
    COMMONS_HOST=0.0.0.0 \
    COMMONS_PORT=8787 \
    COMMONS_MODE=OBSERVE

RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8787

# Plain python, no shell wrapper, so SIGTERM from `docker compose down` reaches uvicorn
# and the SQLite connection closes cleanly instead of being killed after the grace period.
CMD ["python", "scripts/run_proxy.py"]
