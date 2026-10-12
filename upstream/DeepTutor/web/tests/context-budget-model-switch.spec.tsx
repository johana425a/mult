import { fireEvent, render, renderHook, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ContextBudgetChip, { type ContextBudget } from "@/components/chat/home/ContextBudgetChip";
import { contextBudgetForModel, useContextBudget } from "@/hooks/useContextBudget";
import type { MessageItem } from "@/features/chat/ChatStateAdapter";
import type { LLMOption } from "@/lib/llm-options";
import { initI18n } from "@/i18n/init";

initI18n("en");

const measured: ContextBudget = {
  window: 16_384,
  window_estimated: true,
  used_tokens: 18_200,
  free_tokens: 0,
  model: "Qwen3.5-4B",
  counter: "tiktoken",
  segments: [{ key: "messages", tokens: 9_500 }, { key: "system_tools", tokens: 4_200 }],
};
const qwen: LLMOption = {
  profile_id: "local", model_id: "qwen", profile_name: "Local",
  provider: "openai", model: "Qwen3.5-4B", model_name: "Qwen",
  context_window: 16_384, is_active_default: false,
};
const deepseek: LLMOption = {
  profile_id: "connected", model_id: "dsroute_fixture", profile_name: "DeepSeek",
  provider: "openai", model: "dsroute_fixture", actual_model: "deepseek-flash",
  model_name: "DeepSeek Flash", context_window: 1_000_000, is_active_default: true,
};
function transcript(budget: ContextBudget): MessageItem[] {
  return [{ id: 1, role: "assistant", content: "Kept answer", events: [
    { type: "result", timestamp: 1791763200, content: "", source: "chat", stage: "done", metadata: { metadata: { context_budget: budget } } },
  ] }];
}

describe("context budget follows the currently selected model", () => {
  it("updates immediately Qwen 16k -> DeepSeek 1M -> Qwen 16k without modifying history", () => {
    const messages = transcript(measured);
    const original = JSON.stringify(messages);
    const { result, rerender } = renderHook(
      ({ selected }) => useContextBudget(messages, selected),
      { initialProps: { selected: qwen } },
    );
    expect(result.current?.window).toBe(16_384);
    rerender({ selected: deepseek });
    expect(result.current).toMatchObject({ window: 1_000_000, model: "deepseek-flash", used_tokens: 18_200, free_tokens: 981_800, usage_rebased: true });
    rerender({ selected: qwen });
    expect(result.current).toMatchObject({ window: 16_384, model: "Qwen3.5-4B", free_tokens: 0 });
    expect(JSON.stringify(messages)).toBe(original);
  });

  it("repairs an old same-route 16k result using actual catalog metadata", () => {
    const oldRoute = { ...measured, model: "dsroute_fixture" };
    expect(contextBudgetForModel(oldRoute, deepseek)).toMatchObject({
      model: "deepseek-flash", window: 1_000_000, window_estimated: false, usage_rebased: true,
    });
    expect(oldRoute.window).toBe(16_384);
    expect(oldRoute.model).toBe("dsroute_fixture");
  });

  it("marks usage as prior-request estimate and displays no internal routing ID", () => {
    const budget = contextBudgetForModel(measured, deepseek)!;
    render(<ContextBudgetChip budget={budget} />);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText("deepseek-flash")).toBeInTheDocument();
    expect(screen.getByText(/18.2k \/ 1M/)).toBeInTheDocument();
    expect(screen.getByText(/latest measured request/)).toBeInTheDocument();
    expect(screen.queryByText(/dsroute_/)).not.toBeInTheDocument();
  });

  it("clears the rebased warning when a current-model request measurement arrives", () => {
    const { result, rerender } = renderHook(
      ({ messages }) => useContextBudget(messages, deepseek),
      { initialProps: { messages: transcript(measured) } },
    );
    expect(result.current?.usage_rebased).toBe(true);
    rerender({ messages: transcript({ ...measured, window: 1_000_000, model: "deepseek-flash", used_tokens: 20_000 }) });
    expect(result.current).toMatchObject({ used_tokens: 20_000, usage_rebased: false });
  });

  it.each([undefined, 0, -1, Number.NaN, Number.POSITIVE_INFINITY])(
    "hides a mismatched old capacity when the selected model window is %s",
    (context_window) => {
      expect(contextBudgetForModel(measured, { ...deepseek, context_window })).toBeNull();
    },
  );

  it("keeps a matching custom model's historical fallback and honors explicit manual capacity", () => {
    const custom = { ...qwen, model: "custom-v1", context_window: undefined };
    const previous = { ...measured, model: "custom-v1", window: 32_000 };
    expect(contextBudgetForModel(previous, custom)).toBe(previous);
    expect(contextBudgetForModel(previous, { ...custom, context_window: 48_000 })).toMatchObject({ window: 48_000, usage_rebased: true });
  });

  it("hides missing selected metadata and does not invent a measurement before the first result", () => {
    expect(contextBudgetForModel(measured, null)).toBeNull();
    expect(contextBudgetForModel(null, deepseek)).toBeNull();
    expect(contextBudgetForModel({ ...measured, model: "dsroute_fixture" }, { ...deepseek, actual_model: undefined, model_name: "dsroute_fixture", context_window: undefined })).toBeNull();
    expect(contextBudgetForModel({ ...measured, model: "DSEXEC_fixture" }, { ...deepseek, model: "DSEXEC_fixture", actual_model: undefined, model_name: "DSEXEC_fixture", context_window: undefined })).toBeNull();
  });
});
