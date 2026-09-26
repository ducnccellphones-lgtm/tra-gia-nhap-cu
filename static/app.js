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
let repairItems = [];
let faultyKeys = new Set();

const fmt = (n) => new Intl.NumberFormat("vi-VN").format(Number(n || 0)) + "đ";

function fmtFormula(n) {
  const value = Math.round(Number(n || 0) / 1000);
  return new Intl.NumberFormat("vi-VN").format(value);
}

function fmtBonus(n) {
  const value = Number(n || 0);
  if (value >= 1000000 && value % 1000000 === 0) {
    return (value / 1000000) + "TR";
  }
  return fmtFormula(value);
}

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
    const productTokens = normalizeTokens(product.name || "");

    return queryTokens.every(token => {
      if (productTokens.includes(token)) return true;

      if (/^\d+$/.test(token)) {
        return productTokens.some(productToken =>
          productToken === token + "gb" || productToken === token + "tb"
        );
      }

      return false;
    });
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

async function selectProduct(p) {
  currentProduct = p;
  selectedKey = "thu_loai_1";
  faultyKeys = new Set();
  repairItems = [];

  $("#productName").textContent = p.name || "";
  $("#productId").textContent = p.web_id || "—";
  $("#smemberPrice").textContent = fmt(p.tro_gia);
  $("#addSmember").checked = false;

  renderConditions();
  renderRepairLoading();
  updateFinalPrice();

  detailCard.classList.remove("hidden");
  detailCard.scrollIntoView({ behavior: "smooth", block: "start" });

  await loadRepairPrices(p.name || "");
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

function renderRepairLoading() {
  $("#repairStatus").textContent = "Đang lấy giá sửa...";
  $("#repairList").innerHTML = '<div class="repair-loading">Đang đối chiếu giá Điện Thoại Vui...</div>';
}

async function loadRepairPrices(productName) {
  try {
    const res = await fetch("/api/repair-prices?product_name=" + encodeURIComponent(productName));
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Không lấy được giá sửa.");

    repairItems = (data.items || []).filter(Boolean);
    $("#repairStatus").textContent = "Nguồn: Điện Thoại Vui - Hà Nội";
    renderRepairs();
    updateFinalPrice();
  } catch (e) {
    repairItems = [];
    $("#repairStatus").textContent = "Chưa lấy được giá sửa";
    $("#repairList").innerHTML =
      '<div class="repair-loading error">Không lấy được bảng giá sửa lúc này. Giá nhập máy vẫn có thể tra bình thường.</div>';
    updateFinalPrice();
  }
}

function renderRepairs() {
  const list = $("#repairList");
  list.innerHTML = "";

  repairItems.forEach(item => {
    const row = document.createElement("div");
    row.className = "repair-row";

    const info = document.createElement("div");
    info.className = "repair-info";

    let meta = "Chưa có giá phù hợp";
    if (item.available) {
      const supportPct = Math.round(Number(item.support_rate || 0) * 100);
      const supportText = item.max_support
        ? "Hỗ trợ " + supportPct + "% (tối đa " + fmt(item.max_support) + ")"
        : (supportPct ? "Hỗ trợ " + supportPct + "%" : "Không hỗ trợ");

      meta =
        "Giá sửa " + fmt(item.repair_price) +
        " • " + supportText +
        " • Trừ " + fmt(item.deduction);
    }

    info.innerHTML =
      '<div class="repair-title">' + escapeHtml(item.label || "") + "</div>" +
      '<div class="repair-meta">' + escapeHtml(meta) + "</div>";

    const choices = document.createElement("div");
    choices.className = "repair-choices";

    const okBtn = document.createElement("button");
    okBtn.type = "button";
    okBtn.className = "repair-choice" + (!faultyKeys.has(item.key) ? " active" : "");
    okBtn.textContent = "Không lỗi";
    okBtn.onclick = () => {
      faultyKeys.delete(item.key);
      renderRepairs();
      updateFinalPrice();
    };

    const faultBtn = document.createElement("button");
    faultBtn.type = "button";
    faultBtn.className = "repair-choice fault" + (faultyKeys.has(item.key) ? " active" : "");
    faultBtn.textContent = "Có lỗi";
    faultBtn.disabled = !item.available;
    faultBtn.title = item.available ? "" : "Chưa tìm thấy giá sửa phù hợp";
    faultBtn.onclick = () => {
      if (!item.available) return;
      faultyKeys.add(item.key);
      renderRepairs();
      updateFinalPrice();
    };

    choices.appendChild(okBtn);
    choices.appendChild(faultBtn);
    row.appendChild(info);
    row.appendChild(choices);
    list.appendChild(row);
  });
}

function repairDeductionTotal() {
  return repairItems.reduce((sum, item) => {
    if (!item?.available || !faultyKeys.has(item.key)) return sum;
    return sum + Number(item.deduction || 0);
  }, 0);
}

function updateFinalPrice() {
  if (!currentProduct) return;

  const rawBase = Number(currentProduct[selectedKey] || 0);
  const smember = $("#addSmember").checked ? Number(currentProduct.tro_gia || 0) : 0;
  const base = rawBase + smember;
  const deduction = repairDeductionTotal();
  const finalPrice = Math.max(0, base - deduction);

  $("#baseTradePrice").textContent = fmt(base);
  $("#repairDeduction").textContent = "-" + fmt(deduction);
  $("#finalPrice").textContent = fmt(finalPrice);

  const condition = conditionMeta.find(x => x.key === selectedKey);
  const parts = [];
  parts.push((condition?.title || "Giá máy").toUpperCase() + " " + fmtFormula(rawBase));

  repairItems.forEach(item => {
    if (!item?.available || !faultyKeys.has(item.key)) return;
    parts.push("- " + fmtFormula(item.deduction) + " " + String(item.label || "").toUpperCase());
  });

  if (smember > 0) {
    parts.push("+ " + fmtBonus(smember) + " SMEMBER");
  }

  parts.push("= " + fmtFormula(finalPrice));
  $("#proposalText").textContent = parts.join(" ");
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

$("#resetRepairBtn").addEventListener("click", () => {
  faultyKeys.clear();
  renderRepairs();
  updateFinalPrice();

  const resetBtn = $("#resetRepairBtn");
  const oldText = resetBtn.textContent;
  resetBtn.textContent = "Đã reset";
  setTimeout(() => {
    resetBtn.textContent = oldText;
  }, 1000);
});
$("#changeBtn").addEventListener("click", () => {
  detailCard.classList.add("hidden");
  dropdownOpen = true;
  renderProductDropdown();
  input.focus();
});
$("#copyBtn").addEventListener("click", async () => {
  const text = $("#productName").textContent + " - Giá nhập cuối: " + $("#finalPrice").textContent;
  try {
    await navigator.clipboard.writeText(text);
    $("#copyBtn").textContent = "Đã copy";
    setTimeout(() => $("#copyBtn").textContent = "Copy giá", 1200);
  } catch {
    alert(text);
  }
});
