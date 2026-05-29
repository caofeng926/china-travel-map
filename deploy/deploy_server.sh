#!/bin/bash
# China Travel Map - Production Deploy Script (Ubuntu/Debian)
set -euo pipefail

echo "=== China Travel Map Deploy ==="

PROJECT_DIR="/opt/china-travel-map"
DOMAIN="${DOMAIN:-your-domain.com}"  # Set DOMAIN env var or edit this

# --- 1. Pull latest code ---
if [ -d "$PROJECT_DIR" ]; then
    cd "$PROJECT_DIR"
    git pull
else
    git clone https://github.com/caofeng926/china-travel-map.git "$PROJECT_DIR"
    cd "$PROJECT_DIR"
fi

# --- 2. Create .env if not exists ---
if [ ! -f .env ]; then
    cat > .env <<- EOF
# China Travel Map - Production Config
# Generate a random token: openssl rand -hex 32
SEED_TOKEN=change-me-to-a-random-string
ALLOWED_ORIGINS=https://$DOMAIN
EOF
    echo "Created .env - PLEASE EDIT IT: nano .env"
fi

# --- 3. Export env vars ---
set -a
source .env
set +a

# Make sure AMAP_KEY is set
if [ -z "${AMAP_KEY:-}" ]; then
    echo "ERROR: AMAP_KEY not set! Export it or add to .env"
    echo "  export AMAP_KEY=your_amap_webservice_key"
    exit 1
fi

# --- 4. Kill old server ---
pkill -f "python3.*server.py" 2>/dev/null || true
sleep 1

# --- 5. Start backend ---
cd backend
nohup python3 server.py > ../server.log 2>&1 &
echo "Backend started (PID: $!)"

# --- 6. Verify it's running ---
sleep 2
if curl -s http://127.0.0.1:8765/api/health > /dev/null 2>&1; then
    echo "Backend health check: OK"
else
    echo "WARNING: Backend health check failed, check server.log"
fi

# --- 7. Setup Nginx (if not already) ---
if [ ! -f /etc/nginx/sites-enabled/china-travel-map ]; then
    echo ""
    echo "=== Nginx Setup Required ==="
    echo "  sudo cp deploy/nginx.conf /etc/nginx/sites-available/china-travel-map"
    echo "  sudo ln -s /etc/nginx/sites-available/china-travel-map /etc/nginx/sites-enabled/"
    echo "  sudo nginx -t && sudo systemctl reload nginx"
    echo "  sudo certbot --nginx -d $DOMAIN"
fi

echo ""
echo "=== Deploy Complete ==="
echo "  Backend: http://127.0.0.1:8765"
echo "  Frontend (via Nginx): https://$DOMAIN"