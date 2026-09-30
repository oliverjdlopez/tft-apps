import "@testing-library/jest-dom/vitest";

class TestResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

Object.defineProperty(globalThis, "ResizeObserver", { value: TestResizeObserver, writable: true });
Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
  value: () => ({
    scale() {},
    clearRect() {},
    fillRect() {},
    strokeRect() {},
    setLineDash() {},
    fillText() {},
    measureText: (text: string) => ({ width: text.length * 7 }),
  }),
});
Object.defineProperty(HTMLMediaElement.prototype, "load", { value: () => {} });
Object.defineProperty(URL, "createObjectURL", { value: () => "blob:test-download", configurable: true });
Object.defineProperty(URL, "revokeObjectURL", { value: () => {}, configurable: true });
