const $ = (s) => document.querySelector(s);
const input = $("#searchInput");
const btn = $("#searchBtn");
const statusEl = $("#status");
const resultsEl = $("#results");
const detailCard = $("#detailCard");

let currentProduct = null;
let selectedKey = "thu_loai_1";
let searchResults = [];
let dropdownOpen = true;

const fmt = (n) => new Intl.NumberFormat("vi-VN").format(Number(n || 0)) + "đ";

function normalizeTokens(text) {
  return String(text || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
}

function filterRelevantProducts(products, keyword) {
  const queryTokens = normalizeTokens(keyword);
  if (!queryTokens.length) return products;

  return products.filter(product => {
    const productTokens = new Set(normalizeTokens(product.name || ""));
    return queryTokens.every(token => productTokens.has(token));
  });
}

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

    const apiProducts = data.products || [];
    searchResults = filterRelevantProducts(apiProducts, q);
    dropdownOpen = true;
    currentProduct = null;
    detailCard.classList.add("hidden");

    statusEl.textContent = searchResults.length
      ? "Tìm thấy " + searchResults.length + " sản phẩm đúng từ khóa."
      : "Không tìm thấy sản phẩm đúng model/dung lượng đã nhập.";

    renderProductDropdown();
  } catch (e) {
    statusEl.textContent = "Lỗi: " + e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "Tìm giá";
  }
}

function renderProductDropdown() {
  resultsEl.innerHTML = "";
  if (!searchResults.length) return;

  const box = document.createElement("div");
  box.className = "product-dropdown";

  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "product-dropdown-trigger";

  const selectedName = currentProduct?.name || "Chọn sản phẩm";
  trigger.innerHTML =
    '<div><div class="dropdown-label">SẢN PHẨM</div><div class="dropdown-selected">' +
    escapeHtml(selectedName) +
    '</div></div><div class="dropdown-arrow">' + (dropdownOpen ? "▲" : "▼") + "</div>";

  trigger.onclick = () => {
    dropdownOpen = !dropdownOpen;
    renderProductDropdown();
  };

  box.appendChild(trigger);

  if (dropdownOpen) {
    const list = document.createElement("div");
    list.className = "product-dropdown-list";

    searchResults.forEach((p, index) => {
      const row = document.createElement("label");
      row.className = "product-option" + (currentProduct?.web_id === p.web_id ? " selected" : "");

      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "selectedProduct";
      radio.checked = currentProduct?.web_id === p.web_id;
      radio.value = String(index);

      const tick = document.createElement("span");
      tick.className = "product-tick";
      tick.textContent = radio.checked ? "✓" : "";

      const content = document.createElement("span");
      content.className = "product-option-content";
      content.innerHTML =
        '<span class="product-option-name">' + escapeHtml(p.name || "") + "</span>" +
        '<span class="product-option-brand">' + escapeHtml(p.brand || "") + "</span>";

      const price = document.createElement("span");
      price.className = "product-option-price";
      price.textContent = fmt(p.thu_loai_1);

      row.appendChild(radio);
      row.appendChild(tick);
      row.appendChild(content);
      row.appendChild(price);

      row.addEventListener("click", (e) => {
        e.preventDefault();
        dropdownOpen = false;
        currentProduct = p;
        renderProductDropdown();
        selectProduct(p);
      });

      list.appendChild(row);
    });

    box.appendChild(list);
  }

  resultsEl.appendChild(box);
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
      '</div></div><div class="condition-price">' + fmt(price) + "</div>";

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
  dropdownOpen = true;
  renderProductDropdown();
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
