# GPI Document Hub - Frontend (Production Build)
FROM node:20-alpine as builder

WORKDIR /app

# Copy package files (yarn.lock may not exist on first build)
COPY package.json ./
COPY yarn.lock* ./

# Install dependencies
RUN yarn install

# Copy source code
COPY . .

# Build argument for backend URL
ARG REACT_APP_BACKEND_URL
ENV REACT_APP_BACKEND_URL=$REACT_APP_BACKEND_URL

# Build production bundle
RUN yarn build

# Production stage with nginx
FROM nginx:alpine

# Copy custom nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built assets
COPY --from=builder /app/build /usr/share/nginx/html

# Expose port
EXPOSE 3000

# Health check
# Uses 127.0.0.1, not localhost: nginx.conf binds only 0.0.0.0 (IPv4), but
# the container's /etc/hosts resolves "localhost" to ::1 first, so wget
# against "localhost" always hit a dead IPv6 loopback and refused the
# connection -- this left the container reporting unhealthy indefinitely
# even while nginx was correctly serving real traffic on the mapped port.
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget -q --spider http://127.0.0.1:3000 || exit 1

CMD ["nginx", "-g", "daemon off;"]
