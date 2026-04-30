FROM node:22-alpine

WORKDIR /app

# Install dependencies
COPY package.json package-lock.json* ./
RUN npm ci

# Copy source code
COPY . .

# Build once and run without file watching inside Docker.
RUN npm run build

CMD ["npm", "run", "start"]
