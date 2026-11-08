"use client";

import {
  forwardRef,
  memo,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import type { KeyboardEvent } from "react";
import { Minus, Plus, ChevronLeft, ChevronRight, Maximize } from "lucide-react";
import type { PDFDocumentProxy, PDFPageProxy } from "pdfjs-dist";
import { Button } from "@/components/ui/button";
import { findPassageInTextLayer } from "@/lib/citation-matching";
import { downloadDocument, getDocumentPageImage } from "@/lib/documents";

export type SourceHighlight = {
  id: number;
  page: number;
  text: string;
};

export type PdfViewerHandle = {
  scrollToPage: (page: number) => void;
  scrollToSource: (page: number, text: string) => void;
  clearHighlight: () => void;
};

type PdfViewerProps = {
  documentId: number;
  pageCount: number | null;
};

export function SourcePassageBanner({
  page,
  text,
}: {
  page: number;
  text: string;
}) {
  return (
    <div
      role="status"
      className="border-b border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs"
    >
      <p className="font-semibold">Source passage</p>
      <p className="mt-1 text-muted-foreground">Page {page}</p>
      <p className="mt-1 whitespace-pre-wrap">{text}</p>
    </div>
  );
}

function PdfPage({
  pdf,
  documentId,
  pageNumber,
  containerWidth,
  zoom,
  fallback,
  highlight,
  onVisible,
  onFailure,
  onHighlightResult,
}: {
  pdf: PDFDocumentProxy;
  documentId: number;
  pageNumber: number;
  containerWidth: number;
  zoom: number;
  fallback: boolean;
  highlight: SourceHighlight | null;
  onVisible: (page: number) => void;
  onFailure: (page: number) => void;
  onHighlightResult: (page: number, matched: boolean) => void;
}) {
  const frame = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const textLayer = useRef<HTMLDivElement>(null);
  const [intersected, setIntersected] = useState(false);
  const [ratio, setRatio] = useState(0.77);
  const [fallbackUrl, setFallbackUrl] = useState<string | null>(null);
  const [fallbackError, setFallbackError] = useState<string | null>(null);
  const [textReady, setTextReady] = useState(false);
  const [highlightRects, setHighlightRects] = useState<
    Array<{ left: number; top: number; width: number; height: number }>
  >([]);

  useEffect(() => {
    const node = frame.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setIntersected(true);
          onVisible(pageNumber);
        }
      },
      { rootMargin: "0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [onVisible, pageNumber]);

  useEffect(() => {
    if (!fallback) return;
    const controller = new AbortController();
    let url: string | null = null;
    setFallbackError(null);
    void getDocumentPageImage(documentId, pageNumber, controller.signal)
      .then((blob) => {
        url = URL.createObjectURL(blob);
        setFallbackUrl(url);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setFallbackError(error instanceof Error ? error.message : "Page preview failed.");
        }
      });
    return () => {
      controller.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [documentId, fallback, pageNumber]);

  useEffect(() => {
    if (!intersected || fallback) return;
    let canceled = false;
    let renderTask: ReturnType<PDFPageProxy["render"]> | undefined;
    let textTask: { cancel: () => void; render: () => Promise<unknown> } | undefined;
    setTextReady(false);
    setHighlightRects([]);
    void (async () => {
      try {
        const page = await pdf.getPage(pageNumber);
        if (canceled) return;
        const baseViewport = page.getViewport({ scale: 1 });
        const scale = (Math.min(containerWidth, 1000) / baseViewport.width) * zoom;
        const viewport = page.getViewport({ scale });
        setRatio(viewport.width / viewport.height);
        const target = canvas.current;
        const textTarget = textLayer.current;
        if (!target || !textTarget) return;
        const pixelRatio = window.devicePixelRatio || 1;
        target.width = Math.ceil(viewport.width * pixelRatio);
        target.height = Math.ceil(viewport.height * pixelRatio);
        target.style.width = `${viewport.width}px`;
        target.style.height = `${viewport.height}px`;
        const context = target.getContext("2d");
        if (!context) throw new Error("The PDF canvas is unavailable.");
        renderTask = page.render({
          canvas: target,
          canvasContext: context,
          viewport: page.getViewport({ scale: scale * pixelRatio }),
        });
        await renderTask.promise;
        if (canceled) return;
        const textContent = await page.getTextContent();
        if (canceled) return;
        textTarget.replaceChildren();
        const { TextLayer } = await import("pdfjs-dist");
        textTask = new TextLayer({
          textContentSource: textContent,
          container: textTarget,
          viewport,
        });
        await textTask.render();
        if (!canceled) setTextReady(true);
      } catch {
        if (!canceled) onFailure(pageNumber);
      }
    })();
    return () => {
      canceled = true;
      renderTask?.cancel();
      textTask?.cancel();
    };
  }, [containerWidth, fallback, intersected, onFailure, pageNumber, pdf, zoom]);

  useEffect(() => {
    if (!highlight || highlight.page !== pageNumber) {
      setHighlightRects([]);
      return;
    }
    if (fallback) {
      setHighlightRects([]);
      onHighlightResult(pageNumber, false);
      return;
    }
    if (!textReady) return;
    const textTarget = textLayer.current;
    const frameTarget = frame.current;
    if (!textTarget || !frameTarget) return;
    const match = findPassageInTextLayer(textTarget, highlight.text);
    if (!match) {
      setHighlightRects([]);
      onHighlightResult(pageNumber, false);
      return;
    }
    const frameBounds = frameTarget.getBoundingClientRect();
    const rects = Array.from(match.range.getClientRects()).map((rect) => ({
      left: rect.left - frameBounds.left,
      top: rect.top - frameBounds.top,
      width: rect.width,
      height: rect.height,
    }));
    setHighlightRects(rects);
    match.range.startContainer.parentElement?.scrollIntoView({
      behavior: "smooth",
      block: "center",
    });
    onHighlightResult(pageNumber, true);
  }, [fallback, highlight, onHighlightResult, pageNumber, textReady]);

  return (
    <div
      ref={frame}
      data-page={pageNumber}
      className="relative mx-auto mb-4 w-full max-w-[1000px] overflow-hidden rounded border border-border bg-white shadow-sm"
      style={{ aspectRatio: `${ratio}` }}
      aria-label={`PDF page ${pageNumber}`}
    >
      {fallback ? (
        fallbackUrl ? (
          <img
            src={fallbackUrl}
            alt={`Page ${pageNumber} preview`}
            className="h-full w-full object-contain"
          />
        ) : (
          <p role={fallbackError ? "alert" : "status"} className="p-5 text-sm text-muted-foreground">
            {fallbackError ?? "Loading page image…"}
          </p>
        )
      ) : (
        <>
          <canvas ref={canvas} className="block h-full w-full" />
          <div
            ref={textLayer}
            className="textLayer absolute inset-0 select-text"
            aria-label={`Selectable text on page ${pageNumber}`}
          />
          <div className="pointer-events-none absolute inset-0" aria-hidden="true">
            {highlightRects.map((rect, index) => (
              <span
                key={`${index}-${highlight?.id ?? 0}`}
                className="absolute rounded-sm bg-yellow-300/70 outline outline-1 outline-yellow-500/60"
                style={rect}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export const PdfViewer = memo(forwardRef<PdfViewerHandle, PdfViewerProps>(
  function PdfViewer({ documentId, pageCount }, ref) {
    const scrollContainer = useRef<HTMLDivElement>(null);
    const pageNodes = useRef(new Map<number, HTMLDivElement>());
    const pendingPageScroll = useRef<number | null>(null);
    const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
    const [totalPages, setTotalPages] = useState(pageCount ?? 1);
    const [currentPage, setCurrentPage] = useState(1);
    const [zoom, setZoom] = useState(1);
    const [containerWidth, setContainerWidth] = useState(720);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [fallbackAll, setFallbackAll] = useState(false);
    const [failedPages, setFailedPages] = useState<Set<number>>(() => new Set());
    const [highlight, setHighlight] = useState<SourceHighlight | null>(null);
    const [sourceBanner, setSourceBanner] = useState<SourceHighlight | null>(null);
    const highlightSequence = useRef(0);

    useImperativeHandle(
      ref,
      () => ({
        scrollToPage(page) {
          const target = Math.min(Math.max(1, Math.floor(page)), totalPages);
          setCurrentPage(target);
          const targetNode = pageNodes.current.get(target);
          if (targetNode) {
            pendingPageScroll.current = null;
            targetNode.scrollIntoView({ behavior: "smooth", block: "start" });
          } else {
            pendingPageScroll.current = target;
          }
        },
        scrollToSource(page, text) {
          const target = Math.min(Math.max(1, Math.floor(page)), totalPages);
          if (highlight?.page === target && highlight.text === text) {
            setHighlight(null);
            setSourceBanner(null);
            return;
          }
          const next = { id: ++highlightSequence.current, page: target, text };
          setHighlight(next);
          setSourceBanner(null);
          setCurrentPage(target);
          const targetNode = pageNodes.current.get(target);
          if (targetNode) {
            pendingPageScroll.current = null;
            targetNode.scrollIntoView({ behavior: "smooth", block: "start" });
          } else {
            pendingPageScroll.current = target;
          }
        },
        clearHighlight() {
          setHighlight(null);
          setSourceBanner(null);
        },
      }),
      [highlight, totalPages],
    );

    useEffect(() => {
      const target = pendingPageScroll.current;
      if (!pdf || target === null) return;
      const targetNode = pageNodes.current.get(target);
      if (!targetNode) return;
      pendingPageScroll.current = null;
      targetNode.scrollIntoView({ behavior: "smooth", block: "start" });
    }, [pdf]);

    useEffect(() => {
      const element = scrollContainer.current;
      if (!element) return;
      const observer = new ResizeObserver(([entry]) => {
        setContainerWidth(Math.max(320, entry.contentRect.width - 24));
      });
      observer.observe(element);
      return () => observer.disconnect();
    }, []);

    useEffect(() => {
      let canceled = false;
      let loadingTask:
        | ReturnType<typeof import("pdfjs-dist").getDocument>
        | undefined;
      let blobUrl: string | null = null;
      setLoading(true);
      setError(null);
      setPdf(null);
      setFallbackAll(false);
      void (async () => {
        try {
          const [pdfjs, blob] = await Promise.all([
            import("pdfjs-dist"),
            downloadDocument(documentId),
          ]);
          if (canceled) return;
          pdfjs.GlobalWorkerOptions.workerSrc = new URL(
            "pdfjs-dist/build/pdf.worker.min.mjs",
            import.meta.url,
          ).toString();
          blobUrl = URL.createObjectURL(blob);
          loadingTask = pdfjs.getDocument({ url: blobUrl });
          const loaded = await loadingTask.promise;
          if (canceled) {
            await loadingTask.destroy();
            return;
          }
          setPdf(loaded);
          setTotalPages(loaded.numPages);
        } catch (caught) {
          if (!canceled) {
            setFallbackAll(true);
            setError(
              caught instanceof Error ? caught.message : "Could not render the PDF.",
            );
            setTotalPages(Math.max(1, pageCount ?? 1));
          }
        } finally {
          if (!canceled) setLoading(false);
        }
      })();
      return () => {
        canceled = true;
        if (blobUrl) URL.revokeObjectURL(blobUrl);
        void loadingTask?.destroy();
      };
    }, [documentId, pageCount]);

    const onVisible = useCallback((page: number) => {
      setCurrentPage(page);
    }, []);
    const onFailure = useCallback((page: number) => {
      setFailedPages((pages) => new Set(pages).add(page));
    }, []);
    const onHighlightResult = useCallback(
      (page: number, matched: boolean) => {
        if (matched || !highlight || highlight.page !== page) return;
        setSourceBanner(highlight);
      },
      [highlight],
    );
    const changePage = (page: number) => {
      const target = Math.min(totalPages, Math.max(1, page));
      setCurrentPage(target);
      document.getElementById(`pdf-page-${target}`)?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    };
    const handleKeys = (event: KeyboardEvent<HTMLDivElement>) => {
      if (event.target instanceof HTMLInputElement) return;
      if (event.key === "ArrowRight" || event.key === "PageDown") {
        event.preventDefault();
        changePage(currentPage + 1);
      } else if (event.key === "ArrowLeft" || event.key === "PageUp") {
        event.preventDefault();
        changePage(currentPage - 1);
      }
    };

    return (
      <section
        aria-label="PDF viewer"
        className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-border bg-card"
        onClick={(event) => {
          if (!(event.target instanceof HTMLElement && event.target.closest("[data-keep-pdf-highlight]"))) {
            setHighlight(null);
            setSourceBanner(null);
          }
        }}
      >
        <div className="flex flex-wrap items-center justify-center gap-2 border-b border-border p-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            aria-label="Previous page"
            disabled={currentPage <= 1}
            onClick={() => changePage(currentPage - 1)}
          >
            <ChevronLeft size={16} aria-hidden="true" />
          </Button>
          <label className="flex items-center gap-1 text-sm">
            <input
              aria-label="Current page"
              type="number"
              min={1}
              max={totalPages}
              value={currentPage}
              onChange={(event) => {
                const page = Number(event.target.value);
                if (Number.isInteger(page)) changePage(page);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") changePage(Number(event.currentTarget.value));
              }}
              className="h-8 w-14 rounded border border-border bg-background px-2 text-center"
            />
            <span>of {totalPages}</span>
          </label>
          <Button
            type="button"
            size="sm"
            variant="outline"
            aria-label="Next page"
            disabled={currentPage >= totalPages}
            onClick={() => changePage(currentPage + 1)}
          >
            <ChevronRight size={16} aria-hidden="true" />
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            aria-label="Zoom out"
            onClick={() => setZoom((value) => Math.max(0.5, value - 0.1))}
          >
            <Minus size={16} aria-hidden="true" />
          </Button>
          <span className="min-w-12 text-center text-xs">{Math.round(zoom * 100)}%</span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            aria-label="Zoom in"
            onClick={() => setZoom((value) => Math.min(2, value + 0.1))}
          >
            <Plus size={16} aria-hidden="true" />
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            aria-label="Fit width"
            onClick={() => setZoom(1)}
          >
            <Maximize size={16} aria-hidden="true" />
          </Button>
        </div>
        {loading ? (
          <p role="status" className="p-4 text-sm text-muted-foreground">
            Loading PDF…
          </p>
        ) : null}
        {error ? (
          <p role="status" className="px-4 pt-3 text-xs text-muted-foreground">
            PDF preview unavailable; trying the page image service. {error}
          </p>
        ) : null}
        {sourceBanner ? (
          <SourcePassageBanner page={sourceBanner.page} text={sourceBanner.text} />
        ) : null}
        <div
          ref={scrollContainer}
          tabIndex={0}
          onKeyDown={handleKeys}
          className="min-h-0 flex-1 overflow-auto bg-muted/40 p-3"
          aria-label="PDF pages. Use left and right arrow keys to navigate."
        >
          {pdf ? (
            Array.from({ length: totalPages }, (_, index) => index + 1).map((page) => (
              <div
                id={`pdf-page-${page}`}
                key={page}
                ref={(node) => {
                  if (node) pageNodes.current.set(page, node);
                  else pageNodes.current.delete(page);
                }}
              >
                <PdfPage
                  pdf={pdf}
                  documentId={documentId}
                  pageNumber={page}
                  containerWidth={containerWidth}
                  zoom={zoom}
                  fallback={failedPages.has(page)}
                  highlight={highlight}
                  onVisible={onVisible}
                  onFailure={onFailure}
                  onHighlightResult={onHighlightResult}
                />
              </div>
            ))
          ) : fallbackAll ? (
            <FallbackPage
              documentId={documentId}
              pageNumber={currentPage}
              pageCount={totalPages}
            />
          ) : null}
        </div>
      </section>
    );
  },
));

function FallbackPage({
  documentId,
  pageNumber,
  pageCount,
}: {
  documentId: number;
  pageNumber: number;
  pageCount: number;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | null = null;
    setUrl(null);
    setError(null);
    void getDocumentPageImage(documentId, pageNumber, controller.signal)
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setError(caught instanceof Error ? caught.message : "Page preview failed.");
        }
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [documentId, pageNumber]);
  return (
    <div className="mx-auto max-w-3xl">
      {url ? (
        <img
          src={url}
          alt={`Page ${pageNumber} preview`}
          className="w-full bg-white shadow"
        />
      ) : error ? (
        <p role="alert" className="p-5 text-sm text-danger">
          Could not load page {pageNumber}: {error}
        </p>
      ) : (
        <p role="status" className="p-5 text-sm text-muted-foreground">
          Loading page image…
        </p>
      )}
      <span className="sr-only">
        Page {pageNumber} of {pageCount}
      </span>
    </div>
  );
}
