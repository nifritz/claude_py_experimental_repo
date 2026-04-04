# docker/claude-code/Dockerfile
#
# Container Claude Code CLI
#
# - Eseguito interattivamente: docker exec -it claude-code claude
# - Accede al container python-utils via Docker socket (per MCP stdio)
# - La config MCP viene montata dall'host

FROM node:20-slim

# Docker CLI (solo client — usa il daemon dell'host via socket)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Workspace di default (montato dall'host)
WORKDIR /workspace

# Mantieni il container vivo per sessioni interattive
CMD ["sleep", "infinity"]
