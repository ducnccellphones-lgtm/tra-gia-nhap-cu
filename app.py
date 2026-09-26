from flask import Flask, render_template, request, jsonify
import re
import unicodedata
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

CPS_API = "https://api.cellphones.com.vn/graphql-dashboard/graphql/query"
COMPANY_ID = 3759
DTV_BASE = "https://dienthoaivui.com.vn"

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
    {"key":"camera","label":"Camera","url":"/thay-camera-dien-thoai","support_rate":0.30,"max_support":None,"required":[]},
    {"key":"speaker_out","label":"Loa ngoài","url":"/thay-loa-ngoai","support_rate":0.30,"max_support":None,"required":[]},
    {"key":"speaker_in","label":"Loa trong","url":"/thay-loa-trong","support_rate":0.30,"max_support":None,"required":[]},
    {"key":"charging","label":"Chân sạc / cáp sạc","url":"/thay-cap-sac","support_rate":0.30,"max_support":None,"required":[]},
    {"key":"vibration","label":"Rung","url":"/thay-rung","support_rate":0.30,"max_support":None,"required":[]},
    {"key":"microphone","label":"Micro","url":"/thay-cap-micro","support_rate":0.30,"max_support":None,"required":[]},
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

def money_values(text: str):
    raw = re.findall(r"(?<!\d)(\d{1,3}(?:[\.\,]\d{3})+)\s*₫", text)
    vals = []
    for value in raw:
        n = int(re.sub(r"[^0-9]", "", value))
        if n >= 100000:
            vals.append(n)
    return vals

def deduction_for(price: int, support_rate: float, max_support):
    support = round(price * support_rate)
    if max_support is not None:
        support = min(support, max_support)
    return max(0, price - support), support

def product_slug(product_name: str):
    text = normalize_text(product_name)
    text = re.sub(r"\b(apple|samsung|xiaomi|oppo|vivo|realme|honor|huawei)\b", "", text)
    text = re.sub(r"\b\d+(gb|tb)\b", "", text)
    text = re.sub(r"\s+", "-", text).strip("-")
    return text

def fetch_battery_direct(product_name: str, cfg):
    slug = product_slug(product_name)
    candidates = [
        f"{DTV_BASE}/thay-pin-{slug}-chinh-hang-pisen",
        f"{DTV_BASE}/thay-pin-{slug}-pisen",
        f"{DTV_BASE}/thay-pin-pisen-{slug}",
        f"{DTV_BASE}/thay-pin-{slug}",
    ]

    headers = {"User-Agent":"Mozilla/5.0","Accept-Language":"vi-VN,vi;q=0.9"}
    model = model_tokens(product_name)

    for direct_url in candidates:
        try:
            r = requests.get(direct_url, headers=headers, timeout=12, allow_redirects=True)
            if r.status_code != 200:
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            page_text = " ".join(soup.stripped_strings)
            title = soup.find("h1")
            title_text = " ".join(title.stripped_strings) if title else ""
            nt = normalize_text(title_text + " " + page_text[:7000])

            if not all(token in nt.split() for token in model):
                continue
            if "pisen" not in nt:
                continue

            match = re.search(r"Pisen(?!\s+siêu\s+cao)\s*([0-9\.\,]+)\s*₫", page_text, re.IGNORECASE)
            if not match:
                match = re.search(r"dung lượng chuẩn[^0-9]{0,80}([0-9\.\,]+)\s*₫", page_text, re.IGNORECASE)
            if not match:
                continue

            price = int(re.sub(r"[^0-9]", "", match.group(1)))
            if price < 100000:
                continue

            deduction, support = deduction_for(price, cfg["support_rate"], cfg["max_support"])
            return {
                "key":"battery",
                "label":cfg["label"],
                "available":True,
                "service_name":title_text or f"Thay pin {product_name} Pisen dung lượng chuẩn",
                "repair_price":price,
                "support_rate":cfg["support_rate"],
                "support_amount":support,
                "max_support":cfg["max_support"],
                "deduction":deduction,
                "source_url":r.url,
                "source_page":r.url
            }
        except Exception:
            continue

    return None

