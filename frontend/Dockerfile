FROM node:20-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm install

COPY . .

EXPOSE 5173

# --host so Vite's dev server is reachable from outside the container, not
# just localhost inside it. Paired with a bind-mounted source dir (see
# docker-compose.yml) so edits on your host hot-reload without a rebuild.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
