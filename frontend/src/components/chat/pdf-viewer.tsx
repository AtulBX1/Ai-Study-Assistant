"use client";

import {
  forwardRef,
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
import { downloadDocument, getDocumentPageImage } from "@/lib/documents";

export type PdfViewerHandle = {
  scrollToPage: (page: number) => void;
};

type PdfViewerProps = {
  documentId: number;
  pageCount: number | null;
};

function PdfPage({
  pdf,
  documentId,
  pageNumber,
  containerWidth,
  zoom,
  fallback,
  onVisible,
  onFailure,
}: {
  pdf: PDFDocumentProxy;
  documentId: number;
  pageNumber: number;
  containerWidth: number;
  zoom: number;
  fallback: boolean;
  onVisible: (page: number) => void;
  onFailure: (page: number) => void;
}) {
  const frame = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const textLayer = useRef<HTMLDivElement>(null);
  const [intersected, setIntersected] = useState(false);
  const [ratio, setRatio] = useState(0.77);
  const [fallbackUrl, setFallbackUrl] = useState<string | null>(null);
  const [fallbackError, setFallbackError] = useState<string | null>(null);

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
        </>
      )}
    </div>
  );
}

export const PdfViewer = forwardRef<PdfViewerHandle, PdfViewerProps>(
  function PdfViewer({ documentId, pageCount }, ref) {
    const scrollContainer = useRef<HTMLDivElement>(null);
    const pageNodes = useRef(new Map<number, HTMLDivElement>());
    const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
    const [totalPages, setTotalPages] = useState(pageCount ?? 1);
    const [currentPage, setCurrentPage] = useState(1);
    const [zoom, setZoom] = useState(1);
    const [containerWidth, setContainerWidth] = useState(720);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [fallbackAll, setFallbackAll] = useState(false);
    const [failedPages, setFailedPages] = useState<Set<number>>(() => new Set());

    useImperativeHandle(
      ref,
      () => ({
        scrollToPage(page) {
          const target = Math.min(Math.max(1, Math.floor(page)), totalPages);
          setCurrentPage(target);
          pageNodes.current.get(target)?.scrollIntoView({
            behavior: "smooth",
            block: "start",
          });
        },
      }),
      [totalPages],
    );

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
          setCurrentPage(1);
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
                  onVisible={onVisible}
                  onFailure={onFailure}
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
);

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
