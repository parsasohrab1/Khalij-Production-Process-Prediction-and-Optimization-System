#!/bin/sh
# If no certificate exists, generates a self-signed one for the development environment (NFR-SEC-02).
set -e
CERT_DIR=/etc/nginx/certs
if [ ! -f "$CERT_DIR/server.crt" ] || [ ! -f "$CERT_DIR/server.key" ]; then
  echo "Generating a self-signed certificate for TLS 1.3..."
  apk add --no-cache openssl >/dev/null
  openssl req -x509 -nodes -newkey rsa:2048 \
    -keyout "$CERT_DIR/server.key" \
    -out "$CERT_DIR/server.crt" \
    -days 365 \
    -subj "/CN=khalij-pos.local/O=Khalij Holding/C=IR"
fi
exec nginx -g "daemon off;"
