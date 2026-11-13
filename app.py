from flask import Flask, render_template, request, jsonify
import re
import unicodedata
import os
import time
import threading
from collections import defaultdict, deque

import requests

from dtv_catalog import catalog, DTV_BASE

app = Flask(__name__)

CPS_API = "https://api.cellphones.com.vn/graphql-dashboard/graphql/query"
COMPANY_ID = 3759

QUERY = """
query old_trade_list_v2($newProduct: NewProductInput) {
  trade_products_list_v2(
    productName: "%s"
    type: "old"
    companyId: %d
    memberLevel: ""
    customerPhone: ""
    newProduct: $newProduct
  )
}
"""

REPAIR_TYPES = [
    {"key":"battery","label":"Pin","url":"/thay-pin","support_rate":0.30,"max_support":None,"required":["thay pin","pisen","dung lượng chuẩn"]},
    {"key":"screen","label":"Màn hình","url":"/thay-man-hinh","support_rate":0.15,"max_support":500000,"required":["thay màn hình","gena","loại pro"]},
    {"key":"glass","label":"Kính","url":"/thay-ep-kinh","support_rate":0.15,"max_support":500000,"required":[]},
    {"key":"touch","label":"Kính cảm ứng","url":"/thay-kinh-cam-ung","support_rate":0.15,"max_support":500000,"required":[]},
    {"key":"housing","label":"Vỏ","url":"/thay-vo","support_rate":0.0,"max_support":None,"required":[]},
    {"key":"back_glass","label":"Kính lưng","url":"/thay-kinh-lung","support_rate":0.30,"max_support":None,"required":[]},
    {"key":"camera_front","label":"Camera trước","url":"/thay-camera-truoc/thay-camera-truoc-dien-thoai-iphone","support_rate":0.30,"max_support":None,"required":[]},
    {"key":"camera_back","label":"Camera sau","url":"/thay-camera-sau/thay-camera-sau-dien-thoai-iphone","support_rate":0.30,"max_support":None,"required":[]},
    {"key":"speaker_out","label":"Loa ngoài","url":"/thay-loa-ngoai","support_rate":0.30,"max_support":None,"required":[]},
    {"key":"speaker_in","label":"Loa trong","url":"/thay-loa-trong","support_rate":0.30,"max_support":None,"required":[]},
    {"key":"charging","label":"Chân sạc / cáp sạc","url":"/thay-cap-sac","support_rate":0.30,"max_support":None,"required":[]},
    {"key":"vibration","label":"Rung","url":"/thay-rung","support_rate":0.30,"max_support":None,"required":[]},
    {"key":"microphone","label":"Micro","url":"/thay-mic","support_rate":0.30,"max_support":None,"required":[]},
]

