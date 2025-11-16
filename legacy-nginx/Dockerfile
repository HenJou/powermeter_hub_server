# TODO README, this is insecure and ancient. Only run in an isolated environment.

# ===== BUILDER STAGE =====
FROM debian:stretch AS builder

# Use archived main and security repos
RUN sed -i '/stretch-updates/d' /etc/apt/sources.list \
    && sed -i 's|deb.debian.org|archive.debian.org|g' /etc/apt/sources.list \
    && sed -i 's|security.debian.org|archive.debian.org|g' /etc/apt/sources.list \
    && echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99no-check-valid-until \
    && apt-get update \
    && apt-get install -y \
        build-essential \
        wget \
        ca-certificates \
        libssl-dev \
        zlib1g-dev \
        libpcre3-dev \
        perl \
    && rm -rf /var/lib/apt/lists/*

# Set workdir for source downloads
WORKDIR /usr/local/src

# ===== Download sources =====
# OpenSSL 1.0.2u
RUN wget --no-check-certificate https://www.openssl.org/source/old/1.0.2/openssl-1.0.2u.tar.gz \
    && tar xzf openssl-1.0.2u.tar.gz

# Nginx 1.10.3
RUN wget --no-check-certificate http://nginx.org/download/nginx-1.10.3.tar.gz \
    && tar xzf nginx-1.10.3.tar.gz

# PCRE 8.45
RUN wget --no-check-certificate https://sourceforge.net/projects/pcre/files/pcre/8.45/pcre-8.45.tar.gz \
    && tar xzf pcre-8.45.tar.gz

# zlib 1.2.11
RUN wget --no-check-certificate https://zlib.net/fossils/zlib-1.2.11.tar.gz \
    && tar xzf zlib-1.2.11.tar.gz

# ===== Build OpenSSL with SSLv3 support =====
WORKDIR /usr/local/src/openssl-1.0.2u
RUN ./config no-shared --prefix=/opt/openssl enable-ssl2 enable-ssl3 enable-ssl3-method \
    && make \
    && make install_sw

# ===== Build Nginx with SSLv3 support =====
WORKDIR /usr/local/src/nginx-1.10.3
RUN ./configure \
    --prefix=/opt/nginx \
    --with-http_ssl_module \
    --with-openssl=/usr/local/src/openssl-1.0.2u \
    --with-openssl-opt="no-shared enable-ssl2 enable-ssl3 enable-ssl3-method" \
    --with-pcre=/usr/local/src/pcre-8.45 \
    --with-zlib=/usr/local/src/zlib-1.2.11 \
    && make -j1 \
    && make install

# ===== FINAL IMAGE =====
FROM debian:stretch-slim

# Install editors for debugging
RUN sed -i '/stretch-updates/d' /etc/apt/sources.list \
    && sed -i 's|deb.debian.org|archive.debian.org|g' /etc/apt/sources.list \
    && sed -i 's|security.debian.org|archive.debian.org|g' /etc/apt/sources.list \
    && echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99no-check-valid-until \
    && apt-get update \
    && apt-get install -y nano vim \
    && rm -rf /var/lib/apt/lists/*

# Copy Nginx and OpenSSL from builder
COPY --from=builder /opt/nginx /opt/nginx
COPY --from=builder /opt/openssl /opt/openssl

# Add OpenSSL to PATH
ENV PATH="/opt/openssl/bin:$PATH"
ENV PATH="/opt/nginx/sbin:$PATH"

# Default config
COPY nginx.conf /opt/nginx/conf/nginx.conf
COPY server.crt /opt/nginx/conf/server.crt
COPY server.key /opt/nginx/conf/server.key

# Expose SSL port
EXPOSE 443

# Run Nginx in foreground
CMD ["/opt/nginx/sbin/nginx", "-g", "daemon off;"]
