import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PdfViewer, type PdfViewerHandle } from "@/components/chat/pdf-viewer";

const mocks = vi.hoisted(() => ({
  getDocument: vi.fn(),
  getPage: vi.fn(),
}));
const originalScrollIntoView = Object.getOwnPropertyDescriptor(
  Element.prototype,
  "scrollIntoView",
);

vi.mock("@/lib/documents", () => ({
  downloadDocument: vi.fn(async () => new Blob(["mock pdf"])),
  getDocumentPageImage: vi.fn(async () => new Blob(["mock image"])),
}));

vi.mock("pdfjs-dist", () => ({
  GlobalWorkerOptions: {},
  getDocument: mocks.getDocument,
  TextLayer: class {
    private readonly container: HTMLElement;
    constructor({ container }: { container: HTMLElement }) {
      this.container = container;
    }
    async render() {
      const span = document.createElement("span");
      span.textContent = "Text layer has unrelated contents.";
      this.container.append(span);
    }
    cancel() {}
  },
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  if (originalScrollIntoView) {
    Object.defineProperty(Element.prototype, "scrollIntoView", originalScrollIntoView);
  } else {
    Reflect.deleteProperty(Element.prototype, "scrollIntoView");
  }
});

describe("PDF citation feedback", () => {
  it("jumps to the page and shows the source banner when the mocked text layer has no match", async () => {
    const pdf = { numPages: 1, getPage: mocks.getPage };
    mocks.getDocument.mockReturnValue({
      promise: Promise.resolve(pdf),
      destroy: vi.fn(),
    });
    mocks.getPage.mockResolvedValue({
      getViewport: ({ scale }: { scale: number }) => ({
        width: 612 * scale,
        height: 792 * scale,
      }),
      render: () => ({ promise: Promise.resolve(), cancel: vi.fn() }),
      getTextContent: async () => ({ items: [] }),
    });
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(private readonly callback: (entries: Array<{ isIntersecting: boolean }>) => void) {}
        observe() {
          this.callback([{ isIntersecting: true }]);
        }
        disconnect() {}
      },
    );
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(private readonly callback: (entries: Array<{ contentRect: { width: number } }>) => void) {}
        observe() {
          this.callback([{ contentRect: { width: 720 } }]);
        }
        disconnect() {}
      },
    );
    vi.stubGlobal(
      "URL",
      Object.assign(class extends globalThis.URL {}, {
        createObjectURL: () => "blob:mock-pdf",
        revokeObjectURL: vi.fn(),
      }),
    );
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
      {} as CanvasRenderingContext2D,
    );
    Object.defineProperty(Element.prototype, "scrollIntoView", {
      configurable: true,
      value: vi.fn(),
    });

    const viewer = createRef<PdfViewerHandle>();
    render(<PdfViewer ref={viewer} documentId={42} pageCount={1} />);
    await screen.findByText("Text layer has unrelated contents.");
    await waitFor(() => expect(mocks.getPage).toHaveBeenCalled());

    act(() => viewer.current?.scrollToSource(1, "The quoted source evidence is missing."));
    expect(await screen.findByText("Source passage")).toBeTruthy();
    expect(screen.getByText("Page 1")).toBeTruthy();
    expect(screen.getByText("The quoted source evidence is missing.")).toBeTruthy();
  });
});
