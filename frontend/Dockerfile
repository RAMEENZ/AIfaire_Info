FROM node:20-alpine AS builder

WORKDIR /app

# NEXT_PUBLIC_ vars are inlined at build time by Next.js — must pass as ARG
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}

COPY package*.json ./
RUN npm ci --legacy-peer-deps

COPY . .
RUN npm run build


FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000

COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/public ./public

EXPOSE 3000

CMD ["node_modules/.bin/next", "start", "-p", "3000"]
