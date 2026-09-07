# 1. Usar una base oficial y ligera de Python
FROM python:3.10-slim

# 2. Establecer la carpeta de trabajo dentro del servidor
WORKDIR /app

# 3. Copiar todos tus archivos al servidor
COPY . /app

# 4. Forzar la instalación de todas las librerías y Streamlit
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir streamlit playwright

# 5. Instalar el navegador invisible para el bot P2P
RUN playwright install chromium --with-deps

# 6. Exponer el puerto para la interfaz PANKI
EXPOSE 8080

# 7. Encender ambos motores (Bot y Dashboard) en simultáneo
CMD ["sh", "-c", "python main.py & streamlit run dashboard.py --server.port 8080 --server.address 0.0.0.0"]
