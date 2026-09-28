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
let orangeSpot = "none";
let manualRepairPrices = {};
let faceIdFault = false;
let selectedKeyBeforeFaceId = null;
let searchController = null;
let repairController = null;
let searchRequestId = 0;
let repairRequestId = 0;

const fmt = (n) => new Intl.NumberFormat("vi-VN").format(Number(n || 0)) + "đ";

function fmtFormula(n) {
  const value = Math.round(Number(n || 0) / 1000);
  return new Intl.NumberFormat("vi-VN").format(value);
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

  if (searchController) searchController.abort();
  searchController = new AbortController();
  const requestId = ++searchRequestId;

  btn.disabled = true;
  btn.textContent = "Đang tìm...";
  statusEl.textContent = "Đang lấy dữ liệu giá...";
  resultsEl.innerHTML = "";

  try {
    const res = await fetch("/api/search?q=" + encodeURIComponent(q), {
      signal: searchController.signal
    });
    const data = await res.json();
    if (requestId !== searchRequestId) return;
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
    if (e?.name !== "AbortError" && requestId === searchRequestId) {
      statusEl.textContent = "Lỗi: " + e.message;
    }
  } finally {
    if (requestId === searchRequestId) {
      btn.disabled = false;
      btn.textContent = "Tìm giá";
    }
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
  if (repairController) repairController.abort();
  currentProduct = p;
  selectedKey = "thu_loai_1";
  faultyKeys = new Set();
  orangeSpot = "none";
  manualRepairPrices = {};
  faceIdFault = false;
  selectedKeyBeforeFaceId = null;
  repairItems = [];

  $("#productName").textContent = p.name || "";
  $("#productId").textContent = p.web_id || "—";

  renderConditions();
  renderRepairLoading();
  const faceIdAlert = $("#faceIdAlert");
  if (faceIdAlert) faceIdAlert.classList.add("hidden");
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
    const unavailable = price <= 0;
    const el = document.createElement("div");
    el.className =
      "condition" +
      (selectedKey === c.key ? " active" : "") +
      (faceIdFault ? " locked" : "") +
      (unavailable ? " unavailable" : "");
    el.innerHTML =
      '<div><div class="condition-title">' + c.title +
      '</div><div class="condition-desc">' + c.desc +
      '</div></div><div class="condition-price">' +
      (unavailable ? "Chưa có giá" : fmt(price)) +
      "</div>";

    el.onclick = () => {
      if (faceIdFault || unavailable) return;
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
  if (repairController) repairController.abort();
  repairController = new AbortController();
  const requestId = ++repairRequestId;
  const productIdAtRequest = String(currentProduct?.web_id || "");

  try {
    const res = await fetch("/api/repair-prices?product_name=" + encodeURIComponent(productName), {
      signal: repairController.signal
    });
    const data = await res.json();

    if (
      requestId !== repairRequestId ||
      productIdAtRequest !== String(currentProduct?.web_id || "")
    ) return;

    if (!res.ok) throw new Error(data.error || "Không lấy được giá sửa.");

    repairItems = (data.items || []).filter(Boolean);
    const fetched = Number(data.fetched_at || 0) * 1000;
    const stamp = fetched
      ? new Intl.DateTimeFormat("vi-VN", {
          hour: "2-digit",
          minute: "2-digit",
          day: "2-digit",
          month: "2-digit",
          year: "numeric"
        }).format(new Date(fetched))
      : "";
    $("#repairStatus").textContent =
      "Nguồn: Điện Thoại Vui - Hà Nội" + (stamp ? " • " + stamp : "");
    renderRepairs();
    updateFinalPrice();
  } catch (e) {
    if (e?.name === "AbortError" || requestId !== repairRequestId) return;
    repairItems = [];
    $("#repairStatus").textContent = "Chưa lấy được giá sửa";
    $("#repairList").innerHTML =
      '<div class="repair-loading error">Không lấy được bảng giá sửa lúc này. Giá nhập máy vẫn có thể tra bình thường.</div>';
    updateFinalPrice();
  }
}

function parseManualPrice(value) {
  const digits = String(value || "").replace(/[^0-9]/g, "");
  return digits ? Number(digits) : 0;
}

function calcRepairDeduction(item, originalPrice) {
  const price = Number(originalPrice || 0);
  if (!price) return 0;

  const rate = Number(item?.support_rate || 0);
  const maxSupport = item?.max_support == null ? null : Number(item.max_support);

  let support = Math.round(price * rate);
  if (maxSupport !== null) support = Math.min(support, maxSupport);

  return Math.max(0, price - support);
}

function effectiveRepair(item) {
  if (item?.special === "face_id") {
    return {
      available: true,
      repair_price: 0,
      deduction: 0,
      manual: false
    };
  }

  const manualPrice = Number(manualRepairPrices[item.key] || 0);

  if (manualPrice > 0) {
    return {
      available: true,
      repair_price: manualPrice,
      deduction: calcRepairDeduction(item, manualPrice),
      manual: true
    };
  }

  return {
    available: !!item.available,
    repair_price: Number(item.repair_price || 0),
    deduction: Number(item.deduction || 0),
    manual: false
  };
}

function renderRepairs() {
  const list = $("#repairList");
  list.innerHTML = "";

  const orangeRow = document.createElement("div");
  orangeRow.className = "repair-row orange-row";

  const orangeInfo = document.createElement("div");
  orangeInfo.className = "repair-info";
  orangeInfo.innerHTML =
    '<div class="repair-title">Đốm cam</div>' +
    '<div class="repair-meta">Đốm 1 cam: trừ 500.000đ • Đốm 2 cam: trừ 800.000đ</div>';

  const orangeChoices = document.createElement("div");
  orangeChoices.className = "repair-choices orange-choices";

  [
    { key: "none", label: "Không đốm" },
    { key: "one", label: "Đốm 1 cam" },
    { key: "two", label: "Đốm 2 cam" }
  ].forEach(option => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "repair-choice" + (orangeSpot === option.key ? " active" : "");
    if (option.key !== "none") b.classList.add("fault");
    b.textContent = option.label;
    b.onclick = () => {
      orangeSpot = option.key;
      renderRepairs();
      updateFinalPrice();
    };
    orangeChoices.appendChild(b);
  });

  orangeRow.appendChild(orangeInfo);
  orangeRow.appendChild(orangeChoices);
  list.appendChild(orangeRow);

  repairItems.forEach(item => {
    const row = document.createElement("div");
    row.className = "repair-row";
    if (item?.key === "camera_front" || item?.key === "camera_back") row.classList.add("camera-row");
    if (faceIdFault && item?.special !== "face_id") row.classList.add("repair-suspended");

    const info = document.createElement("div");
    info.className = "repair-info";

    const effective = effectiveRepair(item);
    const isFaceId = item?.special === "face_id";
    let meta = isFaceId ? "" : "Chưa có giá phù hợp";
    if (effective.available && !isFaceId) {
      const supportPct = Math.round(Number(item.support_rate || 0) * 100);
      const supportText = item.max_support
        ? "Hỗ trợ " + supportPct + "% (tối đa " + fmt(item.max_support) + ")"
        : (supportPct ? "Hỗ trợ " + supportPct + "%" : "Không hỗ trợ");

      meta =
        (effective.manual ? "Giá thủ công " : "Giá sửa ") + fmt(effective.repair_price) +
        " • " + supportText +
        " • Trừ " + fmt(effective.deduction);
    }

    const manualUrl = item.source_url || item.source_page || "";
    info.innerHTML =
      '<div class="repair-title">' + escapeHtml(item.label || "") + "</div>" +
      (effective.manual ? '<div class="manual-price-badge">ĐANG DÙNG GIÁ THỦ CÔNG</div>' : "") +
      (meta ? '<div class="repair-meta">' + escapeHtml(meta) + "</div>" : "") +
      (!isFaceId && manualUrl
        ? '<a class="manual-price-link" href="' + escapeHtml(manualUrl) + '" target="_blank" rel="noopener noreferrer">Tra giá thủ công ↗</a>'
        : "");

    const choices = document.createElement("div");
    choices.className = "repair-choices";

    const okBtn = document.createElement("button");
    okBtn.type = "button";
    okBtn.className = "repair-choice" + (!faultyKeys.has(item.key) ? " active" : "");
    okBtn.textContent = "Không lỗi";
    okBtn.disabled = faceIdFault && !isFaceId;
    okBtn.onclick = () => {
      if (faceIdFault && !isFaceId) return;
      faultyKeys.delete(item.key);

      if (isFaceId) {
        faceIdFault = false;
        if (selectedKeyBeforeFaceId) {
          selectedKey = selectedKeyBeforeFaceId;
        }
        selectedKeyBeforeFaceId = null;
        renderConditions();
      }

      renderRepairs();
      updateFinalPrice();
    };

    const faultBtn = document.createElement("button");
    faultBtn.type = "button";
    faultBtn.className = "repair-choice fault" + (faultyKeys.has(item.key) ? " active" : "");
    faultBtn.textContent = "Có lỗi";
    const faceIdHasPrice = !isFaceId || Number(currentProduct?.thu_loai_4 || 0) > 0;
    faultBtn.disabled = !effective.available || !faceIdHasPrice || (faceIdFault && !isFaceId);
    faultBtn.title = !faceIdHasPrice
      ? "Loại 4 chưa có giá. Liên hệ QLNH để xác nhận giá nhập."
      : (faceIdFault && !isFaceId
        ? "Face ID đang lỗi: áp dụng giá Loại 4, không cộng thêm phí linh kiện."
        : (effective.available ? "" : "Chưa có giá tự động. Hãy nhập giá thủ công."));
    faultBtn.onclick = () => {
      if (faceIdFault && !isFaceId) return;
      if (!effective.available) return;
      faultyKeys.add(item.key);

      if (isFaceId) {
        if (!faceIdFault) selectedKeyBeforeFaceId = selectedKey;
        faceIdFault = true;
        selectedKey = "thu_loai_4";
        renderConditions();
      }

      renderRepairs();
      updateFinalPrice();
    };

    choices.appendChild(okBtn);
    choices.appendChild(faultBtn);

    const rightWrap = document.createElement("div");
    rightWrap.className = "repair-right";

    rightWrap.appendChild(choices);

    if (!isFaceId) {
      const manualWrap = document.createElement("div");
      manualWrap.className = "manual-price-wrap";

      const manualInput = document.createElement("input");
      manualInput.type = "text";
      manualInput.inputMode = "numeric";
      manualInput.className = "manual-price-input";
      manualInput.placeholder = "Điền giá thủ công";
      manualInput.disabled = faceIdFault;
      manualInput.value = manualRepairPrices[item.key]
        ? new Intl.NumberFormat("vi-VN").format(manualRepairPrices[item.key])
        : "";

      manualInput.addEventListener("input", (e) => {
        const price = parseManualPrice(e.target.value);

        if (price > 0) {
          manualRepairPrices[item.key] = price;
          faultBtn.disabled = faceIdFault;
        } else {
          delete manualRepairPrices[item.key];
          if (!item.available) faultyKeys.delete(item.key);
          faultBtn.disabled = !item.available || faceIdFault;
        }

        updateFinalPrice();
      });

      manualInput.addEventListener("blur", () => {
        renderRepairs();
      });
      manualInput.dataset.key = item.key;

      const manualTools = document.createElement("div");
      manualTools.className = "manual-price-tools";

      const manualHint = document.createElement("div");
      manualHint.className = "manual-price-hint";
      manualHint.textContent = "Nhập giá gốc linh kiện";
      manualTools.appendChild(manualHint);

      if (manualRepairPrices[item.key]) {
        const resetManualBtn = document.createElement("button");
        resetManualBtn.type = "button";
        resetManualBtn.className = "manual-reset-btn";
        resetManualBtn.textContent = "Dùng giá tự động";
        resetManualBtn.onclick = () => {
          delete manualRepairPrices[item.key];
          if (!item.available) faultyKeys.delete(item.key);
          renderRepairs();
          updateFinalPrice();
        };
        manualTools.appendChild(resetManualBtn);
      }

      manualWrap.appendChild(manualInput);
      manualWrap.appendChild(manualTools);
      rightWrap.appendChild(manualWrap);
    } else {
      const spacer = document.createElement("div");
      spacer.className = "manual-price-spacer";
      spacer.setAttribute("aria-hidden", "true");
      rightWrap.appendChild(spacer);
    }

    row.appendChild(info);
    row.appendChild(rightWrap);
    list.appendChild(row);
  });
}

function orangeSpotDeduction() {
  if (orangeSpot === "one") return 500000;
  if (orangeSpot === "two") return 800000;
  return 0;
}

function repairDeductionTotal() {
  if (faceIdFault) return 0;

  const repairTotal = repairItems.reduce((sum, item) => {
    const effective = effectiveRepair(item);
    if (!effective.available || !faultyKeys.has(item.key)) return sum;
    if (item?.special === "face_id") return sum;
    return sum + Number(effective.deduction || 0);
  }, 0);

  return repairTotal + orangeSpotDeduction();
}

function updateFinalPrice() {
  if (!currentProduct) return;

  const rawBase = Number(currentProduct[selectedKey] || 0);
  const base = rawBase;
  const deduction = repairDeductionTotal();
  const hasBasePrice = rawBase > 0;
  const finalPrice = hasBasePrice ? Math.max(0, base - deduction) : 0;

  $("#baseTradePrice").textContent = hasBasePrice ? fmt(base) : "Chưa có giá";
  $("#repairDeduction").textContent = "-" + fmt(deduction);
  $("#finalPrice").textContent = hasBasePrice
    ? fmt(finalPrice)
    : (faceIdFault ? "Liên hệ QLNH" : "Chưa có giá");

  const condition = conditionMeta.find(x => x.key === selectedKey);
  const parts = [];
  if (hasBasePrice) {
    parts.push((condition?.title || "Giá máy").toUpperCase() + " " + fmtFormula(rawBase));
  } else {
    parts.push((condition?.title || "Giá máy").toUpperCase() + " CHƯA CÓ GIÁ");
  }

  if (!faceIdFault) {
    if (orangeSpot === "one") {
      parts.push("- 500 ĐỐM 1 CAM");
    } else if (orangeSpot === "two") {
      parts.push("- 800 ĐỐM 2 CAM");
    }

    repairItems.forEach(item => {
      const effective = effectiveRepair(item);
      if (!effective.available || !faultyKeys.has(item.key)) return;
      if (item?.special === "face_id") return;
      parts.push("- " + fmtFormula(effective.deduction) + " " + String(item.label || "").toUpperCase());
    });
  }

  parts.push(hasBasePrice ? "= " + fmtFormula(finalPrice) : "= LIÊN HỆ QLNH");

  $("#proposalText").textContent = parts.join(" ");

  const faceIdAlert = $("#faceIdAlert");
  if (faceIdAlert) {
    faceIdAlert.classList.toggle("hidden", !faceIdFault);
  }
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

$("#resetRepairBtn").addEventListener("click", () => {
  faultyKeys.clear();
  orangeSpot = "none";
  manualRepairPrices = {};
  faceIdFault = false;
  selectedKeyBeforeFaceId = null;
  renderConditions();
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
  if (repairController) repairController.abort();
  detailCard.classList.add("hidden");
  dropdownOpen = true;
  renderProductDropdown();
  input.focus();
});
$("#copyBtn").addEventListener("click", async () => {
  const text = $("#proposalText").textContent.trim();
  try {
    await navigator.clipboard.writeText(text);
    $("#copyBtn").textContent = "Đã copy";
    setTimeout(() => $("#copyBtn").textContent = "Copy", 1200);
  } catch {
    alert(text);
  }
});
