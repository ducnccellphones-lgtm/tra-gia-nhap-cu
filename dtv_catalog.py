"""
Lay bang gia sua chua Dien Thoai Vui truc tiep tu API GraphQL (khong doc HTML).

- Moi loai dich vu (pin, man hinh, ep kinh...) la mot danh muc tren DTV.
- Tai toan bo danh muc, giu trong bo nho, tu tai lai sau DTV_REFRESH_MINUTES phut
  (mac dinh 30) bang luong chay nen -> gia luon theo web.
- Neu lan tai moi loi / thieu du lieu bat thuong thi giu du lieu cu.
"""
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from requests.adapters import HTTPAdapter

log = logging.getLogger(__name__)

DTV_BASE = "https://dienthoaivui.com.vn"
DTV_API = "https://api.dienthoaivui.com.vn/graphql-dashboard/graphql/query"
PROVINCE_ID = int(os.environ.get("DTV_PROVINCE_ID", "24"))          # 24 = Ha Noi
REFRESH_SECONDS = int(os.environ.get("DTV_REFRESH_MINUTES", "30")) * 60
PAGE_SIZE = 30            # API tra toi da 30 san pham / trang
PAGE_DELAY = 0.35         # nghi giua cac trang de khong bi chan
MAX_PARALLEL = 4          # toi da so request dong thoi toi DTV (tranh loi DNS / bi chan)
RETRY_FAILED_SECONDS = 60 # danh muc loi -> thu lai sau 1 phut

# key dich vu -> id danh muc tren dienthoaivui.com.vn
CATEGORY_IDS = {
    "battery": 380,        # /thay-pin
    "screen": 341,         # /thay-man-hinh
    "glass": 277,          # /thay-ep-kinh
    "touch": 297,          # /thay-kinh-cam-ung
    "housing": 400,        # /thay-vo
    "back_glass": 412,     # /thay-kinh-lung
    "camera_front": 235,   # /thay-camera-truoc
    "camera_back": 225,    # /thay-camera-sau
    "speaker_out": 324,    # /thay-loa-ngoai
    "speaker_in": 332,     # /thay-loa-trong
    "charging": 259,       # /thay-chan-sac
    "vibration": 393,      # /thay-rung
    "microphone": 359,     # /thay-mic
}

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": DTV_BASE,
    "Referer": DTV_BASE + "/",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"),
}

QUERY = """query{ products(
  filter:{static:{categories:["%d"],is_out_of_business:false,is_parent:["true"],
          price:{from:1,to:100000000},province_id:%d},dynamic:{}},
  page:%d, size:%d, sort:[{product_id:asc}]){
  total data{ general{ product_id name url_path sku } filterable{ price special_price stock } } } }"""


_session = requests.Session()
_session.headers.update(HEADERS)
_session.mount("https://", HTTPAdapter(pool_connections=2, pool_maxsize=MAX_PARALLEL + 2))
_http_slots = threading.BoundedSemaphore(MAX_PARALLEL)


def _post(query, retries=4):
    last = None
    for attempt in range(retries):
        try:
            with _http_slots:
                r = _session.post(DTV_API, json={"query": query}, timeout=20)
            r.raise_for_status()
            data = r.json()
            if data.get("data"):
                return data["data"]
            raise RuntimeError(f"DTV API loi: {data.get('errors')}")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


def _effective_price(price, special):
    price = int(price or 0)
    special = int(special or 0)
    return special if 0 < special < price or (special > 0 and price <= 0) else price


def _parse_batch(batch):
    out = []
    for it in batch:
        g, f = it.get("general") or {}, it.get("filterable") or {}
        price = _effective_price(f.get("price"), f.get("special_price"))
        if price <= 0:
            continue
        out.append({
            "product_id": g.get("product_id"),
            "name": " ".join(str(g.get("name") or "").split()),
            "url_path": g.get("url_path") or "",
            "sku": g.get("sku") or "",
            "price": price,
            "stock": f.get("stock"),
        })
    return out


def _fetch_page(category_id, page):
    time.sleep(PAGE_DELAY)
    return _post(QUERY % (category_id, PROVINCE_ID, page, PAGE_SIZE))["products"]


