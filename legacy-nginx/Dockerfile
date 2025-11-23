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
        xz-utils \
    && rm -rf /var/lib/apt/lists/*

# ---- OFFLINE SOURCE BUNDLE ----
ADD sources-bundle.tar.gz /usr/local/
WORKDIR /usr/local/sources

# Verify checksums
RUN sha256sum -c sources.sha256

# Extract tarballs
RUN tar -xzf /usr/local/sources/openssl-1.0.2u.tar.gz \
    && tar -xzf /usr/local/sources/nginx-1.10.3.tar.gz \
    && tar -xzf /usr/local/sources/pcre-8.45.tar.gz \
    && tar -xzf /usr/local/sources/zlib-1.2.11.tar.gz

# ===== Build OpenSSL with SSLv2/3 support =====
WORKDIR /usr/local/sources/openssl-1.0.2u
RUN ./config no-shared --prefix=/opt/openssl enable-ssl2 enable-ssl3 enable-ssl3-method \
    && make -j"$(nproc)" \
    && make install_sw

# ===== Build Nginx with SSLv2/3 support =====
WORKDIR /usr/local/sources/nginx-1.10.3
RUN ./configure \
    --prefix=/opt/nginx \
    --with-http_ssl_module \
    --with-openssl=/usr/local/sources/openssl-1.0.2u \
    --with-openssl-opt="no-shared enable-ssl2 enable-ssl3 enable-ssl3-method" \
    --with-pcre=/usr/local/sources/pcre-8.45 \
    --with-zlib=/usr/local/sources/zlib-1.2.11 \
    && make -j"$(nproc)" \
    && make install

# ===== FINAL IMAGE =====
FROM debian:stretch-slim

LABEL org.opencontainers.image.description="Legacy Nginx for PowerMeter Hub Server."

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
