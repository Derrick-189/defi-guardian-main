# Dockerfile 
 FROM python:3.10-slim 
 
 # Install system dependencies 
 RUN apt-get update && apt-get install -y \ 
     gcc \ 
     graphviz \ 
     && rm -rf /var/lib/apt/lists/* 
 
 # Install SPIN 
 # Note: Assumes spin binary exists in spin-binaries/ directory
 COPY spin-binaries/spin /usr/local/bin/ 
 RUN chmod +x /usr/local/bin/spin 
 
 # Install Python dependencies 
 COPY requirements.txt . 
 RUN pip install -r requirements.txt 
 
 # Copy application 
 COPY . /app 
 WORKDIR /app 
 
 # Expose ports for Streamlit and Desktop/Websocket services
 EXPOSE 8501 8502 
 
 # Run application 
 CMD ["python", "launcher.py"]