def fetch_category(category_id):
    """Tai het 1 danh muc: trang 1 de biet tong so, cac trang sau tai song song (4 luong)."""
    first = _fetch_page(category_id, 1)
    total = int(first.get("total") or 0)
    items = _parse_batch(first.get("data") or [])
    pages = range(2, (total + PAGE_SIZE - 1) // PAGE_SIZE + 1)
    if pages:
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as ex:
            for node in ex.map(lambda pg: _fetch_page(category_id, pg), pages):
                items.extend(_parse_batch(node.get("data") or []))
    # bo trung (phong khi du lieu thay doi giua cac trang)
    seen, uniq = set(), []
    for it in items:
        if it["product_id"] not in seen:
            seen.add(it["product_id"])
            uniq.append(it)
    return uniq


class Catalog:
    def __init__(self):
        self._data = {}            # key -> list[item]
        self._fetched_at = {}      # key -> ts
        self._errors = {}          # key -> str
        self._lock = threading.Lock()
        self._key_locks = {k: threading.Lock() for k in CATEGORY_IDS}
        self._bg_started = False

    # ---- tai du lieu
    def refresh(self, key):
        lock = self._key_locks[key]
        if not lock.acquire(blocking=False):
            # dang co luong khac tai -> doi no xong
            with lock:
                return
        try:
            items = fetch_category(CATEGORY_IDS[key])
            old = self._data.get(key) or []
            if old and len(items) < 0.7 * len(old):
                raise RuntimeError(f"chi lay duoc {len(items)}/{len(old)} dong, giu du lieu cu")
            with self._lock:
                self._data[key] = items
                self._fetched_at[key] = time.time()
                self._errors.pop(key, None)
            log.info("DTV %s: %d dich vu", key, len(items))
        except Exception as e:  # noqa: BLE001
            log.warning("DTV refresh %s loi: %s", key, e)
            with self._lock:
                self._errors[key] = str(e)
        finally:
            lock.release()

    def refresh_all(self):
        # tai lan luot tung danh muc (moi danh muc da tai nhieu trang song song)
        for key in CATEGORY_IDS:
            self.refresh(key)

    def start_background(self):
        with self._lock:
            if self._bg_started:
                return
            self._bg_started = True

        def loop():
            while True:
                try:
                    self.refresh_all()
                except Exception:  # noqa: BLE001
                    log.exception("DTV refresh_all loi")
                # con danh muc chua tai duoc -> thu lai som
                time.sleep(RETRY_FAILED_SECONDS if not self.all_ready() else REFRESH_SECONDS)

        threading.Thread(target=loop, name="dtv-refresh", daemon=True).start()

    # ---- doc du lieu
    def items(self, key):
        """Danh sach dich vu cua key (khong cho). Du lieu cu qua lau -> tai lai o nen."""
        if key not in CATEGORY_IDS:
            return []
        if self._data.get(key) and time.time() - self._fetched_at.get(key, 0) > REFRESH_SECONDS * 2:
            threading.Thread(target=self.refresh, args=(key,), daemon=True).start()
        return self._data.get(key) or []

    def wait_ready(self, timeout=12):
        """Danh muc nao chua co du lieu thi tai ngay; cho tong cong toi da `timeout` giay."""
        missing = [k for k in CATEGORY_IDS if not self._data.get(k)]
        if not missing:
            return True
        deadline = time.time() + timeout
        threads = [threading.Thread(target=self.refresh, args=(k,), daemon=True) for k in missing]
        for t in threads:
            t.start()
        for t in threads:
            t.join(max(0, deadline - time.time()))
        return self.all_ready()

    def version(self, key=None):
        """Doi moi lan tai lai gia -> dung lam khoa cache."""
        if key:
            return self._fetched_at.get(key, 0)
        return tuple(self._fetched_at.get(k, 0) for k in CATEGORY_IDS)

    def all_ready(self):
        return all(self._data.get(k) for k in CATEGORY_IDS)

    def ready(self, key):
        return bool(self._data.get(key))

    def fetched_at(self, keys=None):
        ts = [self._fetched_at[k] for k in (keys or CATEGORY_IDS) if k in self._fetched_at]
        return int(min(ts)) if ts else 0

    def status(self):
        return {
            k: {
                "count": len(self._data.get(k) or []),
                "fetched_at": int(self._fetched_at.get(k, 0)),
                "error": self._errors.get(k),
            }
            for k in CATEGORY_IDS
        }


catalog = Catalog()
