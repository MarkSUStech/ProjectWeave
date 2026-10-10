// jsdom 不提供尺寸和媒体查询，真实布局另在浏览器验收。
Object.defineProperty(window, 'matchMedia', { writable: true, value: (query: string) => ({
  matches: false, media: query, onchange: null,
  addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent: () => true,
}) })
globalThis.ResizeObserver = class {
  observe() {} unobserve() {} disconnect() {}
}
globalThis.IntersectionObserver = class {
  root = null; rootMargin = '0px'; thresholds = [0]
  observe() {} unobserve() {} disconnect() {} takeRecords() { return [] }
}
Element.prototype.scrollIntoView = () => {}
