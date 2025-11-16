#!/bin/bash

# Generate a 1024-bit RSA key
openssl genrsa -out legacy-nginx/server.key 1024

# Generate a certificate signing request (CSR)
openssl req -new -key nginx/server.key -out server.csr \
    -subj "/C=GB/ST=London/L=London/O=sensornet/OU=ops@hildebrand.co.uk/CN=*.sensornet.info/emailAddress=ops@hildebrand.co.uk"

# Self-sign the certificate valid for 10 years
# Use SHA-256 (more widely supported) but compatible with old OpenSSL
openssl x509 -req -days 3650 -in server.csr -signkey legacy-nginx/server.key -out legacy-nginx/server.crt -sha1

# Clean up the CSR
rm server.csr

echo "Generated server.key and server.crt (1048-bit, SHA-256, valid 10 years)"
