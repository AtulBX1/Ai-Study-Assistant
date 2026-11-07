"use client";

import Link from "next/link";
import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useState } from "react";
import {
  ArrowDownToLine,
  ArrowLeft,
  BookOpenText,
  FileText,
  MessageSquareText,
  RefreshCw,
  Sparkles,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs } from "@/components/ui/tabs";
import {
  deleteDocument,
  downloadDocument,
  getDocument,
  getDocumentKeyTerms,
  getDocumentPage,
  reindexDocument,
  type DocumentRecord,
} from "@/lib/documents";
import { useDocumentStatus } from "@/lib/hooks/use-document-status";

const terminal = new Set(["ready", "failed"]);

function PrivateFlag({ document }: { document: DocumentRecord }) {
  return (
    <Badge title="The current API does not include document privacy in its response.">
      {document.is_private === undefined
        ? "Privacy unavailable"
        : document.is_private
          ? "Private"
          : "Not private"}
    </Badge>
  );
}

function DocumentOverview({ id }: { id: number }) {
  const terms = useQuery({
    queryKey: ["document-terms", id],
    queryFn: () => getDocumentKeyTerms(id),
  });

  if (terms.isLoading) {
    return <Skeleton className="h-40 w-full" aria-label="Loading key terms" />;
  }
  if (terms.isError) {
    return (
      <ErrorState
        title="Could not load key terms"
        description={terms.error.message}
      />
    );
  }
  if (!terms.data?.length) {
    return (
      <EmptyState
        title="No key terms yet"
        description="Terms and their source pages will appear here when available."
      />
    );
  }
  return (
    <ul className="divide-y divide-border rounded-lg border border-border">
      {terms.data.map((item, index) => (
        <li key={`${item.term}-${item.page}-${index}`} className="p-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="font-medium">{item.term}</p>
              {item.definition ? (
                <p className="mt-1 text-sm leading-6 text-muted-foreground">
                  {item.definition}
                </p>
              ) : null}
            </div>
            <Badge>Page {item.page}</Badge>
          </div>
        </li>
      ))}
    </ul>
  );
}

function DocumentPages({ document }: { document: DocumentRecord }) {
  const pageSize = 5;
  const pages = useInfiniteQuery({
    queryKey: ["document-pages", document.id],
    initialPageParam: 1,
    queryFn: ({ pageParam }) =>
      Promise.all(
        Array.from(
          {
            length: Math.min(
              pageSize,
              Math.max(0, (document.page_count ?? 0) - pageParam + 1),
            ),
          },
          (_, index) => getDocumentPage(document.id, pageParam + index),
        ),
      ),
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.flat().length;
      return loaded < (document.page_count ?? 0) ? loaded + 1 : undefined;
    },
    enabled: (document.page_count ?? 0) > 0,
  });
  const loadedPages = pages.data?.pages.flat() ?? [];

  if (!document.page_count) {
    return (
      <EmptyState
        title="No pages available yet"
        description="Page previews become available after extraction is complete."
      />
    );
  }
  if (pages.isError) {
    return (
      <ErrorState title="Could not load pages" description={pages.error.message} />
    );
  }
  return (
    <div className="space-y-4">
      {pages.isLoading
        ? Array.from({ length: Math.min(pageSize, document.page_count) }, (_, index) => (
            <Skeleton key={index} className="h-28 w-full" />
          ))
        : loadedPages.map((page) => (
            <Card key={page.page_number}>
              <CardContent className="p-4">
                <h3 className="font-medium">Page {page.page_number}</h3>
                <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
                  {page.text.trim()
                    ? `${page.text.slice(0, 1000)}${page.text.length > 1000 ? "…" : ""}`
                    : "No text preview is available for this page."}
                </p>
              </CardContent>
            </Card>
          ))}
      {pages.hasNextPage ? (
        <Button
          type="button"
          variant="outline"
          disabled={pages.isFetchingNextPage}
          onClick={() => void pages.fetchNextPage()}
        >
          {pages.isFetchingNextPage ? "Loading pages…" : "Load more pages"}
        </Button>
      ) : null}
    </div>
  );
}

function DocumentActions({
  document,
  onDelete,
}: {
  document: DocumentRecord;
  onDelete: () => void;
}) {
  const [working, setWorking] = useState(false);

  const download = async () => {
    setWorking(true);
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
      setWorking(false);
    }
  };

  const reindex = async () => {
    setWorking(true);
    try {
      await reindexDocument(document.id);
      toast.success("Document reindexed.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Reindex failed.");
    } finally {
      setWorking(false);
    }
  };

  const links = [
    { href: `/chat/${document.id}`, label: "Chat", icon: MessageSquareText },
    { href: "/quizzes", label: "Create a quiz", icon: Sparkles },
    { href: "/flashcards", label: "Review flashcards", icon: BookOpenText },
    { href: "/study-tools", label: "Study summary", icon: FileText },
  ];

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">
        Open the document in chat or use another study tool with this document.
      </p>
      <div className="flex flex-wrap gap-2">
        {links.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href.includes("?") ? `${href}&document_id=${document.id}` : href}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-border bg-background px-4 text-sm font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <Icon size={16} aria-hidden="true" />
            {label}
          </Link>
        ))}
      </div>
      <div className="flex flex-wrap gap-2 border-t border-border pt-5">
        <Button type="button" variant="outline" onClick={() => void download()} disabled={working}>
          <ArrowDownToLine size={16} aria-hidden="true" />
          Download original
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => void reindex()}
          disabled={working || document.status !== "ready"}
        >
          <RefreshCw size={16} aria-hidden="true" />
          Reindex
        </Button>
        <Button type="button" variant="outline" onClick={onDelete}>
          <Trash2 size={16} aria-hidden="true" />
          Delete document
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">
        Privacy cannot be changed because the current API does not accept or return
        document privacy flags.
      </p>
    </div>
  );
}

