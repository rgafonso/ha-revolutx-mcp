FROM node:20-alpine

# Install build dependencies
RUN apk add --no-cache git python3 make g++

# Clone revolut-x-api (pinned for reproducible builds)
ARG REVOLUT_X_API_REF=v1.0.47
WORKDIR /app
RUN git clone --branch "$REVOLUT_X_API_REF" --depth 1 https://github.com/revolut-engineering/revolut-x-api.git .

# Install dependencies and build
RUN npm ci && \
    npm run build -w api && \
    npm run build -w mcp

# Create config directory for credentials
RUN mkdir -p /config/revolut-x && chmod 700 /config/revolut-x

# Copy entrypoint script and the HTTP transport wrapper
COPY entrypoint.sh /entrypoint.sh
COPY mcp-network-transport.cjs /app/mcp-network-transport.cjs
RUN chmod +x /entrypoint.sh

# Expose MCP server port
EXPOSE 5000

# Run entrypoint
ENTRYPOINT ["/entrypoint.sh"]
