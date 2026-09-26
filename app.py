from flask import Flask, render_template, request, jsonify
import requests

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

def esc_graphql(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
             .replace('"', '\\"')
             .replace("\n", " ")
             .replace("\r", " ")
    )

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

    payload = {
        "query": QUERY % (esc_graphql(keyword), COMPANY_ID),
        "variables": {}
    }

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
                "tro_gia": p.get("tro_gia") or 0,
                "activation_bonus_value": p.get("activation_bonus_value") or 0,
                "activation_bonus_price": p.get("activation_bonus_price") or "",
                "text": p.get("text") or ""
            })

        return jsonify({
            "products": cleaned,
            "count": len(cleaned),
            "note": node.get("trade_in_note") or ""
        })

    except requests.RequestException as e:
        return jsonify({
            "error": "Không kết nối được API CellphoneS.",
            "detail": str(e),
            "products": []
        }), 502
    except Exception as e:
        return jsonify({
            "error": "API trả dữ liệu không đúng định dạng.",
            "detail": str(e),
            "products": []
        }), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
