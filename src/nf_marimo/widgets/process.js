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
  root.append(card);

  const draw = () => {
    const status = model.get("status");
    card.replaceChildren();
    card.append(
      el(
        "div",
        { class: "nfm-head" },
        el("span", { class: "nfm-title" }, model.get("title")),
        el("span", { class: "nfm-module" }, model.get("module")),
        el(
          "span",
          { class: `nfm-badge nfm-${status === "done" ? "done" : "idle"}` },
          status,
        ),
      ),
    );
    card.append(el("div", { class: "nfm-desc" }, model.get("description")));
    for (const p of model.get("problems"))
      card.append(el("div", { class: "nfm-problem" }, "⚠ " + p));

    const inputs = el("table");
    inputs.append(
      el(
        "tr",
        {},
        el("th", {}, "input"),
        el("th", {}, "elements"),
        el("th", {}, "connected to"),
      ),
    );
    for (const i of model.get("inputs")) {
      inputs.append(
        el(
          "tr",
          { title: i.description },
          el("td", {}, el("code", {}, i.key)),
          el("td", {}, el("code", {}, i.elements.join(", "))),
          el(
            "td",
            {},
            i.connected
              ? el("pre", {}, i.source)
              : el("span", { class: "nfm-problem" }, "not connected"),
          ),
        ),
      );
    }
    card.append(el("div", { class: "nfm-section" }, "Inputs"), inputs);

    const results = model.get("results");
    const outputs = el("table");
    outputs.append(
      el(
        "tr",
        {},
        el("th", {}, "output"),
        el("th", {}, "elements"),
        el("th", {}, "results"),
      ),
    );
    for (const o of model.get("outputs")) {
      const items = results[o.emit];
      outputs.append(
        el(
          "tr",
          {},
          el("td", {}, el("code", {}, o.emit)),
          el("td", {}, el("code", {}, o.elements.join(", "))),
          el(
            "td",
            {},
            items ? el("pre", {}, items.join("\n") || "(empty)") : "—",
          ),
        ),
      );
    }
    card.append(el("div", { class: "nfm-section" }, "Outputs"), outputs);

    if (status !== "done") {
      card.append(
        el(
          "div",
          { class: "nfm-desc" },
          "Run this cell to test-run the step on the test data.",
        ),
      );
    }
  };
  for (const t of ["status", "results", "problems", "inputs"])
    model.on(`change:${t}`, draw);
  draw();
}

export default { render };
