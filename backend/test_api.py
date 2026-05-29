"""Tests for China Travel Map backend modules."""
import os, sys, sqlite3, math, tempfile, unittest
sys.path.insert(0, os.path.dirname(__file__))
import database
_DB = os.path.join(tempfile.gettempdir(), "ctm_test.db")
def setUpModule():
    database.DB_PATH = _DB
    database.init_db()
def tearDownModule():
    if os.path.exists(_DB): os.remove(_DB)
class TestHaversine(unittest.TestCase):
    def test_known(self):
        d = database.haversine(39.9042, 116.4074, 31.2304, 121.4737)
        self.assertAlmostEqual(d, 1060, delta=50)
    def test_zero(self):
        d = database.haversine(30, 120, 30, 120)
        self.assertEqual(d, 0.0)
class TestDB(unittest.TestCase):
    def setUp(self):
        database.init_db()
        self.c = database.get_conn()
        self.c.execute("DELETE FROM attractions")
        self.c.execute("DELETE FROM foods")
        self.c.commit()
    def tearDown(self):
        self.c.close()
    def test_insert_attractions(self):
        database.insert_attractions([{"name":"T1","rating":"5A","city":"C","province":"P","lat":30,"lng":120}])
        r = database.search_pois(type_filter="scenic")
        self.assertEqual(r["total"], 1)
    def test_insert_foods(self):
        database.insert_foods([{"name":"F1","city":"C","province":"P","lat":30,"lng":120,"shop_name":"S1"}])
        r = database.search_pois(type_filter="food")
        self.assertEqual(r["total"], 1)
    def test_keyword(self):
        database.insert_attractions([{"name":"AAA","rating":"5A","city":"C","province":"P","lat":30,"lng":120},{"name":"BBB","rating":"5A","city":"C","province":"P","lat":40,"lng":110}])
        r = database.search_pois(keyword="AAA")
        self.assertEqual(r["total"], 1)
    def test_radius(self):
        database.insert_attractions([{"name":"P1","rating":"5A","city":"C","province":"P","lat":31.24,"lng":121.50}])
        r = database.search_pois(center_lat=31.23,center_lng=121.47,radius_km=50)
        self.assertEqual(r["total"], 1)
        r = database.search_pois(center_lat=31.23,center_lng=121.47,radius_km=1)
        self.assertEqual(r["total"], 0)
    def test_pagination(self):
        for i in range(5):
            database.insert_attractions([{"name":"POI","rating":"5A","city":"C","province":"P","lat":30,"lng":120}])
        r = database.search_pois(page=1, page_size=2)
        self.assertEqual(len(r["results"]), 2)
        self.assertEqual(r["total"], 5)
if __name__ == "__main__":
    unittest.main()