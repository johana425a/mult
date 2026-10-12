"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { UnifiedModelControl } from "@/components/common/UnifiedModelControl";
import { ResolvedModelBadge } from "@/components/common/ResolvedModelBadge";
import type { LLMSelection } from "@/features/chat/model/protocol";
import { bookApi } from "@/lib/book-api";
import type { Book } from "@/lib/book-types";

/** DeepSteam: a saved task's execution identity is distinct from its next selection. */
export function BookModelControl({ book, disabled = false, onUpdated }: {
  book: Book;
  disabled?: boolean;
  onUpdated: (book: Book) => void;
}) {
  const { t } = useTranslation();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const change = async (selection: LLMSelection | null) => {
    setSaving(true);
    setError("");
    try {
      const result = await bookApi.setModelSelection(book.id, selection, book.revision);
      onUpdated(result.book);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Model settings were not saved. Try again.");
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-[var(--border)] px-5 py-2 text-xs">
      {book.can_edit !== false && <UnifiedModelControl
        value={book.llm_selection ?? null}
        onChange={(value) => void change(value)}
        surface="book"
        label={t("Book generation model", { defaultValue: "Book generation model" })}
        disabled={disabled || saving || book.status === "compiling"}
        placement="bottom"
      />}
      <span className="text-[var(--muted-foreground)]">{t("Current task model", { defaultValue: "Current task model" })}</span>
      <ResolvedModelBadge value={book.metadata?.generation_model} showUnknown />
      {book.status === "compiling" && <span className="text-[var(--muted-foreground)]">{t("Pause generation before changing the model", { defaultValue: "Pause generation before changing the model" })}</span>}
      {error && <span role="alert" className="text-red-500">{error}</span>}
    </div>
  );
}
