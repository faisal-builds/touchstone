# syntax=docker/dockerfile:1.7
# Touchstone dashboard. Multi-stage build producing a minimal standalone Next.js
# server (output: "standalone"). The dashboard is a BFF: the browser only ever
# talks to this server, which proxies to the control-plane and RHD with the
# session token.
FROM node:20-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

FROM node:20-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-slim AS runner
WORKDIR /app
# HOSTNAME=0.0.0.0 makes the Next standalone server bind all interfaces. Without
# it Next binds $HOSTNAME (Docker sets it to the container id -> the container IP),
# so an in-container probe to 127.0.0.1 is refused even though the app is up.
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN groupadd --system --gid 1001 nodejs \
    && useradd --system --uid 1001 --gid nodejs nextjs
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000

# Liveness probe via the dashboard's /api/health route (node is the only runtime
# in the image — no curl/wget).
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
  CMD ["node", "-e", "require('http').get('http://127.0.0.1:3000/api/health',r=>process.exit(r.statusCode===200?0:1)).on('error',()=>process.exit(1))"]

CMD ["node", "server.js"]
