"""China Travel Map - Data Crawler (多源爬虫框架)
数据来源优先级:
  1. 文旅部数据服务 (lyfw.mct.gov.cn) - 全国景区官方登记
  2. 高德地图POI搜索 - 需Web服务API Key
  3. 各省文旅厅网站 - 各省特色景点/美食
  4. 公开数据集 - GitHub/Baidu等

用法:
  python -m backend.crawlers.province_crawlers
  python -c "from backend.crawlers.province_crawlers import *; run_all()"
"""
import sys, os, json, time, re, hashlib, urllib.request, ssl

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from database import insert_attractions, insert_foods, get_conn

# SSL context for HTTPS requests
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# 高德地图配置（需要Web服务API Key，当前Key仅限JS API使用）
AMAP_KEY = "6341f96e11ef424295330e635f174132"
AMAP_SECRET = "b8af7f12aafdc31fe67ee671a6871dd6"

class BaseCrawler:
    """爬虫基类"""
    def __init__(self, name):
        self.name = name
        self.attractions = []
        self.foods = []

    def crawl(self):
        raise NotImplementedError

    def save(self):
        if self.attractions:
            insert_attractions(self.attractions)
            print(f"  [{self.name}] +{len(self.attractions)} attractions")
        if self.foods:
            insert_foods(self.foods)
            print(f"  [{self.name}] +{len(self.foods)} foods")

    def get(self, url, headers=None, timeout=10):
        h = {"User-Agent": "Mozilla/5.0"}
        if headers:
            h.update(headers)
        try:
            req = urllib.request.Request(url, headers=h)
            r = urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX)
            return r.read().decode("utf-8", "replace")
        except Exception as e:
            print(f"  [{self.name}] HTTP Error: {e}")
            return None


class MCTCrawler(BaseCrawler):
    """文旅部数据服务爬虫 (lyfw.mct.gov.cn)
    
    可获取: 全国34省景区统计数据
    限制: WAF防护，具体景点明细API无法直接访问
    """
    def __init__(self):
        super().__init__("文旅部")
        self.base = "https://lyfw.mct.gov.cn"

    def crawl(self):
        print(f"  [{self.name}] 正在获取省级景区统计数据...")
        data = self.get(f"{self.base}/api/marker/province/list",
                       headers={"Accept": "application/json"})
        if not data:
            return
        import json
        try:
            prov_data = json.loads(data)
            provinces = prov_data.get("data", [])
            print(f"  [{self.name}] 获取到 {len(provinces)} 个省份数据")
            for p in provinces:
                print(f"    {p['name']}: {p['count']}个景区")
        except Exception as e:
            print(f"  [{self.name}] 解析失败: {e}")


class AmapCrawler(BaseCrawler):
    """高德地图POI爬虫
    
    前置条件: 申请高德Web服务API Key
    限制: 当前Key (6341f96e...) 仅JS API可用
    """
    def __init__(self):
        super().__init__("高德POI")

    def crawl(self):
        print(f"  [{self.name}] 需要高德Web服务API Key")
        print(f"  [{self.name}] 当前Key类型: JS API (不支持REST接口)")
        print(f"  [{self.name}] 待申请: https://console.amap.com/dev/key/app")


class ManualCrawler(BaseCrawler):
    """手动数据补充爬虫
    从已有的5A/4A清单中提取周边省份景区的坐标和描述
    """
    def __init__(self):
        super().__init__("数据补充")

    def crawl(self):
        print(f"  [{self.name}] 检查现有数据分布...")
        conn = get_conn()
        rows = conn.execute("SELECT province, COUNT(*) FROM attractions GROUP BY province ORDER BY COUNT(*) DESC").fetchall()
        for r in rows:
            print(f"    {r['province']}: {r[1]}个景点")
        conn.close()
        print(f"  [{self.name}] 总计: {sum(r[1] for r in rows)}个景点")


# 爬虫注册表
CRAWLERS = [
    MCTCrawler,
    AmapCrawler,
    ManualCrawler,
]

def run_all():
    """运行所有爬虫"""
    total_atts = 0
    total_foods = 0
    for cls in CRAWLERS:
        try:
            c = cls()
            c.crawl()
            c.save()
            total_atts += len(c.attractions)
            total_foods += len(c.foods)
        except Exception as e:
            print(f"  Error in {cls.__name__}: {e}")
    print(f"\n爬取完成: +{total_atts} attractions, +{total_foods} foods")

def stats():
    """打印数据统计"""
    conn = get_conn()
    atts = conn.execute("SELECT COUNT(*) FROM attractions").fetchone()[0]
    foods = conn.execute("SELECT COUNT(*) FROM foods").fetchone()[0]
    print(f"\n数据库统计:")
    print(f"  景点: {atts}")
    print(f"  美食: {foods}")
    print(f"  总计: {atts + foods}")
    print(f"\n按等级分布:")
    rows = conn.execute("SELECT rating, COUNT(*) FROM attractions GROUP BY rating ORDER BY COUNT(*) DESC").fetchall()
    for r in rows:
        print(f"  {r['rating'] or '未评级'}: {r[1]}")
    conn.close()

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        stats()
    else:
        run_all()
