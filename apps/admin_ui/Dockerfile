FROM node:22-alpine
WORKDIR /app
COPY apps/admin_ui/package.json ./package.json
RUN npm install
COPY apps/admin_ui .
ENV VITE_API_BASE=http://localhost:8080
EXPOSE 3000
CMD ["npm", "run", "dev"]
