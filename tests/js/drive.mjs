// Runs the review page's own JavaScript under Node against a stub DOM, so the
// viewed/undo bookkeeping can be driven by keystroke and inspected. The page
// script is extracted from the built HTML rather than duplicated here: a test
// that ran a copy of the logic would keep passing after render2.py changed.
//
// Protocol: the built page's path in argv[2], a JSON scenario on stdin, a
// JSON report on stdout. See tests/test_page_js.py for both shapes.
import { readFileSync } from "node:fs";

const scenario = JSON.parse(readFileSync(0, "utf8"));

function stub(name) {
  const handlers = {};
  return {
    _name: name, _handlers: handlers,
    textContent: "", innerHTML: "", className: "", disabled: false,
    scrollTop: 0, offsetHeight: 0, onclick: null,
    dataset: {}, style: {},
    setAttribute() {}, getAttribute() { return null; },
    classList: { add() {}, remove() {}, toggle() {} },
    addEventListener(type, fn) { (handlers[type] ||= []).push(fn); },
    getBoundingClientRect() { return { top: 0 }; },
    closest() { return null; },
  };
}

const byId = {};
const bySelector = {};
// The six filter buttons are the one query the page iterates over, so they
// need distinct dataset entries; everything else can share the generic stub.
const filters = ["all", "todo", "work", "hidden", "wrong", "mod"].map(f => {
  const el = stub(`.flt[${f}]`);
  el.dataset.f = f;
  return el;
});
const docHandlers = {};

globalThis.document = {
  getElementById(id) { return byId[id] ||= stub(`#${id}`); },
  querySelector(sel) { return bySelector[sel] ||= stub(sel); },
  querySelectorAll(sel) { return sel === ".flt" ? filters : []; },
  addEventListener(type, fn) { (docHandlers[type] ||= []).push(fn); },
};
globalThis.window = { scrollY: 0, scrollTo() {} };

const store = {};
globalThis.localStorage = {
  getItem(k) { return k in store ? store[k] : null; },
  setItem(k, v) { store[k] = String(v); },
};

const posts = [];
globalThis.fetch = async (url, opts) => {
  if (!opts) {
    return { ok: true, json: async () => ({ synced: scenario.synced, states: scenario.states }) };
  }
  const body = JSON.parse(opts.body);
  posts.push(body);
  const rejected = scenario.rejectFrom != null && posts.length > scenario.rejectFrom;
  return { ok: !rejected, json: async () => ({}), text: async () => "rejected" };
};

const html = readFileSync(process.argv[2], "utf8");
const code = html.slice(html.indexOf("<script>") + "<script>".length,
                        html.lastIndexOf("</script>"));

// Same function body as the page script, so the probe closes over the page's
// own `viewed`, `cur` and `undoStack` rather than a reconstruction of them.
// typeof guards a name the page does not declare yet: the probe reports the
// gap instead of crashing the run.
const probe = `
globalThis.__state = () => ({
  viewed: [...viewed].sort(),
  cur,
  undoDepth: typeof undoStack === "undefined" ? null : undoStack.length,
});`;
new Function(code + probe)();

// The page's handlers are fire-and-forget async; nothing here uses real
// timers, so a macrotask turn is enough to settle every pending await.
const settle = () => new Promise(resolve => setTimeout(resolve, 0));
const press = key => docHandlers.keydown.forEach(
  fn => fn({ key, preventDefault() {}, metaKey: false, ctrlKey: false, altKey: false }));

await settle();

for (const action of scenario.actions) {
  if (action.length === 1) press(action);
  else if (byId[action]?.onclick) byId[action].onclick();
  else throw new Error(`no control with id ${action}`);
  await settle();
}

const undo = byId.undo;
console.log(JSON.stringify({
  ...globalThis.__state(),
  posts,
  undoLabel: undo ? undo.textContent : null,
  undoDisabled: undo ? undo.disabled : null,
}));
