#!/usr/bin/env bash
# generate_certs.sh — create a sysmon CA and per-agent TLS certificates
#
# Run this ONCE on your sysmon management server:
#   chmod +x generate_certs.sh
#   ./generate_certs.sh agent1 agent2 agent3
#
# Output:
#   certs/
#     ca.crt            ← copy to /etc/sysmon/ca.crt on the Flask server
#     ca.key            ← keep private, never leave this machine
#     agent1.crt  }
#     agent1.key  }     ← copy these two files to each agent server
#     agent2.crt  }         e.g. /etc/sysmon/agent.crt + /etc/sysmon/agent.key
#     agent2.key  }
#     ...

set -euo pipefail

CERTS_DIR="./certs"
CA_DAYS=3650    # 10 years for the CA
CERT_DAYS=730   # 2 years for agent certs

mkdir -p "$CERTS_DIR"

# ─── Generate CA ──────────────────────────────────────────────────────────────
if [ ! -f "$CERTS_DIR/ca.key" ]; then
    echo "[CA] Generating CA key and self-signed certificate..."
    openssl genrsa -out "$CERTS_DIR/ca.key" 4096
    openssl req -new -x509 \
        -days  "$CA_DAYS" \
        -key   "$CERTS_DIR/ca.key" \
        -out   "$CERTS_DIR/ca.crt" \
        -subj  "/CN=sysmon-ca"
    echo "[CA] Done → $CERTS_DIR/ca.crt"
else
    echo "[CA] CA already exists — skipping generation."
fi

# ─── Generate per-agent certs ─────────────────────────────────────────────────
if [ $# -eq 0 ]; then
    echo ""
    echo "Usage: $0 <agent-name> [agent-name2] ..."
    echo "Example: $0 prod-web-01 prod-db-01 staging-01"
    echo ""
    echo "CA files are ready in $CERTS_DIR/"
    exit 0
fi

for AGENT in "$@"; do
    echo ""
    echo "[agent: $AGENT] Generating key + CSR + certificate..."

    openssl genrsa \
        -out "$CERTS_DIR/$AGENT.key" 2048

    openssl req -new \
        -key  "$CERTS_DIR/$AGENT.key" \
        -out  "$CERTS_DIR/$AGENT.csr" \
        -subj "/CN=$AGENT"

    openssl x509 -req \
        -days    "$CERT_DAYS" \
        -in      "$CERTS_DIR/$AGENT.csr" \
        -CA      "$CERTS_DIR/ca.crt" \
        -CAkey   "$CERTS_DIR/ca.key" \
        -CAcreateserial \
        -out     "$CERTS_DIR/$AGENT.crt"

    rm "$CERTS_DIR/$AGENT.csr"   # CSR not needed after signing
    echo "[agent: $AGENT] Done → $CERTS_DIR/$AGENT.crt + $CERTS_DIR/$AGENT.key"
done

echo ""
echo "─────────────────────────────────────────────────────"
echo " Next steps"
echo "─────────────────────────────────────────────────────"
echo ""
echo " 1. Copy ca.crt to the Flask server:"
echo "      sudo mkdir -p /etc/sysmon"
echo "      sudo cp $CERTS_DIR/ca.crt /etc/sysmon/ca.crt"
echo ""
echo " 2. For each agent server, copy its cert + key:"
echo "      scp $CERTS_DIR/<name>.crt root@<agent-ip>:/etc/sysmon/agent.crt"
echo "      scp $CERTS_DIR/<name>.key root@<agent-ip>:/etc/sysmon/agent.key"
echo ""
echo " 3. On each agent server, set env vars and restart:"
echo "      export AGENT_CERT=/etc/sysmon/agent.crt"
echo "      export AGENT_KEY=/etc/sysmon/agent.key"
echo "      (or add to the systemd service Environment= lines)"
echo ""
echo " 4. In config.py on the Flask server:"
echo "      AGENT_TLS     = True"
echo "      AGENT_CA_CERT = '/etc/sysmon/ca.crt'"
echo "      Then restart Flask."
echo "─────────────────────────────────────────────────────"