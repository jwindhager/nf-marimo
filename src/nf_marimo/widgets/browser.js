function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else e.setAttribute(k, v);
  }
  for (const c of children)
    e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return e;
}

function render({ model, el: root }) {
  const card = el("div", { class: "nfm-card" });
  const input = el("input", {
    type: "search",
    placeholder: "Search modules (name, keywords, description)…",
    style: "width: 100%; padding: 4px 8px; margin-bottom: 6px;",
  });
  input.value = model.get("query");
  let timer;
  input.oninput = () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      model.set("query", input.value);
      model.save_changes();
    }, 300);
  };
  const list = el("div", { style: "max-height: 260px; overflow: auto;" });
  const detail = el("div");
  card.append(input, list, detail);
  root.append(card);

  const drawList = () => {
    list.replaceChildren();
    const err = model.get("error");
    if (err) list.append(el("div", { class: "nfm-problem" }, err));
    const table = el("table");
    for (const r of model.get("results")) {
      const row = el(
        "tr",
        { style: "cursor: pointer;" },
        el("td", {}, el("code", {}, r.id)),
        el("td", {}, r.description),
      );
      if (r.id === model.get("selected"))
        row.style.background = "rgba(31,136,61,0.12)";
      row.onclick = () => {
        model.set("selected", r.id);
        model.save_changes();
      };
      table.append(row);
    }
    list.append(table);
  };
  const drawDetail = () => {
    detail.replaceChildren();
    const code = model.get("snippet");
    if (!code) return;
    const copy = el("button", { class: "nfm-run" }, "Copy cell");
    copy.onclick = async () => {
      await navigator.clipboard.writeText(code);
      copy.textContent = "Copied ✓";
      setTimeout(() => (copy.textContent = "Copy cell"), 1500);
    };
    detail.append(
      el(
        "div",
        { class: "nfm-head" },
        el("span", { class: "nfm-section" }, model.get("selected")),
        copy,
      ),
      el("pre", { class: "nfm-log" }, code),
      el(
        "div",
        { class: "nfm-desc" },
        "Paste into a new cell, or run: nfm add <module> <notebook.py>",
      ),
    );
  };
  model.on("change:results", drawList);
  model.on("change:error", drawList);
  model.on("change:selected", drawList);
  model.on("change:snippet", drawDetail);
  drawList();
  drawDetail();
}

export default { render };
