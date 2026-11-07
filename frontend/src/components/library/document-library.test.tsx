import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DocumentRecord } from "@/lib/documents";

const { deleteDocument, listDocuments, reindexDocument, downloadDocument } =
  vi.hoisted(() => ({
    deleteDocument: vi.fn(),
    listDocuments: vi.fn(),
    reindexDocument: vi.fn(),
    downloadDocument: vi.fn(),
  }));

vi.mock("@/lib/documents", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/documents")>();
  return {
    ...actual,
    deleteDocument,
    listDocuments,
    reindexDocument,
    downloadDocument,
  };
});
vi.mock("@/lib/hooks/use-document-status", () => ({
  useDocumentStatus: (initial: DocumentRecord) => ({
    document: initial,
    streamError: null,
    pollingError: null,
  }),
}));

import { DocumentLibrary } from "@/components/library/document-library";

const document: DocumentRecord = {
  id: 10,
  title: "Course.pdf",
  status: "failed",
  progress: 100,
  error_message: "Text extraction failed.",
  page_count: 3,
  language: null,
  created_at: "2026-01-01T00:00:00Z",
};

function renderLibrary() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <DocumentLibrary />
    </QueryClientProvider>,
  );
}

describe("document delete confirmation", () => {
  beforeEach(() => {
    listDocuments.mockResolvedValue([document]);
    deleteDocument.mockReset().mockResolvedValue(undefined);
    reindexDocument.mockReset();
    downloadDocument.mockReset();
    Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
      configurable: true,
      value: function showModal(this: HTMLDialogElement) {
        this.setAttribute("open", "");
      },
    });
    Object.defineProperty(HTMLDialogElement.prototype, "close", {
      configurable: true,
      value: function close(this: HTMLDialogElement) {
        this.removeAttribute("open");
      },
    });
  });

  it("requires confirmation before deleting a document", async () => {
    renderLibrary();
    await screen.findByText("Course.pdf");

    fireEvent.click(screen.getByLabelText("Actions for Course.pdf"));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(
      screen.getByText(/also removes its chunks, summaries, flashcards, and quiz data/),
    ).toBeTruthy();
    expect(deleteDocument).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Delete document" }));
    await waitFor(() => expect(deleteDocument).toHaveBeenCalled());
    expect(deleteDocument.mock.calls[0]?.[0]).toBe(document.id);
  });
});
