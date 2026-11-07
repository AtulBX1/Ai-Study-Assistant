"use client";

import Link from "next/link";
import {
  ArrowDownToLine,
  ArrowUpDown,
  CheckCircle2,
  FileText,
  LoaderCircle,
  LockKeyhole,
  MoreHorizontal,
  RefreshCw,
  Search,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import {
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import {
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type Dispatch,
  type DragEvent,
  type KeyboardEvent,
  type SetStateAction,
} from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import {
  DOCUMENT_PAGE_SIZE,
  deleteDocument,
  downloadDocument,
  listDocuments,
  reindexDocument,
  type DocumentRecord,
} from "@/lib/documents";
import {
  estimatePdfPageCount,
  fileIdentity,
  MAX_PDF_PAGES,
  validatePdfFiles,
  uploadPdf,
} from "@/lib/document-upload";
import { useDocumentStatus } from "@/lib/hooks/use-document-status";

type Candidate = {
  id: string;
  file: File;
  isPrivate: boolean;
  error?: string;
};

type UploadTask = {
  id: string;
  title: string;
  progress: number;
  state: "uploading" | "canceled" | "uploaded" | "error";
  error?: string;
};

const terminal = new Set(["ready", "failed"]);
const statusLabels: Record<string, string> = {
  queued: "Queued",
  extracting: "Extracting",
  processing: "Processing",
  indexing: "Indexing",
  ready: "Ready",
  failed: "Failed",
};

function createdLabel(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Date unavailable"
    : new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date);
}

function PrivacyLabel({ isPrivate }: { isPrivate?: boolean }) {
  return isPrivate === undefined ? (
    <Badge title="This API does not return a document privacy flag.">
      Privacy unavailable
    </Badge>
  ) : (
    <Badge>
      {isPrivate ? (
        <LockKeyhole className="mr-1" size={12} aria-hidden="true" />
      ) : null}
      {isPrivate ? "Private" : "Not private"}
    </Badge>
  );
}

function StatusSummary({ document }: { document: DocumentRecord }) {
  const value = statusLabels[document.status] ?? document.status;
  return (
    <div aria-live="polite" className="min-w-32">
      <div className="mb-1 flex items-center justify-between gap-2">
        <Badge
          className={
            document.status === "ready"
              ? "border-accent/30 text-accent"
              : document.status === "failed"
                ? "border-danger/30 text-danger"
                : ""
          }
        >
          {document.status === "ready" ? (
            <CheckCircle2 className="mr-1" size={12} aria-hidden="true" />
          ) : null}
          {value}
        </Badge>
        {!terminal.has(document.status) ? (
          <span className="text-xs text-muted-foreground">{document.progress}%</span>
        ) : null}
      </div>
      {!terminal.has(document.status) ? (
        <progress
          className="h-1.5 w-full accent-primary"
          max={100}
          value={document.progress}
          aria-label={`${value} progress`}
        />
      ) : null}
      {document.status === "failed" && document.error_message ? (
        <p className="mt-1 max-w-xs text-xs text-danger">{document.error_message}</p>
      ) : null}
    </div>
  );
}

function DocumentStatus({ initial }: { initial: DocumentRecord }) {
  const { document, streamError, pollingError } = useDocumentStatus(initial);
  return (
    <div className="space-y-1">
      <StatusSummary document={document} />
      {streamError ? (
        <p className="text-xs text-muted-foreground">
          Reconnecting with status checks…
        </p>
      ) : null}
      {pollingError ? (
        <p className="text-xs text-danger" role="status">
          Status check failed: {pollingError.message}
        </p>
      ) : null}
    </div>
  );
}

function UploadDropzone({
  onFiles,
}: {
  onFiles: (files: File[]) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const openPicker = () => inputRef.current?.click();
  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    onFiles(Array.from(event.dataTransfer.files));
  };
  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openPicker();
    }
  };
  const handleInput = (event: ChangeEvent<HTMLInputElement>) => {
    onFiles(Array.from(event.target.files ?? []));
    event.target.value = "";
  };

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label="Choose PDF files or drop them here"
      onClick={openPicker}
      onKeyDown={handleKeyDown}
      onDragEnter={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={(event) => {
        if (event.currentTarget === event.target) setDragging(false);
      }}
      onDrop={handleDrop}
      className={`rounded-xl border-2 border-dashed p-6 text-center transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary sm:p-8 ${
        dragging ? "border-primary bg-primary/5" : "border-border bg-card"
      }`}
    >
      <input
        ref={inputRef}
        className="sr-only"
        type="file"
        accept="application/pdf,.pdf"
        multiple
        aria-label="Choose PDF files"
        onChange={handleInput}
      />
      <span className="mx-auto mb-3 grid size-11 place-items-center rounded-full bg-primary/10 text-primary">
        <Upload size={20} aria-hidden="true" />
      </span>
      <p className="font-medium">Drag your PDFs here</p>
      <p className="mt-1 text-sm text-muted-foreground">
        or choose files from your device · PDF up to 20 MB
      </p>
      <Button
        type="button"
        variant="outline"
        className="mt-4"
        onClick={(event) => {
          event.stopPropagation();
          openPicker();
        }}
      >
        Choose PDFs
      </Button>
      <p className="sr-only">
        Use Enter or Space to open the file picker. Maximum PDF length is{" "}
        {MAX_PDF_PAGES} pages.
      </p>
    </div>
  );
}

