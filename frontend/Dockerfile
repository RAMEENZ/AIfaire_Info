FROM node:26-alpine AS builder

WORKDIR /app

# NEXT_PUBLIC_ vars are inlined at build time by Next.js — must pass as ARG
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}

COPY package*.json ./
RUN npm install --legacy-peer-deps && npm cache clean --force

COPY . .
RUN npm run build


FROM node:26-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
# Le serveur standalone doit écouter sur toutes les interfaces pour être
# joignable depuis l'extérieur du conteneur (pas seulement localhost).
ENV HOSTNAME=0.0.0.0

# Sortie "standalone" : on ne copie que le strict nécessaire (server.js + deps
# tracées), pas tout node_modules. Image bien plus légère et reproductible.
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000

CMD ["node", "server.js"]
