# 中国旅游地图 (China Travel Map)

基于高德地图的全国旅游景点与美食地图。

## 功能

- 🗺️ 高德地图展示，支持缩放拖拽
- 🏔️ 5A/4A/3A 级景区标注（3,627个景点）
- 🍜 特色美食推荐（8,324条，含店铺名和地址）
- 🏛️ 国家级旅游休闲街区、度假区、世界遗产
- 📱 响应式设计，支持桌面和移动端
- 📍 **当前位置定位**：右下角 `📍` 按钮调用浏览器 `navigator.geolocation`，移动端冷启动放宽到 15s 并在 GPS 超时时自动降级到网络定位；非 HTTPS 或浏览器拒绝授权时自动回落到高德 `v3/ip` IP 定位（需配置 `AMAP_KEY`）。定位成功后会在地图上放置带脉冲动画的当前位置标记，后续每个 POI 信息窗里会自动计算并显示「📍 距您 X km」，「🚗 规划路线」也会以你的位置为起点。
- 🔍 按名称/城市搜索
- 🏷️ **多选筛选**：5A / 4A / 3A / 街区 / 世界 / 度假 / 美食 任意组合并集筛选，选中状态持久化到 `localStorage`；关键词搜索会先按多选结果收窄

## 快速开始

```bash
cd backend
python server.py
# 访问 http://localhost:8765
```

## 数据来源

- **景区**: 文旅部官方5A + 高德API爬取4A/3A
- **美食**: 高德API"老字号""特色美食""必吃"关键词，60城市

## 服务器部署

```bash
# Ubuntu/Debian 服务器
bash deploy.sh
```

或手动部署：

```bash
git clone https://github.com/caofeng926/china-travel-map.git
cd china-travel-map
python3 backend/server.py
# 访问 http://服务器IP:8765
```
