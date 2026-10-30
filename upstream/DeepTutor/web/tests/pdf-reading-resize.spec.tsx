import { act, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  PdfDocumentView,
  type PdfDocumentViewProps,
} from "@/components/reading/PdfDocumentView";

const pdf = vi.hoisted(() => ({ ratios: new Map<number, number>(), failures: 0, stall: false,
  requests: [] as Array<{url: string; withCredentials: boolean; disableStream: boolean; disableAutoFetch: boolean; rangeChunkSize: number}> }));

// Keep both reader components real; only the PDF decoding/painting boundary is
// replaced. Page heights still come from PdfPage's measured aspect ratios.
vi.mock("@/lib/pdfjs-loader", () => ({
  outputScale: () => 1,
  pdfjsWasmUrl: () => "/pdfjs/wasm/",
  loadPdfjs: async () => ({
    getDocument: (options: {url: string; withCredentials: boolean; disableStream: boolean; disableAutoFetch: boolean; rangeChunkSize: number}) => {
      pdf.requests.push(options);
      if (pdf.stall) return {destroy: async () => undefined, promise: new Promise(() => {})};
      if (pdf.failures > 0) { pdf.failures--; return {destroy: async () => undefined, promise: Promise.reject(new Error('Temporary connection failure'))}; }
      return ({
      destroy: async () => undefined,
      promise: Promise.resolve({
        getPage: async (locator: number) => ({
          getViewport: ({ scale }: { scale: number }) => ({
            width: 600 * scale,
            height: 600 * (pdf.ratios.get(locator) ?? 1.414) * scale,
          }),
          render: () => ({
            promise: Promise.resolve(),
            cancel: () => undefined,
          }),
          getTextContent: async () => ({ items: [] }),
        }),
      }),
    });},
    TextLayer: class {
      async render() {}
      cancel() {}
    },
  }),
}));

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});

const GAP = 16;
const ROOT_TOP = 80;
let containerWidth: number;
let viewportHeight: number;
let resizeCallbacks: Set<() => void>;

function pageTop(page: HTMLElement): number {
  let top = GAP;
  for (
    let sibling = page.previousElementSibling;
    sibling;
    sibling = sibling.previousElementSibling
  ) {
    top += Number.parseFloat((sibling as HTMLElement).style.height) + GAP;
  }
  return top;
}

function pageAt(root: HTMLElement, locator: number): HTMLElement {
  const page = root.querySelector<HTMLElement>(
    `[data-reader-unit="${locator}"]`,
  );
  if (!page) throw new Error(`Page ${locator} is missing`);
  return page;
}

function positionWithin(root: HTMLElement, locator: number): number {
  const page = pageAt(root, locator);
  return (
    (root.scrollTop - pageTop(page)) / Number.parseFloat(page.style.height)
  );
}

async function resize(width: number): Promise<void> {
  await act(async () => {
    containerWidth = width;
    for (const notify of resizeCallbacks) notify();
  });
}

async function openReader(overrides: Partial<PdfDocumentViewProps> = {}) {
  const onVisibleLocatorChange = vi.fn();
  const props: PdfDocumentViewProps = {
    materialId: "resize-pdf",
    unitCount: 160,
    annotations: [],
    jump: null,
    onSelection: vi.fn(),
    onVisibleLocatorChange,
    ...overrides,
  };
  const view = render(<PdfDocumentView {...props} />);
  const root = view.container.querySelector<HTMLElement>(".dt-reader-scroll")!;
  let scrollTop = 0;
  // jsdom supplies no layout. Model the browser's stacking and scroll clamp
  // from the real page elements/styles, without stubbing either component.
  Object.defineProperty(root, "scrollTop", {
    configurable: true,
    get: () => scrollTop,
    set: (value: number) => {
      const pages = root.querySelectorAll<HTMLElement>("[data-reader-unit]");
      const last = pages[pages.length - 1];
      const contentHeight = last
        ? pageTop(last) + Number.parseFloat(last.style.height) + GAP
        : viewportHeight;
      scrollTop = Math.max(0, Math.min(value, contentHeight - viewportHeight));
    },
  });
  await waitFor(() => expect(pageAt(root, 1).style.width).toBe("600px"));
  await act(async () => {});
  return { ...view, root, props, onVisibleLocatorChange };
}

async function scrollTo(root: HTMLElement, locator: number, fraction = 0.3) {
  const page = pageAt(root, locator);
  root.scrollTop =
    pageTop(page) + Number.parseFloat(page.style.height) * fraction;
  await act(async () => {
    fireEvent.scroll(root);
    await new Promise<void>((resolve) =>
      window.requestAnimationFrame(() => resolve()),
    );
  });
}

beforeEach(() => {
  containerWidth = 648;
  viewportHeight = 500;
  resizeCallbacks = new Set();
  pdf.ratios.clear();
  pdf.requests.length = 0;
  pdf.failures = 0;
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(private readonly callback: () => void) {}
      observe() {
        resizeCallbacks.add(this.callback);
      }
      disconnect() {
        resizeCallbacks.delete(this.callback);
      }
    },
  );
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(
    function (this: HTMLElement) {
      return this.classList.contains("dt-reader-scroll") ? containerWidth : 0;
    },
  );
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    function (this: HTMLElement) {
      if (this.classList.contains("dt-reader-scroll")) {
        return new DOMRect(120, ROOT_TOP, containerWidth, viewportHeight);
      }
      if (this.dataset.readerUnit) {
        const root = this.closest<HTMLElement>(".dt-reader-scroll")!;
        return new DOMRect(
          144,
          ROOT_TOP + pageTop(this) - root.scrollTop,
          Number.parseFloat(this.style.width),
          Number.parseFloat(this.style.height),
        );
      }
      return new DOMRect();
    },
  );
});

