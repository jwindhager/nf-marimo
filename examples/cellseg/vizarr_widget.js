// anywidget front end for the BioNGFF vizarr viewer (https://github.com/BioNGFF/vizarr).
// The viewer library is loaded from npm (@biongff/vizarr), pinned.
import { createViewer } from "https://esm.sh/@biongff/vizarr@1.5.0?deps=react@18.3.1,react-dom@18.3.1";

// marimo renders widgets in a shadow DOM, which page-level styles (MUI/emotion rules inserted
// into document.head at runtime) do not reach: mirror them into the widget's shadow root.
function mirrorDocumentStyles(el) {
  const root = el.getRootNode();
  if (!(root instanceof ShadowRoot) || !("adoptedStyleSheets" in root))
    return () => {};
  const sheet = new CSSStyleSheet();
  root.adoptedStyleSheets = [...root.adoptedStyleSheets, sheet];
  let last = "";
  const sync = () => {
    const parts = [];
    for (const node of document.head.querySelectorAll(
      "style[data-emotion], style[data-jss]",
    )) {
      const s = node.sheet;
      if (!s) continue;
      try {
        for (const rule of s.cssRules) parts.push(rule.cssText);
      } catch (_) {
        /* cross-origin */
      }
      if (!s.cssRules.length && node.textContent) parts.push(node.textContent);
    }
    const text = parts.join("\n");
    if (text !== last) {
      last = text;
      sheet.replaceSync(text);
    }
  };
  sync();
  const timer = setInterval(sync, 250);
  return () => clearInterval(timer);
}

// Fit the image's physical extent into the canvas area right of the layer panel
// (deck.gl orthographic view: 2^zoom pixels per unit).
const PANEL_WIDTH = 340;

function fit(viewer, div, extent) {
  if (extent.length !== 4) return;
  const [x0, y0, x1, y1] = extent;
  const panel = Math.min(PANEL_WIDTH, div.clientWidth / 2);
  const width = div.clientWidth - panel;
  const zoom = Math.log2(
    0.9 * Math.min(width / (x1 - x0), div.clientHeight / (y1 - y0)),
  );
  const shift = panel / 2 / 2 ** zoom; // move the image right, out from under the panel
  viewer.setViewState({ target: [(x0 + x1) / 2 - shift, (y0 + y1) / 2], zoom });
}

async function render({ model, el }) {
  const div = document.createElement("div");
  div.style.height = model.get("height");
  div.style.backgroundColor = "black";
  el.appendChild(div);
  const stopStyles = mirrorDocumentStyles(el);
  const viewer = await createViewer(div);
  for (const source of model.get("sources")) viewer.addImage({ source });
  // the viewer's own initial fit is off inside marimo; fit once the layer has loaded
  const timer = setTimeout(() => fit(viewer, div, model.get("extent")), 1500);
  return () => {
    clearTimeout(timer);
    stopStyles();
    viewer.destroy();
  };
}

export default { render };