def fetch_screen_direct(product_name: str, cfg):
    slug = product_slug(product_name)
    direct_url = f"{DTV_BASE}/thay-man-hinh-{slug}-chinh-hang-gena-loai-pro"
    r = requests.get(
        direct_url,
        headers={"User-Agent":"Mozilla/5.0","Accept-Language":"vi-VN,vi;q=0.9"},
        timeout=12,
        allow_redirects=True
    )
    if r.status_code != 200:
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    page_text = " ".join(soup.stripped_strings)
    title = soup.find("h1")
    title_text = " ".join(title.stripped_strings) if title else ""

    nt = normalize_text(title_text + " " + page_text[:5000])
    model = model_tokens(product_name)
    if not all(token in nt.split() for token in model):
        return None
    if "gena" not in nt or "loai pro" not in nt:
        return None

    price = None

    # 1) Giá hiển thị trực tiếp cạnh GENA loại Pro.
    match = re.search(r"GENA\s+loại\s+pro[^0-9]{0,80}([0-9\.\,]+)\s*₫", page_text, re.IGNORECASE)
    if match:
        price = int(re.sub(r"[^0-9]", "", match.group(1)))

    # 2) Một số trang render giá bằng JavaScript: tìm trường giá trong dữ liệu gần GENA loại Pro.
    if not price:
        raw_flat = re.sub(r"\s+", " ", r.text)
        for m in re.finditer(r"GENA.{0,40}loại.{0,20}pro", raw_flat, re.IGNORECASE):
            window = raw_flat[max(0, m.start() - 2000):m.start() + 2000]
            pm = re.search(r'(?:"(?:final_price|special_price|price|finalPrice|salePrice)"|(?:final_price|special_price|price|finalPrice|salePrice))\s*[:=]\s*["\']?([0-9]{6,9})', window, re.IGNORECASE)
            if pm:
                candidate = int(pm.group(1))
                if 300000 <= candidate <= 30000000:
                    price = candidate
                    break

    # 3) Tìm theo mã SKU của chính trang sản phẩm.
    if not price:
        sku_match = re.search(r"\b\d+\.\d+\.\d+\.\d+\.\d+\b", page_text)
        if sku_match:
            raw_flat = re.sub(r"\s+", " ", r.text)
            sku_pos = raw_flat.find(sku_match.group(0))
            if sku_pos >= 0:
                window = raw_flat[max(0, sku_pos - 2500):sku_pos + 2500]
                pm = re.search(r'(?:"(?:final_price|special_price|price|finalPrice|salePrice)"|(?:final_price|special_price|price|finalPrice|salePrice))\s*[:=]\s*["\']?([0-9]{6,9})', window, re.IGNORECASE)
                if pm:
                    candidate = int(pm.group(1))
                    if 300000 <= candidate <= 30000000:
                        price = candidate

    # 4) Fallback: lấy giá trong bảng giá bài viết đúng model + GENA loại Pro.
    if not price:
        model_text = " ".join(model)
        pattern = r"Thay màn hình[^₫]{0,180}" + re.escape(model_text).replace(r"\ ", r"\s+") + r"[^₫]{0,180}GENA\s+loại\s+Pro[^0-9]{0,80}([0-9\.\,]+)\s*đ"
        tm = re.search(pattern, page_text, re.IGNORECASE)
        if tm:
            price = int(re.sub(r"[^0-9]", "", tm.group(1)))

    if not price or price < 100000:
        return None

    deduction, support = deduction_for(price, cfg["support_rate"], cfg["max_support"])
    return {
        "key":"screen",
        "label":cfg["label"],
        "available":True,
        "service_name":title_text or f"Thay màn hình {product_name} GENA loại Pro",
        "repair_price":price,
        "support_rate":cfg["support_rate"],
        "support_amount":support,
        "max_support":cfg["max_support"],
        "deduction":deduction,
        "source_url":r.url,
        "source_page":r.url
    }

@lru_cache(maxsize=256)
def fetch_repair_type(product_name: str, key: str):
    cfg = next((x for x in REPAIR_TYPES if x["key"] == key), None)
    if not cfg:
        return None

    if key == "battery":
        direct = fetch_battery_direct(product_name, cfg)
        if direct:
            return direct

    if key == "screen":
        direct = fetch_screen_direct(product_name, cfg)
        if direct:
            return direct

    url = DTV_BASE + cfg["url"]
    r = requests.get(url, headers={"User-Agent":"Mozilla/5.0","Accept-Language":"vi-VN,vi;q=0.9"}, timeout=12)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    model = model_tokens(product_name)
    candidates = []

    for a in soup.find_all("a"):
        text = " ".join(a.stripped_strings)
        if not text:
            continue
        nt = normalize_text(text)
        words = set(nt.split())
        if not all(token in words for token in model):
            continue
        if any(normalize_text(req) not in nt for req in cfg["required"]):
            continue
        prices = money_values(text)
        if not prices:
            continue
        price = prices[0]
        href = str(a.get("href") or "")
        source_url = href if href.startswith("http") else DTV_BASE + href
        candidates.append({"service_name":text[:260],"price":price,"source_url":source_url})

    if not candidates:
        return {
            "key":key,"label":cfg["label"],"available":False,
            "support_rate":cfg["support_rate"],"max_support":cfg["max_support"],
            "source_page":url
        }

    best = min(candidates, key=lambda x: x["price"])
    deduction, support = deduction_for(best["price"], cfg["support_rate"], cfg["max_support"])
    return {
        "key":key,"label":cfg["label"],"available":True,
        "service_name":best["service_name"],"repair_price":best["price"],
        "support_rate":cfg["support_rate"],"support_amount":support,
        "max_support":cfg["max_support"],"deduction":deduction,
        "source_url":best["source_url"],"source_page":url
    }

@app.get("/")
def home():
    return render_template("index.html")

@app.get("/health")
def health():
    return jsonify({"ok": True})

@app.get("/api/search")
def search():
    keyword = (request.args.get("q") or "").strip()
    if len(keyword) < 2:
        return jsonify({"products": [], "message": "Nhập ít nhất 2 ký tự."})

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
    except requests.RequestException as e:
        return jsonify({"error":"Không kết nối được API CellphoneS.","detail":str(e),"products":[]}), 502
    except Exception as e:
        return jsonify({"error":"API trả dữ liệu không đúng định dạng.","detail":str(e),"products":[]}), 500

@app.get("/api/repair-prices")
def repair_prices():
    product_name = (request.args.get("product_name") or "").strip()
    if not product_name:
        return jsonify({"items": [], "error": "Thiếu tên sản phẩm."}), 400

    results = {}
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(fetch_repair_type, product_name, cfg["key"]): cfg["key"] for cfg in REPAIR_TYPES}
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as e:
                cfg = next(x for x in REPAIR_TYPES if x["key"] == key)
                results[key] = {
                    "key":key,"label":cfg["label"],"available":False,
                    "support_rate":cfg["support_rate"],"max_support":cfg["max_support"],
                    "error":str(e)
                }

    ordered = [results.get(cfg["key"]) for cfg in REPAIR_TYPES]
    return jsonify({
        "product_name":product_name,
        "region":"Hà Nội",
        "items":ordered,
        "source":"Điện Thoại Vui"
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
