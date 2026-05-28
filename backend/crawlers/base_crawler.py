"""Base crawler for provincial tourism websites"""
import sys, os, json, re, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from database import insert_attractions, insert_foods

class BaseCrawler:
    def __init__(self, province, base_url):
        self.province = province
        self.base_url = base_url
        self.attractions = []
        self.foods = []

    def crawl(self):
        raise NotImplementedError

    def save(self):
        if self.attractions:
            insert_attractions(self.attractions)
            print(f"  Inserted {len(self.attractions)} attractions for {self.province}")
        if self.foods:
            insert_foods(self.foods)
            print(f"  Inserted {len(self.foods)} foods for {self.province}")
        return len(self.attractions) + len(self.foods)

class ShaanxiCrawler(BaseCrawler):
    """Example: Shaanxi Provincial Tourism Website crawler"""
    def __init__(self):
        super().__init__("??", "http://whhlyt.shaanxi.gov.cn")

    def crawl(self):
        print(f"Crawling {self.province}...")
        # In real implementation, parse HTML pages from the tourism website
        # For now, return empty - data already seeded from pois.js
        return self

# Registry of all provincial crawlers
CRAWLERS = {
    "??": ShaanxiCrawler,
}

def run_all():
    total = 0
    for name, cls in CRAWLERS.items():
        try:
            c = cls()
            c.crawl()
            total += c.save()
        except Exception as e:
            print(f"  Error crawling {name}: {e}")
    print(f"Total: {total} items added")

if __name__ == "__main__":
    run_all()
