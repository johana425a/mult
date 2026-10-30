import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { StreamEvent } from "@/features/chat/model/protocol";
import { StreamingStatus } from "@/features/chat/trace";
import { initI18n } from "@/i18n/init";
import { PRODUCT_NAME } from "@/lib/product-brand";

initI18n("en");

describe("chat activity status", () => {
  it("keeps answer streaming inside the existing exploration surface", () => {
    const events = [
      {
        type: "content",
        stage: "responding",
        content: "Partial answer",
        timestamp: Date.now() / 1000,
      },
    ] as StreamEvent[];

    render(
      <StreamingStatus
        events={events}
        isStreaming
        content="Partial answer"
      />,
    );

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent(`${PRODUCT_NAME} Exploring`);
    expect(status).not.toHaveTextContent("Responding");
  });

  it("keeps the row on a finished turn that produced only a trace", () => {
    // A turn can run tools and end without a user-facing answer (a rejected
    // capability finish, for one). The row is the only way to open that
    // trace, so hiding it makes the whole turn look like it never ran.
    const events = [
      {
        type: "tool_call",
        stage: "exploring",
        content: "",
        timestamp: Date.now() / 1000,
      },
    ] as StreamEvent[];

    render(
      <StreamingStatus
        events={events}
        isStreaming={false}
        content=""
        expandable
        expanded={false}
        onToggle={() => {}}
      />,
    );

    // Expandable rows render as the disclosure button rather than a status
    // region, and carry the settled label.
    expect(screen.getByRole("button")).toHaveTextContent("Done");
  });

  it("shows the opaque reasoning-progress status until action starts", () => {
    const events = [
      {
        type: "progress",
        source: "chat",
        stage: "responding",
        content: "The model is still reasoning; it has not produced an answer or tool action yet.",
        metadata: {
          trace_kind: "reasoning_progress",
          call_id: "call-1",
          reasoning_chars: 120,
          elapsed_s: 15,
        },
        timestamp: Date.now() / 1000,
      },
    ] as StreamEvent[];

    const { rerender } = render(
      <StreamingStatus events={events} isStreaming content="" />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      "Still reasoning before acting",
    );

    rerender(
      <StreamingStatus
        events={[
          ...events,
          {
            type: "content",
            source: "chat",
            stage: "responding",
            content: "Acting now",
            timestamp: Date.now() / 1000,
          },
        ] as StreamEvent[]}
        isStreaming
        content="Acting now"
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(`${PRODUCT_NAME} Exploring`);
  });

  it.each([
    { type: "done", metadata: { status: "failed" } },
    { type: "error", metadata: { turn_terminal: true, status: "failed" } },
  ])("preserves failed status after reopening a terminal $type", (terminal) => {
    render(<StreamingStatus events={[{
      ...terminal, source: "chat", stage: "responding", content: "",
      timestamp: Date.now() / 1000,
    }] as StreamEvent[]} isStreaming={false} content="The request failed." />);
    expect(screen.getByRole("status")).toHaveTextContent("Generation failed");
    expect(screen.getByRole("status")).not.toHaveTextContent("Done");
  });

  it.each(["done", "error"])("preserves cancellation from terminal %s", (type) => {
    render(<StreamingStatus events={[{
      type, source: "chat", stage: "responding", content: "",
      metadata: { turn_terminal: true, status: "cancelled" },
      timestamp: Date.now() / 1000,
    }] as StreamEvent[]} isStreaming={false} content="Partial answer" />);
    expect(screen.getByRole("status")).toHaveTextContent("Stopped");
    expect(screen.getByRole("status")).not.toHaveTextContent("Done");
  });

  it("uses the latest completion after a recovered tool error", () => {
    const events = [
      { type: "error", metadata: { status: "failed" } },
      { type: "done", metadata: { status: "completed" } },
    ].map((e, index) => ({ ...e, source: "chat", stage: "responding", content: "",
      timestamp: Date.now() / 1000 + index })) as StreamEvent[];
    render(<StreamingStatus events={events} isStreaming={false} content="Recovered answer" />);
    expect(screen.getByRole("status")).toHaveTextContent("Done");
    expect(screen.getByRole("status")).not.toHaveTextContent("Generation failed");
  });

  it("does not turn a nonterminal tool error into a failed answer", () => {
    render(<StreamingStatus events={[{
      type: "error", source: "tool", stage: "exploring", content: "Tool unavailable",
      metadata: { status: "failed" }, timestamp: Date.now() / 1000,
    }] as StreamEvent[]} isStreaming={false} content="Answered using another tool" />);
    expect(screen.getByRole("status")).toHaveTextContent("Done");
  });

  it("shows live activity when resuming after an earlier terminal event", () => {
    render(<StreamingStatus events={[{
      type: "done", source: "chat", stage: "responding", content: "",
      metadata: { status: "failed" }, timestamp: Date.now() / 1000,
    }, {
      type: "content", source: "chat", stage: "responding", content: "Retrying",
      timestamp: Date.now() / 1000 + 1,
    }] as StreamEvent[]} isStreaming content="Retrying" />);
    expect(screen.getByRole("status")).toHaveTextContent(`${PRODUCT_NAME} Exploring`);
    expect(screen.getByRole("status")).not.toHaveTextContent("Generation failed");
  });
});
