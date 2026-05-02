#!/bin/bash
# ──────────────────────────────────────────────────────────────
# SSL Certificate Setup for rai-k63.me
# Run this script on the VPS AFTER DNS propagation is complete
# ──────────────────────────────────────────────────────────────
set -euo pipefail

DOMAIN="rai-k63.me"
EMAIL="${1:-admin@${DOMAIN}}"
COMPOSE_FILE="docker-compose.prod.yml"

echo "╔══════════════════════════════════════════════╗"
echo "║  SSL Setup for ${DOMAIN}                     ║"
echo "╚══════════════════════════════════════════════╝"

# Step 1: Verify DNS points to this server
echo ""
echo "▶ Step 1: Verifying DNS resolution..."
RESOLVED_IP=$(dig +short "${DOMAIN}" @8.8.8.8 2>/dev/null || echo "")
SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || echo "unknown")

if [ -z "${RESOLVED_IP}" ]; then
    echo "  ✗ DNS for ${DOMAIN} not resolving yet."
    echo "    Set A record → ${SERVER_IP} and wait for propagation."
    exit 1
fi

echo "  Domain resolves to: ${RESOLVED_IP}"
echo "  This server's IP:   ${SERVER_IP}"

if [ "${RESOLVED_IP}" != "${SERVER_IP}" ]; then
    echo "  ⚠ WARNING: DNS points to a different IP!"
    echo "    Certbot may fail. Continue anyway? [y/N]"
    read -r confirm
    [ "${confirm}" != "y" ] && exit 1
fi

# Step 2: Ensure nginx is running (HTTP mode)
echo ""
echo "▶ Step 2: Ensuring nginx is running..."
docker compose -f "${COMPOSE_FILE}" up -d nginx
sleep 3

# Step 3: Request certificate via webroot
echo ""
echo "▶ Step 3: Requesting SSL certificate..."
docker compose -f "${COMPOSE_FILE}" run --rm certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "${EMAIL}" \
    --agree-tos \
    --no-eff-email \
    -d "${DOMAIN}" \
    -d "www.${DOMAIN}"

# Step 4: Enable HTTPS in nginx config
echo ""
echo "▶ Step 4: Enabling HTTPS..."
echo ""
echo "  ✓ Certificate obtained!"
echo ""
echo "  Now you need to edit nginx/conf.d/default.conf:"
echo "  1. Uncomment the 'return 301' redirect in the HTTP block"
echo "  2. Uncomment the entire HTTPS server block (Phase 2)"
echo ""
echo "  Then reload nginx:"
echo "    docker compose -f ${COMPOSE_FILE} exec nginx nginx -s reload"
echo ""

# Step 5: Set up auto-renewal cron
echo "▶ Step 5: Setting up auto-renewal..."
CRON_CMD="0 3 * * 1 cd $(pwd) && docker compose -f ${COMPOSE_FILE} run --rm certbot renew --quiet && docker compose -f ${COMPOSE_FILE} exec nginx nginx -s reload"

if ! crontab -l 2>/dev/null | grep -q "certbot renew"; then
    (crontab -l 2>/dev/null; echo "${CRON_CMD}") | crontab -
    echo "  ✓ Auto-renewal cron installed (every Monday 3:00 AM)"
else
    echo "  ✓ Auto-renewal cron already exists"
fi

echo ""
echo "══════════════════════════════════════════════"
echo "  Done! Next steps:"
echo "  1. Edit nginx/conf.d/default.conf (enable HTTPS)"
echo "  2. Update .env: NEXT_PUBLIC_API_URL=https://${DOMAIN}"
echo "  3. Rebuild client: docker compose -f ${COMPOSE_FILE} up -d --force-recreate client"
echo "  4. Reload nginx: docker compose -f ${COMPOSE_FILE} exec nginx nginx -s reload"
echo "══════════════════════════════════════════════"
