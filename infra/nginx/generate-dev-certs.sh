#!/usr/bin/env sh
# تولید گواهی خودامضا برای محیط توسعه (TLS 1.3 / NFR-SEC-02)
# در production باید از گواهی معتبر CA استفاده شود.
set -e
CERT_DIR="$(dirname "$0")/certs"
mkdir -p "$CERT_DIR"
openssl req -x509 -nodes -newkey rsa:2048 \
  -keyout "$CERT_DIR/server.key" \
  -out "$CERT_DIR/server.crt" \
  -days 365 \
  -subj "/CN=khalij-pos.local/O=Khalij Holding/C=IR"
echo "گواهی تولید شد: $CERT_DIR/server.crt"
