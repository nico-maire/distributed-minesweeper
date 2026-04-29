FROM python:3.10-slim

WORKDIR /app

# Copia los archivos del proyecto al contenedor
COPY . .
