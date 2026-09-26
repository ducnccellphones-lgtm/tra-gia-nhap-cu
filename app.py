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

@lru_cache(maxsize=256)
def fetch_repair_type(product_name: str, key: str):
    cfg = next((x for x in REPAIR_TYPES if x["key"] == key), None)
    if not cfg:
        return None

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
