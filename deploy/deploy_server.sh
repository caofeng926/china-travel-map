#!/bin/bash
# China Travel Map - Server Deploy Script
set -e
echo "=== China Travel Map Deploy ==="

PROJECT_DIR="/root/china-travel-map"
if [ -d "$PROJECT_DIR" ]; then
    cd "$PROJECT_DIR"
    git pull
else
    git clone https://github.com/caofeng926/china-travel-map.git "$PROJECT_DIR"
    cd "$PROJECT_DIR"
fi

cd backend
pip3 install requests 2>/dev/null || true
python3 -c "from database import init_db; init_db(); print('DB OK')"

pkill -f "python.*server.py" 2>/dev/null || true
sleep 1
nohup python3 server.py > /tmp/travel.log 2>&1 &
sleep 2

if curl -s http://localhost:8765/api/health | grep -q "ok"; then
    echo "Deploy OK - http://localhost:8765"
else
    echo "FAILED"
    cat /tmp/travel.log
fi