def esc_graphql(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")

def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFD", str(value or ""))
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = value.lower()
    value = re.sub(r"[^a-z0-9+]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def model_tokens(product_name: str):
    text = normalize_text(product_name)
    drop = {"apple","samsung","xiaomi","oppo","vivo","realme","honor","huawei"}
    out = []
    for token in text.split():
        if token in drop or token in {"ram","rom"}:
            continue
        if re.fullmatch(r"\d+(gb|tb)", token):
            continue
        out.append(token)
    return out


def iphone_model_signature(text: str):
    """
    Doc doi + bien the iPhone ngay sau chu "iPhone" de khong nham chu Pro trong ten linh kien.
    iPhone 16 -> ("16", "", "base"); iPhone 16 Pro Max -> ("16", "", "pro max");
    iPhone 16e -> ("16e", "", "base"); iPhone Air -> ("air", "", "base");
    iPhone XS Max -> ("xs", "", "max"); iPhone SE 2022 -> ("se", "2022", "base")
    """
    nt = normalize_text(text)
    m = re.search(
        r"\biphone\s+(\d{1,2}[es]?|xs|xr|x|se|air)\b(?:\s+(20\d\d))?(?:\s+(pro max|pro|plus|max|mini)\b)?",
        nt,
    )
    if not m:
        return None
    return (m.group(1), m.group(2) or "", m.group(3) or "base")

def common_android_signature(text: str):
    nt = normalize_text(text)

    # Samsung S/A/Note: giữ đời + biến thể quan trọng.
    m = re.search(r"\b(?:galaxy\s+)?(s|a|note)\s*(\d{1,3})(?:\s*(ultra|plus|fe|pro|max))?\b", nt)
    if m:
        return ("samsung", m.group(1) + m.group(2), m.group(3) or "base")

    # Fold / Flip.
    m = re.search(r"\b(?:galaxy\s+)?z\s*(fold|flip)\s*(\d{1,2})\b", nt)
    if m:
        return ("samsung", "z " + m.group(1), m.group(2))

    # Pixel.
    m = re.search(r"\bpixel\s+(\d{1,2})(?:\s+(pro|pro xl|xl|a))?\b", nt)
    if m:
        return ("pixel", m.group(1), m.group(2) or "base")

    return None

def housing_model_matches(candidate_text: str, product_name: str):
    target = iphone_model_signature(product_name)
    candidate = iphone_model_signature(candidate_text)

    # iPhone: khớp chính xác đời + biến thể.
    if target:
        return candidate is not None and candidate == target

    # Một số dòng Android phổ biến: tránh nhầm Ultra/Plus/FE/Fold/Flip.
    android_target = common_android_signature(product_name)
    if android_target:
        android_candidate = common_android_signature(candidate_text)
        return android_candidate is not None and android_candidate == android_target

    # Fallback cho model khác: vẫn yêu cầu đủ token model.
    words = set(normalize_text(candidate_text).split())
    return all(token in words for token in model_tokens(product_name))

def deduction_for(price: int, support_rate: float, max_support):
    support = round(price * support_rate)
    if max_support is not None:
        support = min(support, max_support)
    return max(0, price - support), support


# ---------------------------------------------------------------------------
#  Gia sua chua Dien Thoai Vui: lay tu catalog API (dtv_catalog.py), tu cap nhat nen
# ---------------------------------------------------------------------------
def _price_key(item):
    return (item["price"], item["product_id"] or 0)


# Moi lan tai gia: tinh san ten khong dau + doi may cho tung dich vu (khong lam lai moi lan tra)
_FEATURES = {}          # key -> (version, [(item, ten_khong_dau, sig_iphone, sig_android, tu)])
_FEATURES_LOCK = threading.Lock()


def _features(key: str):
    items = catalog.items(key)
    ver = catalog.version(key)
    cached = _FEATURES.get(key)
    if cached and cached[0] == ver:
        return cached[1]
    feats = []
    for it in items:
        nt = normalize_text(it["name"])
        feats.append((it, nt, iphone_model_signature(it["name"]),
                      common_android_signature(it["name"]), set(nt.split())))
    with _FEATURES_LOCK:
        _FEATURES[key] = (ver, feats)
    return feats


def _model_rows(key: str, product_name: str):
    """Cac dich vu dung doi may (cung logic voi housing_model_matches, nhung dung du lieu tinh san)."""
    t_iphone = iphone_model_signature(product_name)
    t_android = None if t_iphone else common_android_signature(product_name)
    tokens = None if (t_iphone or t_android) else model_tokens(product_name)
    out = []
    for it, _nt, sig_i, sig_a, words in _features(key):
        if t_iphone:
            ok = sig_i == t_iphone
        elif t_android:
            ok = sig_a == t_android
        else:
            ok = all(t in words for t in tokens)
        if ok:
            out.append(it)
    return out


def _pick_service(key: str, product_name: str):
    """Chon dung dich vu theo rule cua shop. Tra ve (item, ghi_chu)."""
    rows = _model_rows(key, product_name)
    if not rows:
        return None, ""

    def n(it):
        return normalize_text(it["name"])

    if key == "screen":
        pool = [it for it in rows
                if ("gena" in n(it) or "gen a" in n(it))
                and re.search(r"\bloai pro\b", n(it)) and "loai ultra" not in n(it)]
        return (min(pool, key=_price_key), "GENA") if pool else (None, "")

    if key == "battery":
        # Pisen dung luong chuan -> GENA dung luong chuan -> VMAS (bo loai sieu cao)
        for brand, need_std in (("pisen", True), ("gena", True), ("vmas", False)):
            pool = [it for it in rows
                    if brand in n(it) and "sieu cao" not in n(it)
                    and (not need_std or "dung luong chuan" in n(it))]
            if pool:
                return min(pool, key=_price_key), {"pisen": "Pisen", "gena": "GENA", "vmas": "VMAS"}[brand]
        return None, ""

    if key in ("camera_front", "camera_back"):
        pool = [it for it in rows
                if ("gena" in n(it) or "gen a" in n(it))
                and "giu face id" not in n(it) and "kinh camera" not in n(it) and "rua" not in n(it)]
        return (min(pool, key=_price_key), "GENA") if pool else (None, "")

    # Danh muc DTV co lan dich vu khac (vd. "chan sac" co ca "cap sac khong day NFC",
    # "ep kinh" co ca "kinh lien film") -> uu tien dung loai, roi moi lay re nhat.
    prefer = SERVICE_PREFER.get(key)
    if prefer:
        include, exclude = prefer
        pool = [it for it in rows
                if any(p in n(it) for p in include) and not any(x in n(it) for x in exclude)]
        if pool:
            rows = pool
    return min(rows, key=_price_key), ""


# key -> (cum tu uu tien, cum tu loai tru)  [da bo dau, chu thuong]
SERVICE_PREFER = {
    "glass": (["ep kinh"], []),
    "touch": (["kinh cam ung"], []),
    "charging": (["chan sac", "cap sac"], ["khong day", "nfc"]),
    "speaker_in": (["thay loa trong"], ["day noi"]),
    "speaker_out": (["loa ngoai"], []),
    "back_glass": (["kinh lung", "nap lung"], []),
    "housing": (["vo"], []),
    "vibration": (["rung"], []),
}


def _fetch_repair_type_uncached(product_name: str, key: str):
    cfg = next((x for x in REPAIR_TYPES if x["key"] == key), None)
    if not cfg:
        return None

    source_page = DTV_BASE + cfg["url"]
    item, brand = _pick_service(key, product_name)
    if not item:
        return {
            "key": key, "label": cfg["label"], "available": False,
            "support_rate": cfg["support_rate"], "max_support": cfg["max_support"],
            "source_page": source_page,
        }

    price = item["price"]
    deduction, support = deduction_for(price, cfg["support_rate"], cfg["max_support"])
    out = {
        "key": key, "label": cfg["label"], "available": True,
        "service_name": item["name"], "repair_price": price,
        "support_rate": cfg["support_rate"], "support_amount": support,
        "max_support": cfg["max_support"], "deduction": deduction,
        "source_url": DTV_BASE + "/" + item["url_path"].lstrip("/") if item["url_path"] else source_page,
        "source_page": source_page,
        "dtv_product_id": item["product_id"],
        "dtv_sku": item["sku"],
    }
    if key == "battery":
        out["battery_brand"] = brand
    return out


_RESULT_CACHE = {}      # ten may -> (version, ket_qua) ; xoa khi gia DTV duoc tai lai


def fetch_repair_type(product_name: str, key: str):
    ver = catalog.version(key)
    ck = (product_name.lower(), key)
    hit = _RESULT_CACHE.get(ck)
    if hit and hit[0] == ver and ver:
        return hit[1]
    res = _fetch_repair_type_uncached(product_name, key)
    if ver:
        if len(_RESULT_CACHE) > 5000:
            _RESULT_CACHE.clear()
        _RESULT_CACHE[ck] = (ver, res)
    return res


# Tai bang gia DTV ngay khi khoi dong va tu cap nhat dinh ky (DTV_REFRESH_MINUTES, mac dinh 30).
if os.environ.get("DTV_DISABLE_BACKGROUND") != "1":
    catalog.start_background()


_RATE_LOCK = threading.Lock()
_RATE_BUCKETS = defaultdict(deque)

def client_ip():
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return forwarded or request.remote_addr or "unknown"

def rate_limited(scope: str, limit: int, window_seconds: int = 60):
    now = time.time()
    key = (scope, client_ip())
    with _RATE_LOCK:
        q = _RATE_BUCKETS[key]
        cutoff = now - window_seconds
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= limit:
            return True
        q.append(now)
        return False

@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cache-Control"] = "no-store" if request.path.startswith("/api/") else "no-cache"
    return response

@app.get("/")
def home():
    return render_template("index.html")

@app.get("/health")
def health():
    return jsonify({"ok": True})

@app.get("/api/dtv-status")
def dtv_status():
    """Xem bang gia DTV da tai duoc bao nhieu dong, luc nao, co loi khong."""
    return jsonify(catalog.status())

@app.get("/api/search")
def search():
    if rate_limited("search", 40):
        return jsonify({"products": [], "error": "Bạn thao tác quá nhanh. Vui lòng thử lại sau ít phút."}), 429

    keyword = (request.args.get("q") or "").strip()
    if len(keyword) < 2:
        return jsonify({"products": [], "message": "Nhập ít nhất 2 ký tự."})
    if len(keyword) > 100:
        return jsonify({"products": [], "error": "Từ khóa quá dài."}), 400

    payload = {"query": QUERY % (esc_graphql(keyword), COMPANY_ID), "variables": {}}
    headers = {
        "Accept": "*/*",
        "Content-Type": "application/json",
        "X-Client-Type": "web",
        "Origin": "https://cellphones.com.vn",
        "Referer": "https://cellphones.com.vn/",
        "User-Agent": "Mozilla/5.0"
    }

    try:
        r = requests.post(CPS_API, json=payload, headers=headers, timeout=15)
        r.raise_for_status()
        raw = r.json()
        node = ((raw.get("data") or {}).get("trade_products_list_v2") or {})
        products = node.get("products") or []

        cleaned = []
        for p in products[:30]:
            cleaned.append({
                "brand": p.get("brand"),
                "name": p.get("name"),
                "web_id": p.get("web_id"),
                "default_id": p.get("default_id"),
                "img": p.get("img"),
                "just_activated": p.get("just_activated") or 0,
                "thu_loai_1": p.get("thu_loai_1") or 0,
                "thu_loai_2": p.get("thu_loai_2") or 0,
                "thu_loai_3": p.get("thu_loai_3") or 0,
                "thu_loai_4": p.get("thu_loai_4") or 0,
                "tro_gia": p.get("tro_gia") or 0
            })

        return jsonify({"products": cleaned, "count": len(cleaned), "note": node.get("trade_in_note") or ""})
    except requests.RequestException:
        app.logger.exception("CellphoneS API request failed")
        return jsonify({"error":"Không kết nối được API CellphoneS.","products":[]}), 502
    except Exception:
        app.logger.exception("CellphoneS API response error")
        return jsonify({"error":"API trả dữ liệu không đúng định dạng.","products":[]}), 500

@app.get("/api/repair-prices")
def repair_prices():
    if rate_limited("repair", 90):
        return jsonify({"items": [], "error": "Bạn thao tác quá nhanh. Vui lòng thử lại sau ít phút."}), 429

    product_name = (request.args.get("product_name") or "").strip()
    if not product_name:
        return jsonify({"items": [], "error": "Thiếu tên sản phẩm."}), 400
    if len(product_name) > 120:
        return jsonify({"items": [], "error": "Tên sản phẩm quá dài."}), 400

    # Lan dau sau khi khoi dong: cho bang gia DTV toi da ~12 giay (khong vuot timeout gunicorn)
    catalog.wait_ready(timeout=12)

    results = {}
    for cfg in REPAIR_TYPES:
        key = cfg["key"]
        try:
            results[key] = fetch_repair_type(product_name, key)
        except Exception:
            app.logger.exception("Repair lookup failed for %s / %s", product_name, key)
            results[key] = {
                "key":key,"label":cfg["label"],"available":False,
                "support_rate":cfg["support_rate"],"max_support":cfg["max_support"]
            }

    ordered = [results.get(cfg["key"]) for cfg in REPAIR_TYPES]
    warming = not catalog.all_ready()
    return jsonify({
        "product_name":product_name,
        "region":"Hà Nội",
        "warming": warming,
        "items":ordered,
        "source":"Điện Thoại Vui",
        "fetched_at": catalog.fetched_at() or int(time.time())
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
