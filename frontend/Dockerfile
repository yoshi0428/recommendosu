FROM node:26-alpine AS build

WORKDIR /app

COPY package*.json ./

RUN npm ci

COPY . .

RUN npm run build

# Only the built static files are served, so Node and node_modules stay in the
# build stage. (compose.local.yml runs the Vite dev server from that stage.)
# compose.production.yml mounts the server config, nginx/nginx.frontend.conf.
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 4173
