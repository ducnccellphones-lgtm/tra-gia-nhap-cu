const $ = (s) => document.querySelector(s);
const input = $("#searchInput");
const btn = $("#searchBtn");
const statusEl = $("#status");
const resultsEl = $("#results");
const detailCard = $("#detailCard");

let currentProduct = null;
let selectedKey = "thu_loai_1";

const fmt = (n) => new Intl.NumberFormat("vi-VN").format(Number(n || 0)) + "đ";

const conditionMeta = [
  { key: "just_activated", title: "Máy mới kích hoạt", desc: "Máy đẹp, điều kiện kích hoạt theo chính sách hiện hành." },
  { key: "thu_loai_1", title: "Loại 1", desc: "Máy hoạt động bình thường, màn đẹp, thân máy đẹp." },
  { key: "thu_loai_2", title: "Loại 2", desc: "Máy hoạt động bình thường, màn đẹp, thân máy trầy xước nhẹ." },
  { key: "thu_loai_3", title: "Loại 3", desc: "Máy hoạt động bình thường, màn trầy nhẹ, thân máy cấn móp nhẹ." },
  { key: "thu_loai_4", title: "Loại 4", desc: "Ngoại hình xấu nhưng màn còn hiển thị và cảm ứng được." }
];

async function searchProducts() {
  const q = input.value.trim();
  if (q.length < 2) {
    statusEl.textContent = "Nhập ít nhất 2 ký tự.";
    return;
  }

  btn.disabled = true;
  btn.textContent = "Đang tìm...";
  statusEl.textContent = "Đang lấy dữ liệu giá...";
  resultsEl.innerHTML = "";

  try {
    const res = await fetch("/api/search?q=" + encodeURIComponent(q));
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Không lấy được dữ liệu.");

    const products = data.products || [];
    statusEl.textContent = products.length
      ? "Tìm thấy " + products.length + " sản phẩm."
      : "Không tìm thấy sản phẩm phù hợp.";

    products.forEach(p => {
      const el = document.createElement("button");
      el.className = "result-item";
      el.innerHTML =
        '<div><div class="result-name">' + escapeHtml(p.name || "") +
        '</div><div class="condition-desc">' + escapeHtml(p.brand || "") +
        '</div></div><div class="result-price">' + fmt(p.thu_loai_1) + '</div>';
      el.onclick = () => selectProduct(p);
      resultsEl.appendChild(el);
    });
  } catch (e) {
    statusEl.textContent = "Lỗi: " + e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "Tìm giá";
  }
}

function selectProduct(p) {
  currentProduct = p;
  selectedKey = "thu_loai_1";
  $("#productName").textContent = p.name || "";
  $("#productId").textContent = p.web_id || "—";
  $("#smemberPrice").textContent = fmt(p.tro_gia);
  $("#addSmember").checked = false;
  renderConditions();
  updateFinalPrice();
  detailCard.classList.remove("hidden");
  detailCard.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderConditions() {
  const list = $("#conditionList");
  list.innerHTML = "";

  conditionMeta.forEach(c => {
    const price = Number(currentProduct?.[c.key] || 0);
    const el = document.createElement("div");
    el.className = "condition" + (selectedKey === c.key ? " active" : "");
    el.innerHTML =
      '<div><div class="condition-title">' + c.title +
      '</div><div class="condition-desc">' + c.desc +
      '</div></div><div class="condition-price">' + fmt(price) + '</div>';

    el.onclick = () => {
      selectedKey = c.key;
      renderConditions();
      updateFinalPrice();
    };

    list.appendChild(el);
  });
}

function updateFinalPrice() {
  if (!currentProduct) return;
  let price = Number(currentProduct[selectedKey] || 0);
  if ($("#addSmember").checked) price += Number(currentProduct.tro_gia || 0);
  $("#finalPrice").textContent = fmt(price);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;"
  }[c]));
}

btn.addEventListener("click", searchProducts);
input.addEventListener("keydown", e => {
  if (e.key === "Enter") searchProducts();
});
$("#addSmember").addEventListener("change", updateFinalPrice);
$("#changeBtn").addEventListener("click", () => {
  detailCard.classList.add("hidden");
  input.focus();
});
$("#copyBtn").addEventListener("click", async () => {
  const text = $("#productName").textContent + " - " + $("#finalPrice").textContent;
  try {
    await navigator.clipboard.writeText(text);
    $("#copyBtn").textContent = "Đã copy";
    setTimeout(() => $("#copyBtn").textContent = "Copy giá", 1200);
  } catch {
    alert(text);
  }
});
