import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ listSyllabi: vi.fn(), listDocuments: vi.fn(), previewSyllabus: vi.fn(), getCoverage: vi.fn(), getSyllabus: vi.fn(), createSyllabus: vi.fn(), addTopic: vi.fn(), editTopic: vi.fn(), deleteTopic: vi.fn() }));
vi.mock("@/lib/syllabus", () => mocks);
vi.mock("@/lib/documents", () => ({ listDocuments: mocks.listDocuments }));
import SyllabusPage from "./page";

beforeEach(() => { vi.clearAllMocks(); mocks.listSyllabi.mockResolvedValue([{ id: 1, title: "Networks" }]); mocks.listDocuments.mockResolvedValue([]); mocks.getCoverage.mockResolvedValue({ percent: 50, topics: [{ topic_id: 8, title: "Routing", chunks: 3, pages: [2, 3], documents: [4], status: "covered" }, { topic_id: 9, title: "Security", chunks: 0, pages: [], documents: [], status: "no material" }] }); mocks.getSyllabus.mockResolvedValue({ id: 1, title: "Networks", tree: [{ id: 8, title: "Routing", order: 0, children: [] }, { id: 9, title: "Security", order: 1, children: [] }] }); mocks.previewSyllabus.mockResolvedValue([{ title: "Routing", order: 0, children: [] }]); });
afterEach(cleanup);

describe("syllabus", () => {
  it("previews parsed topics and displays coverage with topic actions", async () => {
    render(<SyllabusPage />);
    expect(await screen.findByText("Coverage: 50%")).toBeTruthy();
    expect(screen.getByText("no material found: upload notes covering this topic")).toBeTruthy();
    expect(screen.getAllByRole("link", { name: "Quiz this topic" })[0].getAttribute("href")).toContain("syllabusId=1&topicId=8");
    expect(screen.getAllByRole("link", { name: "Make flashcards" })[0].getAttribute("href")).toContain("documentId=4");
    fireEvent.change(screen.getByLabelText("Paste syllabus"), { target: { value: "1. Routing" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview topics" }));
    expect(await screen.findByDisplayValue("Routing")).toBeTruthy();
    expect(mocks.previewSyllabus).toHaveBeenCalledWith("1. Routing");
  });
});
