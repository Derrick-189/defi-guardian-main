# Dockerfile 
 FROM python:3.10-slim 
 
 # Install system dependencies 
RUN apt-get update && apt-get install -y \ 
    gcc \ 
    make \
    flex \
    bison \
    graphviz \ 
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/* 

# Install SPIN Model Checker from source
RUN cd /tmp && \
    wget -q https://github.com/nimble-code/Spin/archive/refs/tags/version-6.5.2.tar.gz -O spin.tar.gz && \
    tar -xzf spin.tar.gz && \
    cd Spin-version-6.5.2/Src && \
    make && \
    cp spin /usr/local/bin/ && \
    chmod +x /usr/local/bin/spin && \
    cd /tmp && \
    rm -rf spin.tar.gz Spin-version-6.5.2
 
 # Install Python dependencies 
 COPY requirements.txt . 
 RUN pip install --no-cache-dir -r requirements.txt 
 
 # Copy application 
 COPY . /app 
 WORKDIR /app 
 
 # Expose port for the Web Portal or Verification Server
EXPOSE 10000 9000

# Copy and set up entrypoint script
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]