export function DocumentDetail({ id: rawId }: { id: string }) {
  const id = Number(rawId);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const documentQuery = useQuery({
    queryKey: ["document", id],
    queryFn: () => getDocument(id),
    enabled: Number.isInteger(id) && id > 0,
  });
  const queryClient = useQueryClient();

  if (!Number.isInteger(id) || id < 1) {
    return (
      <ErrorState
        title="Document not found"
        description="This document link is invalid or the document is no longer available."
      />
    );
  }
  if (documentQuery.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-12 w-64" />
        <Skeleton className="h-36 w-full" />
      </div>
    );
  }
  if (documentQuery.isError) {
    const status =
      typeof documentQuery.error === "object" &&
      documentQuery.error !== null &&
      "status" in documentQuery.error
        ? documentQuery.error.status
        : undefined;
    if (status === 403 || status === 404) {
      return (
        <EmptyState
          title={status === 403 ? "Access denied" : "Document not found"}
          description={
            status === 403
              ? "You do not have permission to view this document."
              : "This document may have been deleted or is not in your library."
          }
          action={
            <Link
              href="/library"
              className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-border px-4 text-sm font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              <ArrowLeft size={16} aria-hidden="true" />
              Back to Library
            </Link>
          }
        />
      );
    }
    return (
      <ErrorState
        title="Could not load this document"
        description={documentQuery.error.message}
      />
    );
  }

  const document = documentQuery.data;
  if (!document) return null;

  const removeDocument = async () => {
    setDeleting(true);
    try {
      await deleteDocument(document.id);
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
      toast.success("Document and its study data were deleted.");
      window.location.assign("/library");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not delete document.");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <>
      <Link
        href="/library"
        className="mb-5 inline-flex h-10 items-center justify-center gap-2 rounded-md px-4 text-sm font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
      >
          <ArrowLeft size={16} aria-hidden="true" />
          Library
      </Link>
      <DocumentDetailContent document={document} onDelete={() => setDeleteOpen(true)} />
      <Dialog
        open={deleteOpen}
        onOpenChange={(open) => {
          if (!deleting) setDeleteOpen(open);
        }}
        title="Delete this document?"
      >
        <p className="text-sm leading-6 text-muted-foreground">
          This also removes the document&apos;s chunks, summaries, flashcards, and
          quiz data. This cannot be undone.
        </p>
        <div className="mt-6 flex justify-end gap-3">
          <Button
            type="button"
            variant="outline"
            disabled={deleting}
            onClick={() => setDeleteOpen(false)}
          >
            Cancel
          </Button>
          <Button
            type="button"
            className="bg-danger text-white hover:bg-danger/90"
            disabled={deleting}
            onClick={() => void removeDocument()}
          >
            {deleting ? "Deleting…" : "Delete document"}
          </Button>
        </div>
      </Dialog>
    </>
  );
}

function DocumentDetailContent({
  document: initial,
  onDelete,
}: {
  document: DocumentRecord;
  onDelete: () => void;
}) {
  const { document } = useDocumentStatus(initial);
  const date = new Date(document.created_at);
  const created = Number.isNaN(date.getTime())
    ? "Date unavailable"
    : new Intl.DateTimeFormat(undefined, { dateStyle: "long" }).format(date);

  return (
    <>
      <PageHeader
        title={document.title}
        description="Document details and extracted learning material."
      />
      <Card className="mb-6">
        <CardContent className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <p className="text-xs font-medium text-muted-foreground">Pages</p>
            <p className="mt-1 font-medium">{document.page_count ?? "Unknown"}</p>
          </div>
          <div>
            <p className="text-xs font-medium text-muted-foreground">Language</p>
            <p className="mt-1 font-medium">{document.language ?? "Not detected"}</p>
          </div>
          <div>
            <p className="text-xs font-medium text-muted-foreground">Uploaded</p>
            <p className="mt-1 font-medium">{created}</p>
          </div>
          <div className="space-y-2">
            <p className="text-xs font-medium text-muted-foreground">Status / privacy</p>
            <div className="flex flex-wrap gap-2">
              <Badge>{document.status}</Badge>
              <PrivateFlag document={document} />
            </div>
            {!terminal.has(document.status) ? (
              <progress
                className="h-1.5 w-full accent-primary"
                max={100}
                value={document.progress}
                aria-label={`${document.status} progress`}
              />
            ) : null}
            {document.status === "failed" && document.error_message ? (
              <p role="alert" className="text-sm text-danger">
                {document.error_message}
              </p>
            ) : null}
          </div>
        </CardContent>
      </Card>
      <Tabs
        tabs={[
          {
            id: "overview",
            label: "Overview",
            content: <DocumentOverview id={document.id} />,
          },
          {
            id: "pages",
            label: "Pages",
            content: <DocumentPages document={document} />,
          },
          {
            id: "actions",
            label: "Actions",
            content: <DocumentActions document={document} onDelete={onDelete} />,
          },
        ]}
      />
    </>
  );
}
