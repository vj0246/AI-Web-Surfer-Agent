FROM node:20-slim

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

ARG VITE_BACKEND_API_URL=http://localhost:8000
ENV VITE_BACKEND_API_URL=$VITE_BACKEND_API_URL

CMD ["npm", "run", "dev"]
