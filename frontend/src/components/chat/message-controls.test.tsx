import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GroundingBadge, ReadAloud, VoiceInput, FeedbackControls } from "@/components/chat/message-controls";
import { SourcePassageBanner } from "@/components/chat/pdf-viewer";

const mocks = vi.hoisted(() => ({
  submitChatFeedback: vi.fn(),
  getChatSession: vi.fn(),
}));

vi.mock("@/lib/chat", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/chat")>();
  return {
    ...actual,
    submitChatFeedback: mocks.submitChatFeedback,
    getChatSession: mocks.getChatSession,
  };
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
    configurable: true,
    value(this: HTMLDialogElement) {
      this.setAttribute("open", "");
    },
  });
  Object.defineProperty(HTMLDialogElement.prototype, "close", {
    configurable: true,
    value(this: HTMLDialogElement) {
      this.removeAttribute("open");
    },
  });
});

describe("message trust and controls", () => {
  it("shows all grounding levels with an exact accessible score", () => {
    const { rerender } = render(<GroundingBadge score={0.75} />);
    expect(screen.getByLabelText("Grounding score 0.75: Well supported").getAttribute("title")).toBe(
      "Grounding score: 0.75",
    );
    rerender(<GroundingBadge score={0.5} />);
    expect(screen.getByLabelText("Grounding score 0.5: Partly supported")).toBeTruthy();
    rerender(<GroundingBadge score={0.49} />);
    expect(screen.getByLabelText("Grounding score 0.49: Weakly supported")).toBeTruthy();
  });

  it("shows the source banner with the quoted page when no text-layer match exists", () => {
    render(<SourcePassageBanner page={3} text="The quoted evidence was not found in the text layer." />);
    expect(screen.getByText("Source passage")).toBeTruthy();
    expect(screen.getByText("Page 3")).toBeTruthy();
    expect(screen.getByText("The quoted evidence was not found in the text layer.")).toBeTruthy();
  });

  it("sends thumbs down once with its optional reason and keeps saved feedback disabled", async () => {
    mocks.submitChatFeedback.mockResolvedValue(undefined);
    const onSaved = vi.fn();
    const view = render(
      <FeedbackControls messageId={51} onSaved={onSaved} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Not helpful answer" }));
    fireEvent.change(screen.getByLabelText("Optional reason"), {
      target: { value: "The citation is unrelated." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send feedback" }));

    await waitFor(() =>
      expect(mocks.submitChatFeedback).toHaveBeenCalledWith(
        51,
        "thumbs_down",
        "The citation is unrelated.",
      ),
    );
    expect(mocks.submitChatFeedback).toHaveBeenCalledTimes(1);
    expect(onSaved).toHaveBeenCalledWith("thumbs_down", "The citation is unrelated.");
    view.rerender(
      <FeedbackControls
        messageId={51}
        storedFeedback="thumbs_down"
        storedReason="The citation is unrelated."
        onSaved={onSaved}
      />,
    );
    expect(screen.getByRole("button", { name: "Not helpful answer" }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByText("Feedback saved: The citation is unrelated.")).toBeTruthy();
  });

  it("hides browser voice controls when the browser APIs are missing", async () => {
    Object.defineProperty(window, "SpeechRecognition", { configurable: true, value: undefined });
    Object.defineProperty(window, "webkitSpeechRecognition", { configurable: true, value: undefined });
    vi.stubGlobal("speechSynthesis", undefined);
    vi.stubGlobal("SpeechSynthesisUtterance", undefined);
    render(
      <>
        <VoiceInput language="English" onTranscript={vi.fn()} />
        <ReadAloud content="An answer." language="English" />
      </>,
    );
    await waitFor(() => expect(screen.queryByRole("button", { name: "Speak" })).toBeNull());
    expect(screen.queryByRole("button", { name: "Read aloud" })).toBeNull();
  });

  it("strips markdown and citations before speaking an answer", async () => {
    const speak = vi.fn();
    class MockUtterance {
      text: string;
      lang = "";
      voice: SpeechSynthesisVoice | null = null;
      onend: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor(text: string) {
        this.text = text;
      }
    }
    vi.stubGlobal("SpeechSynthesisUtterance", MockUtterance);
    vi.stubGlobal("speechSynthesis", {
      getVoices: () => [],
      cancel: vi.fn(),
      speak,
      pause: vi.fn(),
      resume: vi.fn(),
    });
    render(<ReadAloud content="**Attention** [Unit I, p.2] uses *context*." language="English" />);
    fireEvent.click(await screen.findByRole("button", { name: "Read aloud" }));
    await waitFor(() => expect(speak).toHaveBeenCalledTimes(1));
    expect((speak.mock.calls[0][0] as MockUtterance).text).toBe("Attention uses context.");
  });
});
