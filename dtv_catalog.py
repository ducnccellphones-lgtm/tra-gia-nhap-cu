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
PROVINCE_ID = int(os.environ.get("DTV_PROVINCE_ID", "24"))
REFRESH_SECONDS = int(os.environ.get("DTV_REFRESH_MINUTES", "5")) * 60
PAGE_SIZE = 30
PAGE_DELAY = 0.35
MAX_PARALLEL = 4
RETRY_FAILED_SECONDS = 60

CATEGORY_IDS = {
    "battery": 380,
    "screen": 341,
    "glass": 277,
    "touch": 297,
    "housing": 400,
    "back_glass": 412,
    "camera_front": 235,
    "camera_back": 225,
    "speaker_out": 324,
    "speaker_in": 332,
    "charging": 259,
    "vibration": 393,
    "microphone": 359,
}

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": DTV_BASE,
    "Referer": DTV_BASE + "/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
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
            raise RuntimeError(f"DTV API error: {data.get('errors')}")
        except Exception as exc:
            last = exc
            time.sleep(2 * (attempt + 1))
    raise last


def _effective_price(price, special):
    price = int(price or 0)
    special = int(special or 0)
    return special if 0 < special < price or (special > 0 and price <= 0) else price


def _parse_batch(batch):
    out = []
    for item in batch:
        general = item.get("general") or {}
        filterable = item.get("filterable") or {}
        price = _effective_price(filterable.get("price"), filterable.get("special_price"))
        if price <= 0:
            continue
        out.append({
            "product_id": general.get("product_id"),
            "name": " ".join(str(general.get("name") or "").split()),
            "url_path": general.get("url_path") or "",
            "sku": general.get("sku") or "",
            "price": price,
            "stock": filterable.get("stock"),
        })
    return out


def _fetch_page(category_id, page):
    time.sleep(PAGE_DELAY)
    return _post(QUERY % (category_id, PROVINCE_ID, page, PAGE_SIZE))["products"]


def fetch_category(category_id):
    first = _fetch_page(category_id, 1)
    total = int(first.get("total") or 0)
    items = _parse_batch(first.get("data") or [])
    pages = range(2, (total + PAGE_SIZE - 1) // PAGE_SIZE + 1)
    if pages:
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as executor:
            for node in executor.map(lambda pg: _fetch_page(category_id, pg), pages):
                items.extend(_parse_batch(node.get("data") or []))

    seen = set()
    unique = []
    for item in items:
        pid = item["product_id"]
        if pid not in seen:
            seen.add(pid)
            unique.append(item)
    return unique


class Catalog:
    def __init__(self):
        self._data = {}
        self._fetched_at = {}
        self._errors = {}
        self._lock = threading.Lock()
        self._key_locks = {key: threading.Lock() for key in CATEGORY_IDS}
        self._bg_started = False

    def refresh(self, key):
        lock = self._key_locks[key]
        if not lock.acquire(blocking=False):
            with lock:
                return

        try:
            items = fetch_category(CATEGORY_IDS[key])
            old = self._data.get(key) or []
            if old and len(items) < 0.7 * len(old):
                raise RuntimeError(
                    f"catalog too small: {len(items)}/{len(old)}, keeping previous data"
                )

            with self._lock:
                self._data[key] = items
                self._fetched_at[key] = time.time()
                self._errors.pop(key, None)
            log.info("DTV %s: %d services", key, len(items))
        except Exception as exc:
            log.warning("DTV refresh %s failed: %s", key, exc)
            with self._lock:
                self._errors[key] = str(exc)
        finally:
            lock.release()

    def refresh_all(self):
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
                except Exception:
                    log.exception("DTV refresh_all failed")
                time.sleep(RETRY_FAILED_SECONDS if not self.all_ready() else REFRESH_SECONDS)

        threading.Thread(target=loop, name="dtv-refresh", daemon=True).start()

    def items(self, key):
        if key not in CATEGORY_IDS:
            return []

        fetched_at = self._fetched_at.get(key, 0)
        if self._data.get(key) and time.time() - fetched_at > REFRESH_SECONDS * 2:
            threading.Thread(target=self.refresh, args=(key,), daemon=True).start()
        return self._data.get(key) or []

    def wait_ready(self, timeout=12):
        missing = [key for key in CATEGORY_IDS if not self._data.get(key)]
        if not missing:
            return True

        deadline = time.time() + timeout
        threads = [
            threading.Thread(target=self.refresh, args=(key,), daemon=True)
            for key in missing
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(max(0, deadline - time.time()))
        return self.all_ready()

    def version(self, key=None):
        if key:
            return self._fetched_at.get(key, 0)
        return tuple(self._fetched_at.get(k, 0) for k in CATEGORY_IDS)

    def all_ready(self):
        return all(self._data.get(key) for key in CATEGORY_IDS)

    def fetched_at(self, keys=None):
        keys = keys or CATEGORY_IDS
        values = [self._fetched_at[k] for k in keys if k in self._fetched_at]
        return int(min(values)) if values else 0

    def status(self):
        return {
            key: {
                "count": len(self._data.get(key) or []),
                "fetched_at": int(self._fetched_at.get(key, 0)),
                "error": self._errors.get(key),
            }
            for key in CATEGORY_IDS
        }


catalog = Catalog()
