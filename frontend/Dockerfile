# -- Build stage --
FROM node:22-alpine AS build

WORKDIR /app

ARG VITE_API_BASE
ENV VITE_API_BASE=${VITE_API_BASE:-/api}

COPY package.json package-lock.json* ./
RUN npm install

COPY . .
RUN npm run build

# -- Production stage --
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