afterEach(() => vi.unstubAllGlobals());

describe("PDF reading position during layout changes", () => {
  it("keeps page 99 and its within-page position when the sidebar closes and reopens", async () => {
    const { root, onVisibleLocatorChange } = await openReader();
    await scrollTo(root, 99);
    expect(onVisibleLocatorChange).toHaveBeenLastCalledWith(99);
    onVisibleLocatorChange.mockClear();

    await resize(1098);
    expect(pageAt(root, 99).style.width).toBe("1050px");
    expect(positionWithin(root, 99)).toBeCloseTo(0.3, 5);
    await resize(648);
    expect(positionWithin(root, 99)).toBeCloseTo(0.3, 5);
    expect(
      onVisibleLocatorChange.mock.calls.every(([locator]) => locator === 99),
    ).toBe(true);
  });

  it("uses the latest user scroll as the anchor during successive window resizes", async () => {
    const { root } = await openReader();
    await scrollTo(root, 99, 0.4);
    for (const width of [848, 1048, 748, 548, 648]) {
      await resize(width);
      expect(positionWithin(root, 99)).toBeCloseTo(0.4, 5);
    }
    await scrollTo(root, 120, 0.25);
    await resize(998);
    expect(positionWithin(root, 120)).toBeCloseTo(0.25, 5);
  });

  it("preserves the anchor across coalesced resize notifications and a cancelled resize", async () => {
    const { root } = await openReader();
    await scrollTo(root, 99);
    await act(async () => {
      containerWidth = 1098;
      for (const notify of resizeCallbacks) notify();
      containerWidth = 848;
      for (const notify of resizeCallbacks) notify();
    });
    expect(positionWithin(root, 99)).toBeCloseTo(0.3, 5);
    await act(async () => {
      containerWidth = 1098;
      for (const notify of resizeCallbacks) notify();
      containerWidth = 848;
      for (const notify of resizeCallbacks) notify();
    });
    await scrollTo(root, 120, 0.2);
    await resize(648);
    expect(positionWithin(root, 120)).toBeCloseTo(0.2, 5);
  });

  it("preserves page-top padding and handles mixed measured page heights", async () => {
    pdf.ratios.set(2, 0.75);
    pdf.ratios.set(99, 1.8);
    const { root } = await openReader();
    expect(root.scrollTop).toBe(0);
    await resize(1098);
    expect(root.scrollTop).toBe(0);
    await scrollTo(root, 99);
    await waitFor(() => expect(pageAt(root, 99).style.height).toBe("1890px"));
    await scrollTo(root, 99, 0.2);
    await resize(648);
    expect(positionWithin(root, 99)).toBeCloseTo(0.2, 5);
  });

  it("allows an explicit page jump after a resize and anchors subsequent resizes there", async () => {
    const view = await openReader();
    await scrollTo(view.root, 99);
    await resize(1098);
    view.rerender(
      <PdfDocumentView {...view.props} jump={{ locator: 120, nonce: 1 }} />,
    );
    await waitFor(() =>
      expect(pageAt(view.root, 120).getBoundingClientRect().top).toBe(
        ROOT_TOP + GAP,
      ),
    );
    await resize(648);
    expect(pageAt(view.root, 120).getBoundingClientRect().top).toBe(
      ROOT_TOP + GAP,
    );
  });

  it("clamps restoration at the document end", async () => {
    const { root } = await openReader();
    await scrollTo(root, 160, 0.6);
    await resize(348);
    const lastRect = pageAt(root, 160).getBoundingClientRect();
    expect(lastRect.top).toBeLessThan(ROOT_TOP + viewportHeight);
    expect(lastRect.bottom + GAP).toBeCloseTo(ROOT_TOP + viewportHeight, 5);
  });

  it("uses the authenticated browser-ready PDF and leaves original downloads untouched", async () => {
    await openReader({materialId: 'browser-view-contract'});
    const request = pdf.requests.at(-1)!;
    expect(request.url).toContain('/api/reading/materials/browser-view-contract/render');
    expect(request.url).not.toContain('/raw');
    expect(request.withCredentials).toBe(true);
    expect(request.disableStream).toBe(true);
    expect(request.disableAutoFetch).toBe(true);
    expect(request.rangeChunkSize).toBe(1024 * 1024);
  });

  it("retries a failed load on the same source without losing the selected page", async () => {
    pdf.failures = 1;
    const view = render(<PdfDocumentView materialId="retry-source" unitCount={5}
      annotations={[]} jump={{locator: 5, nonce: 73}} onSelection={vi.fn()} />);
    await waitFor(() => expect(view.getByText('Temporary connection failure')).toBeTruthy());
    fireEvent.click(view.getByRole('button', {name: 'Retry'}));
    await waitFor(() => expect(view.container.querySelector('[data-reader-unit="5"]')).toBeTruthy());
    expect(view.queryByText('Temporary connection failure')).toBeNull();
    expect(pdf.requests).toHaveLength(2);
    expect(pdf.requests[1].url).toBe(pdf.requests[0].url);
  });

  it("ends a stalled load with a retry instead of an endless spinner", async () => {
    vi.useFakeTimers();
    pdf.stall = true;
    try {
      const view = render(<PdfDocumentView materialId="stalled-source" unitCount={5}
        annotations={[]} jump={null} onSelection={vi.fn()} />);
      await act(async () => { await Promise.resolve(); });
      await act(async () => { await vi.advanceTimersByTimeAsync(90_000); });
      expect(view.getByText('Opening the document timed out. Retry to continue.')).toBeTruthy();
      expect(view.getByRole('button', {name:'Retry'})).toBeTruthy();
      view.unmount();
    } finally { pdf.stall = false; vi.useRealTimers(); }
  });
});
