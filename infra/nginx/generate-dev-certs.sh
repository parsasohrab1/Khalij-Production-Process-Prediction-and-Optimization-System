#!/usr/bin/env sh
# Generate a self-signed certificate for the development environment (TLS 1.3 / NFR-SEC-02)
# In production a valid CA certificate must be used.
set -e
CERT_DIR="$(dirname "$0")/certs"
mkdir -p "$CERT_DIR"
openssl req -x509 -nodes -newkey rsa:2048 \
  -keyout "$CERT_DIR/server.key" \
  -out "$CERT_DIR/server.crt" \
  -days 365 \
  -subj "/CN=khalij-pos.local/O=Khalij Holding/C=IR"
echo "Certificate generated: $CERT_DIR/server.crt"
