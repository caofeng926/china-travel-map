# 中国旅游地图 (China Travel Map)

基于高德地图的全国旅游景点与美食地图。

## 功能

- ??? 高德地图展示，支持缩放拖拽
- ??? 5A/4A/3A 级景区标注（3,627个景点）
- ?? 特色美食推荐（8,324条，含店铺名和地址）
- ??? 国家级旅游休闲街区、度假区、世界遗产
- ?? 响应式设计，支持桌面和移动端
- ?? 当前位置定位与距离计算
- ?? 按名称/城市搜索

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