function UploadQueue({
  candidates,
  setCandidates,
  tasks,
  setTasks,
  onUploaded,
}: {
  candidates: Candidate[];
  setCandidates: Dispatch<SetStateAction<Candidate[]>>;
  tasks: UploadTask[];
  setTasks: Dispatch<SetStateAction<UploadTask[]>>;
  onUploaded: () => void;
}) {
  const controllers = useRef(new Map<string, AbortController>());

  const queueFiles = (files: File[]) => {
    const identities = new Set(candidates.map(({ file }) => fileIdentity(file)));
    const { accepted, rejected } = validatePdfFiles(files, identities);
    setCandidates((current) => [
      ...current,
      ...accepted.map((file) => ({
        id: `${fileIdentity(file)}-${crypto.randomUUID()}`,
        file,
        isPrivate: true,
      })),
    ]);
    if (rejected.length) {
      toast.error(
        rejected.map(({ file, message }) => `${file.name}: ${message}`).join("\n"),
      );
    }
  };

  const togglePrivacy = (id: string, isPrivate: boolean) => {
    setCandidates((current) =>
      current.map((candidate) =>
        candidate.id === id ? { ...candidate, isPrivate } : candidate,
      ),
    );
  };

  const uploadOne = async (candidate: Candidate) => {
    if (candidate.isPrivate) {
      setCandidates((current) =>
        current.map((item) =>
          item.id === candidate.id
            ? {
                ...item,
                error:
                  "The current API cannot save a private flag. Uncheck Private only if you accept this document being treated as non-private.",
              }
            : item,
        ),
      );
      return;
    }
    const controller = new AbortController();
    controllers.current.set(candidate.id, controller);
    setTasks((current) => [
      ...current.filter((task) => task.id !== candidate.id),
      {
        id: candidate.id,
        title: candidate.file.name,
        progress: 0,
        state: "uploading",
      },
    ]);
    try {
      const pageCount = await estimatePdfPageCount(candidate.file);
      if (pageCount !== null && pageCount > MAX_PDF_PAGES) {
        throw new Error(
          `This PDF has more than the ${MAX_PDF_PAGES}-page limit.`,
        );
      }
      const document = await uploadPdf(candidate.file, {
        signal: controller.signal,
        onProgress: (progress) =>
          setTasks((current) =>
            current.map((task) =>
              task.id === candidate.id ? { ...task, progress } : task,
            ),
          ),
      });
      setTasks((current) =>
        current.map((task) =>
          task.id === candidate.id
            ? { ...task, progress: 100, state: "uploaded" }
            : task,
        ),
      );
      setCandidates((current) =>
        current.filter((item) => item.id !== candidate.id),
      );
      toast.success(`${document.title} uploaded. Ingestion is starting.`);
      onUploaded();
    } catch (error) {
      const canceled =
        error instanceof DOMException && error.name === "AbortError";
      setTasks((current) =>
        current.map((task) =>
          task.id === candidate.id
            ? {
                ...task,
                state: canceled ? "canceled" : "error",
                ...(canceled
                  ? {}
                  : {
                      error:
                        error instanceof Error
                          ? error.message
                          : "Upload failed.",
                    }),
              }
            : task,
        ),
      );
    } finally {
      controllers.current.delete(candidate.id);
    }
  };

  const removeCandidate = (id: string) => {
    setCandidates((current) =>
      current.filter((candidate) => candidate.id !== id),
    );
  };

  return (
    <div className="space-y-4">
      <UploadDropzone onFiles={queueFiles} />
      {candidates.length ? (
        <ul className="space-y-3" aria-label="Files waiting to upload">
          {candidates.map((candidate) => (
            <li
              key={candidate.id}
              className="rounded-lg border border-border bg-card p-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate font-medium">{candidate.file.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {(candidate.file.size / 1024 / 1024).toFixed(2)} MB · The
                    server enforces the {MAX_PDF_PAGES}-page limit; local page
                    counting is best effort.
                  </p>
                  <label className="mt-3 flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={candidate.isPrivate}
                      onChange={(event) =>
                        togglePrivacy(candidate.id, event.target.checked)
                      }
                      aria-describedby={`privacy-note-${candidate.id}`}
                      className="size-4 accent-primary focus-visible:ring-2 focus-visible:ring-primary"
                    />
                    Private
                    <span
                      id={`privacy-note-${candidate.id}`}
                      title="Private documents should never be sent to online AI providers."
                      className="cursor-help text-xs text-muted-foreground underline decoration-dotted"
                    >
                      Why?
                    </span>
                  </label>
                  <p className="mt-1 text-xs text-danger" role="status">
                    {candidate.isPrivate
                      ? "Private upload is unavailable: the current upload API has no privacy field. The file will not be sent while this is checked."
                      : "The backend does not currently store a privacy flag; this upload will be non-private."}
                  </p>
                  {candidate.error ? (
                    <p className="mt-1 text-xs text-danger" role="alert">
                      {candidate.error}
                    </p>
                  ) : null}
                </div>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    size="sm"
                    disabled={candidate.isPrivate}
                    onClick={() => void uploadOne(candidate)}
                  >
                    Upload PDF
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={`Remove ${candidate.file.name}`}
                    onClick={() => removeCandidate(candidate.id)}
                  >
                    <X size={16} aria-hidden="true" />
                  </Button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      ) : null}
      {tasks.length ? (
        <ul className="space-y-2" aria-live="polite" aria-label="Upload progress">
          {tasks.map((task) => (
            <li
              key={task.id}
              className="flex items-center gap-3 rounded-lg border border-border bg-card p-3"
            >
              {task.state === "uploading" ? (
                <LoaderCircle
                  size={17}
                  className="animate-spin text-primary"
                  aria-hidden="true"
                />
              ) : (
                <FileText size={17} className="text-primary" aria-hidden="true" />
              )}
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{task.title}</p>
                <p className="text-xs text-muted-foreground">
                  {task.error ?? `${task.state} · ${task.progress}%`}
                </p>
                {task.state === "uploading" ? (
                  <progress
                    className="mt-1 h-1.5 w-full accent-primary"
                    max={100}
                    value={task.progress}
                    aria-label={`${task.title} upload progress`}
                  />
                ) : null}
              </div>
              {task.state === "uploading" ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => controllers.current.get(task.id)?.abort()}
                >
                  Cancel
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      <p className="sr-only" aria-live="polite">
        {tasks
          .filter((task) => task.state !== "uploading")
          .map((task) => `${task.title}: ${task.state}`)
          .join(". ")}
      </p>
    </div>
  );
}

function DocumentCard({
  document,
  onDelete,
}: {
  document: DocumentRecord;
  onDelete: (document: DocumentRecord) => void;
}) {
  const [reindexing, setReindexing] = useState(false);
  const [downloading, setDownloading] = useState(false);

  const handleReindex = async () => {
    setReindexing(true);
    try {
      await reindexDocument(document.id);
      toast.success("Document reindexed.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Reindex failed.");
    } finally {
      setReindexing(false);
    }
  };

  const handleDownload = async () => {
    setDownloading(true);
    try {
      const blob = await downloadDocument(document.id);
      const url = URL.createObjectURL(blob);
      const anchor = window.document.createElement("a");
      anchor.href = url;
      anchor.download = document.title;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Download failed.");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <Card>
      <CardContent className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center">
        <span className="grid size-11 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
          <FileText size={20} aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <Link
            href={`/library/${document.id}`}
            className="font-medium underline-offset-4 hover:text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            {document.title}
          </Link>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span>{document.page_count ?? "—"} pages</span>
            <span>Uploaded {createdLabel(document.created_at)}</span>
            <PrivacyLabel isPrivate={document.is_private} />
          </div>
          {document.status === "failed" && document.error_message ? (
            <p className="mt-2 text-sm text-danger" role="alert">
              {document.error_message}
            </p>
          ) : null}
        </div>
        <DocumentStatus initial={document} />
        {document.status === "failed" ? (
          <Button
            type="button"
            variant="outline"
            className="text-danger"
            onClick={() => onDelete(document)}
          >
            Delete failed document
          </Button>
        ) : null}
        <details className="relative self-end sm:self-center">
          <summary
            aria-label={`Actions for ${document.title}`}
            className="grid size-10 cursor-pointer list-none place-items-center rounded-md text-muted-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary [&::-webkit-details-marker]:hidden"
          >
            <MoreHorizontal size={19} aria-hidden="true" />
          </summary>
          <div className="absolute right-0 z-10 mt-1 flex min-w-48 flex-col rounded-lg border border-border bg-card p-1 shadow-lg">
            <Button
              type="button"
              variant="ghost"
              className="justify-start"
              disabled={downloading}
              onClick={() => void handleDownload()}
            >
              <ArrowDownToLine size={16} aria-hidden="true" />
              Download original
            </Button>
            <Button
              type="button"
              variant="ghost"
              className="justify-start"
              disabled={reindexing || document.status !== "ready"}
              onClick={() => void handleReindex()}
            >
              <RefreshCw size={16} aria-hidden="true" />
              {reindexing ? "Reindexing…" : "Reindex"}
            </Button>
            <p className="px-3 py-2 text-xs text-muted-foreground">
              Privacy cannot be changed because the API does not support it yet.
            </p>
            <Button
              type="button"
              variant="ghost"
              className="justify-start text-danger hover:text-danger"
              onClick={() => onDelete(document)}
            >
              <Trash2 size={16} aria-hidden="true" />
              Delete
            </Button>
          </div>
        </details>
      </CardContent>
    </Card>
  );
}

export function DocumentLibrary() {
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<"newest" | "title">("newest");
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [tasks, setTasks] = useState<UploadTask[]>([]);
  const [deleteTarget, setDeleteTarget] = useState<DocumentRecord | null>(null);
  const queryClient = useQueryClient();

  const documentsQuery = useInfiniteQuery({
    queryKey: ["documents"],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => listDocuments(pageParam, DOCUMENT_PAGE_SIZE),
    getNextPageParam: (lastPage, pages) =>
      lastPage.length === DOCUMENT_PAGE_SIZE
        ? pages.length * DOCUMENT_PAGE_SIZE
        : undefined,
  });

  const deleteMutation = useMutation({
    mutationFn: deleteDocument,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
      setDeleteTarget(null);
      toast.success("Document and its study data were deleted.");
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "Could not delete document."),
  });

  const documents = useMemo(() => {
    const loaded = documentsQuery.data?.pages.flat() ?? [];
    const filtered = loaded.filter((document) =>
      document.title.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()),
    );
    return filtered.sort((first, second) =>
      sort === "title"
        ? first.title.localeCompare(second.title)
        : new Date(second.created_at).getTime() -
          new Date(first.created_at).getTime(),
    );
  }, [documentsQuery.data, search, sort]);

  return (
    <>
      <PageHeader
        title="Library"
        description="Keep your course PDFs together. Documents are private to your account."
      />
      <section aria-labelledby="upload-heading" className="mb-8 space-y-4">
        <h2 id="upload-heading" className="text-lg font-semibold">
          Upload documents
        </h2>
        <UploadQueue
          candidates={candidates}
          setCandidates={setCandidates}
          tasks={tasks}
          setTasks={setTasks}
          onUploaded={() => {
            void queryClient.invalidateQueries({ queryKey: ["documents"] });
          }}
        />
      </section>
      <section aria-labelledby="documents-heading">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 id="documents-heading" className="text-lg font-semibold">
            Your documents
          </h2>
          <div className="flex flex-wrap items-center gap-2">
            <label className="relative">
              <span className="sr-only">Search documents by title</span>
              <Search
                size={16}
                aria-hidden="true"
                className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
              />
              <Input
                type="search"
                placeholder="Search title"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                className="w-52 pl-9"
              />
            </label>
            <label className="flex items-center gap-2 text-sm">
              <ArrowUpDown size={16} aria-hidden="true" />
              <span className="sr-only">Sort documents</span>
              <select
                aria-label="Sort documents"
                value={sort}
                onChange={(event) =>
                  setSort(event.target.value as "newest" | "title")
                }
                className="h-11 rounded-md border border-border bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >
                <option value="newest">Newest first</option>
                <option value="title">Title A–Z</option>
              </select>
            </label>
          </div>
        </div>
        {documentsQuery.isLoading ? (
          <div className="space-y-3" aria-label="Loading documents">
            {Array.from({ length: 3 }, (_, index) => (
              <Skeleton key={index} className="h-24 w-full" />
            ))}
          </div>
        ) : documentsQuery.isError ? (
          <ErrorState
            title="Could not load your library"
            description={
              documentsQuery.error instanceof Error
                ? documentsQuery.error.message
                : "Try loading your documents again."
            }
            action={
              <Button
                type="button"
                variant="outline"
                onClick={() => void documentsQuery.refetch()}
              >
                Try again
              </Button>
            }
          />
        ) : documents.length === 0 ? (
          <EmptyState
            title={search ? "No matching documents" : "Your library is empty"}
            description={
              search
                ? "Try another title or clear your search."
                : "Upload your first PDF to start building your study space."
            }
            action={
              search ? (
                <Button variant="outline" onClick={() => setSearch("")}>
                  Clear search
                </Button>
              ) : (
                <Button onClick={() => documentUploadFocus()}>
                  Upload your first PDF
                </Button>
              )
            }
          />
        ) : (
          <div className="space-y-3">
            {documents.map((document) => (
              <DocumentCard
                key={document.id}
                document={document}
                onDelete={setDeleteTarget}
              />
            ))}
            {documentsQuery.hasNextPage ? (
              <div className="pt-3 text-center">
                <Button
                  type="button"
                  variant="outline"
                  disabled={documentsQuery.isFetchingNextPage}
                  onClick={() => void documentsQuery.fetchNextPage()}
                >
                  {documentsQuery.isFetchingNextPage
                    ? "Loading…"
                    : "Load more documents"}
                </Button>
              </div>
            ) : null}
          </div>
        )}
      </section>
      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open && !deleteMutation.isPending) setDeleteTarget(null);
        }}
        title="Delete this document?"
      >
        <p className="text-sm leading-6 text-muted-foreground">
          Deleting <strong className="text-foreground">{deleteTarget?.title}</strong>{" "}
          also removes its chunks, summaries, flashcards, and quiz data. This
          cannot be undone.
        </p>
        <div className="mt-6 flex justify-end gap-3">
          <Button
            type="button"
            variant="outline"
            onClick={() => setDeleteTarget(null)}
            disabled={deleteMutation.isPending}
          >
            Cancel
          </Button>
          <Button
            type="button"
            className="bg-danger text-white hover:bg-danger/90"
            disabled={deleteMutation.isPending || !deleteTarget}
            onClick={() => {
              if (deleteTarget) deleteMutation.mutate(deleteTarget.id);
            }}
          >
            {deleteMutation.isPending ? "Deleting…" : "Delete document"}
          </Button>
        </div>
      </Dialog>
    </>
  );
}

function documentUploadFocus() {
  document
    .querySelector<HTMLElement>('[aria-label="Choose PDF files or drop them here"]')
    ?.focus();
}
