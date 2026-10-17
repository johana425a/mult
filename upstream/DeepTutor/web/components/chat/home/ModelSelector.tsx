"use client";

import { useId, useMemo, useRef, useState } from "react";
import { AlertCircle, Bot, Check, ChevronDown } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLingerExpand } from "@/hooks/use-linger-expand";
import { useOutsideClick } from "@/hooks/use-outside-click";
import Tooltip from "@/shared/ui/Tooltip";
import ProviderIcon from "@/components/common/ProviderIcon";
import type { LLMSelection } from "@/features/chat/model/protocol";
import { setGlobalDefaultModel } from "@/lib/resolved-model";
import { isDesktopManagedOption, llmOptionPresentation } from "@/lib/llm-option-presentation";
import {
  llmSelectionKey,
  sameLLMSelection,
  type LLMOption,
} from "@/lib/llm-options";

function formatContextWindow(value?: number) {
  if (!value) return "";
  if (value >= 1_000_000) return `${Math.round(value / 1_000_000)}M ctx`;
  if (value >= 1_000) return `${Math.round(value / 1_000)}k ctx`;
  return `${value} ctx`;
}

function providerLabel(option: LLMOption) {
  return llmOptionPresentation(option).providerLabel;
}

function ModelOptionRow({
  option,
  selected,
  onSelect,
}: {
  option: LLMOption;
  selected: boolean;
  onSelect: () => void;
}) {
  const { t } = useTranslation();
  // Gateway IDs are transport details. Owned desktop connections expose the
  // actual model name; other configured providers keep their existing labels.
  const presentation = llmOptionPresentation(option);
  const modelLabel = presentation.modelLabel;
  const contextWindow = formatContextWindow(option.context_window);
  // Long model ids ("google/gemini-3-flash-preview") get ellipsized by the
  // inline layout; hovering the row reveals the full id as an overlay. The
  // scrollWidth check at mouseenter time keeps the overlay away from rows
  // that aren't actually truncated.
  const nameRef = useRef<HTMLSpanElement>(null);
  const [revealFull, setRevealFull] = useState(false);
  return (
    <button
      type="button"
      aria-label={`${isDesktopManagedOption(option) ? modelLabel : option.model_name} | ${option.profile_name}`}
      onClick={onSelect}
      onMouseEnter={() => {
        const el = nameRef.current;
        setRevealFull(!!el && el.scrollWidth > el.clientWidth + 1);
      }}
      onMouseLeave={() => setRevealFull(false)}
      className={`relative flex w-full items-center gap-2 px-3 py-1.5 text-left transition-colors active:bg-[var(--muted)]/70 ${
        selected ? "bg-[var(--primary)]/[0.06]" : "hover:bg-[var(--muted)]/45"
      }`}
    >
      <ProviderIcon
        provider={presentation.provider}
        size={14}
        className={
          selected ? "text-[var(--primary)]" : "text-[var(--muted-foreground)]"
        }
      />
      <span
        ref={nameRef}
        className="min-w-0 truncate text-[12.5px] font-medium text-[var(--foreground)]"
      >
        {modelLabel}
      </span>
      {option.is_active_default && (
        <span className="shrink-0 rounded-full bg-[var(--muted)] px-1.5 py-px text-[9px] font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
          {t("Default")}
        </span>
      )}
      <span className="min-w-0 flex-1 truncate text-[11px] text-[var(--muted-foreground)]">
        {providerLabel(option)}
      </span>
      {contextWindow ? (
        <span className="shrink-0 text-[11px] text-[var(--muted-foreground)]">
          {contextWindow}
        </span>
      ) : null}
      {option.reasoning_effort && <span className="shrink-0 text-[10px] text-[var(--muted-foreground)]">{option.reasoning_effort}</span>}
      {selected && (
        <Check
          size={14}
          strokeWidth={2}
          className="shrink-0 text-[var(--primary)]"
        />
      )}
      {revealFull && (
        <span className="pointer-events-none absolute inset-x-1.5 top-1/2 z-10 -translate-y-1/2 break-all rounded-lg border border-[var(--border)] bg-[var(--popover)] px-2 py-1 text-[12px] font-medium text-[var(--foreground)] shadow-md">
          {modelLabel}
        </span>
      )}
    </button>
  );
}

