import "@testing-library/jest-dom/vitest";

// jsdom has no layout engine; Radix observes element sizes and media queries.
globalThis.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query) => ({ matches: false, media: query, onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent: () => false }),
});

// React Flow reads CSS transforms through DOMMatrixReadOnly, which jsdom lacks.
globalThis.DOMMatrixReadOnly ??= class DOMMatrixReadOnly {
  constructor(transform) {
    const scale = /scale\(([\d.]+)\)/.exec(transform ?? "");
    this.m22 = scale ? Number(scale[1]) : 1;
  }
};
