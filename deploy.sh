#!/bin/bash
# 中国旅游地图 - 腾讯云轻量服务器一键部署脚本
# 在服务器上执行: bash deploy.sh

set -e

echo "=== 中国旅游地图 部署开始 ==="

# 1. 安装依赖
apt-get update
apt-get install -y python3 git

# 2. 克隆项目
cd /opt
if [ -d china-travel-map ]; then
  cd china-travel-map && git pull
else
  git clone https://github.com/caofeng926/china-travel-map.git
  cd china-travel-map
fi

# 3. 防火墙放行端口
ufw allow 8765/tcp 2>/dev/null || true

# 4. 启动服务（使用nohup后台运行）
pkill -f "python3.*server.py" 2>/dev/null || true
nohup python3 backend/server.py > server.log 2>&1 &

echo "=== 部署完成 ==="
echo "访问地址: http://$(curl -s ifconfig.me):8765"
echo "日志查看: tail -f /opt/china-travel-map/server.log"