export default function ModelSelector({
  options,
  activeDefault,
  value,
  loading,
  error,
  allowSystemDefault = true,
  systemDefaultLabel,
  systemDefaultDetail,
  helperText,
  placement = "top",
  pinned = true,
  disabled: externallyDisabled = false,
  onChange,
  onRefresh,
}: {
  options: LLMOption[];
  activeDefault: LLMSelection | null;
  value: LLMSelection | null;
  loading: boolean;
  error: boolean;
  allowSystemDefault?: boolean;
  systemDefaultLabel?: string;
  systemDefaultDetail?: string;
  helperText?: string;
  placement?: "top" | "bottom";
  /** Optional always-visible label for surfaces outside the composer. */
  pinned?: boolean;
  disabled?: boolean;
  onChange: (selection: LLMSelection | null) => void;
  onRefresh?: () => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [savingDefault, setSavingDefault] = useState(false);
  const [saveError, setSaveError] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popupId = useId();
  const {
    linger,
    triggerProps: lingerProps,
  } = useLingerExpand(open, 1200, pinned);

  const selectedSelection = value ?? activeDefault;
  const selectedKey = llmSelectionKey(value);
  const selectedOption = useMemo(
    () =>
      options.find((option) => sameLLMSelection(option, selectedSelection)) ??
      null,
    [options, selectedSelection],
  );
  const selectedPresentation = selectedOption ? llmOptionPresentation(selectedOption) : null;

  useOutsideClick(rootRef, open, () => {
    setOpen(false);
    linger();
  });

  const defaultLabel = systemDefaultLabel || t("Follow global default", { defaultValue: "Follow global default" });
  const defaultDetail =
    systemDefaultDetail || t("Use the active default model from Settings");
  const canRefresh = error && Boolean(onRefresh);
  const disabled =
    externallyDisabled || savingDefault || loading ||
    (!canRefresh && (error || (options.length === 0 && !allowSystemDefault)));
  const label = loading
    ? t("Loading models")
    : error
      ? canRefresh
        ? t("Refresh models")
        : t("Models unavailable")
      : selectedPresentation
        ? `${selectedPresentation.providerLabel} · ${selectedPresentation.modelLabel} · ${!value ? defaultLabel : t("This conversation", { defaultValue: "This conversation" })}`
        : value ? t("Selected model unavailable", { defaultValue: "Selected model unavailable" }) : t("Select model");
  const menuPlacementClass =
    placement === "bottom" ? "top-full mt-1.5" : "bottom-full mb-1.5";

  return (
    <div ref={rootRef} className="relative min-w-0" onKeyDown={(event) => {
      if (open && event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        setOpen(false);
        linger();
        triggerRef.current?.focus();
      }
    }} onBlur={(event) => {
      if (open && !event.currentTarget.contains(event.relatedTarget as Node | null)) {
        setOpen(false);
        linger();
      }
    }}>
      <Tooltip label={canRefresh ? t("Refresh models") : label} suppressed={open} side="top">
        <button
          ref={triggerRef}
          type="button"
          disabled={disabled}
          onClick={() => {
            if (canRefresh) {
              setOpen(false);
              onRefresh?.();
              return;
            }
            setOpen((current) => !current);
          }}
          aria-label={canRefresh ? t("Refresh models") : t("Select model")}
          aria-expanded={open}
          aria-haspopup="dialog"
          aria-controls={open ? popupId : undefined}
          {...lingerProps}
          className={`dt-interactive inline-flex min-h-8 max-w-full items-center rounded-lg px-2 py-1 text-[14px] font-medium ${
            disabled
              ? "cursor-not-allowed text-[var(--border)]"
              : open
                ? "bg-[var(--muted)] text-[var(--foreground)]"
                : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)]"
          }`}
        >
          {error ? (
            <AlertCircle size={16} strokeWidth={1.7} className="shrink-0" />
          ) : (
            <ProviderIcon provider={selectedPresentation?.provider} size={16} />
          )}
          <span data-model-selector-label className="ml-1.5 inline-flex min-w-0 max-w-[min(260px,calc(100vw-230px))] items-center gap-1 text-left">
            <span className="min-w-0 whitespace-normal [overflow-wrap:anywhere]">
              <span data-model-name className="block leading-5">{selectedPresentation && !loading && !error ? selectedPresentation.modelLabel : label}</span>
              {selectedPresentation && !loading && !error && <span className="block text-[10px] font-normal leading-3 text-[var(--muted-foreground)]">{selectedPresentation.providerLabel} · {!value ? defaultLabel : t("This conversation", { defaultValue: "This conversation" })}</span>}
            </span>
            <ChevronDown
              size={13}
              className={`shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
            />
          </span>
        </button>
      </Tooltip>

      {open && !disabled && (
        <div
          id={popupId}
          role="dialog"
          aria-label={t("Select model")}
          className={`dt-popup-up absolute right-0 z-50 ${menuPlacementClass} w-[min(380px,calc(100vw-32px))] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--popover)] shadow-lg backdrop-blur-md`}
        >
          {helperText ? (
            <div className="border-b border-[var(--border)]/50 px-3 py-1.5 text-[11px] text-[var(--muted-foreground)]">
              {helperText}
            </div>
          ) : null}
          <div className="max-h-[280px] overflow-y-auto py-1">
            {allowSystemDefault && (
              <button
                type="button"
                aria-label={defaultDetail}
                onClick={() => {
                  onChange(null);
                  setOpen(false);
                  linger();
                }}
                className={`flex w-full items-center gap-2 px-3 py-1.5 text-left transition-colors active:bg-[var(--muted)]/70 ${
                  selectedKey === ""
                    ? "bg-[var(--primary)]/[0.06]"
                    : "hover:bg-[var(--muted)]/45"
                }`}
              >
                <Bot
                  size={14}
                  strokeWidth={1.7}
                  className={`shrink-0 ${
                    selectedKey === ""
                      ? "text-[var(--primary)]"
                      : "text-[var(--muted-foreground)]"
                  }`}
                />
                <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-[var(--foreground)]">
                  {defaultLabel}
                </span>
                {selectedKey === "" && (
                  <Check
                    size={14}
                    strokeWidth={2}
                    className="shrink-0 text-[var(--primary)]"
                  />
                )}
              </button>
            )}
            {options.map((option) => {
              const optionSelection = {
                profile_id: option.profile_id,
                model_id: option.model_id,
              };
              const optionKey = llmSelectionKey(optionSelection);
              return (
                <ModelOptionRow
                  key={optionKey}
                  option={option}
                  selected={optionKey === selectedKey}
                  onSelect={() => {
                    onChange(optionSelection);
                    setOpen(false);
                    linger();
                  }}
                />
              );
            })}
          </div>
          {selectedOption && <div className="border-t border-[var(--border)] p-1">
            <button type="button" disabled={savingDefault} className="w-full rounded-lg px-3 py-2 text-left text-xs hover:bg-[var(--muted)]" onClick={() => {
              setSavingDefault(true); setSaveError("");
              void setGlobalDefaultModel({ profile_id: selectedOption.profile_id, model_id: selectedOption.model_id })
                .then(() => { onRefresh?.(); setOpen(false); })
                .catch(() => setSaveError(t("Default model could not be saved", { defaultValue: "Default model could not be saved" })))
                .finally(() => setSavingDefault(false));
            }}>{t("Set selected model as global default", { defaultValue: "Set selected model as global default" })}</button>
            {saveError && <p role="alert" className="px-3 pb-2 text-xs text-[var(--destructive)]">{saveError}</p>}
          </div>}
        </div>
      )}
    </div>
  );
}
