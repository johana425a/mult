"use client";
import { PRODUCT_NAME } from "@/lib/product-brand";

import {
  AudioLines,
  Bot,
  Boxes,
  Brain,
  BrainCircuit,
  Clapperboard,
  Database,
  FileScan,
  FolderOpen,
  Image as ImageIcon,
  Info,
  KeyRound,
  Library,
  ListChecks,
  MessagesSquare,
  Mic,
  Network,
  Palette,
  Paperclip,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  ChartNoAxesCombined,
  UserRound,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import {
  ClaudeGlyph,
  CodexGlyph,
  DeepSeekGlyph,
  GeminiGlyph,
  GrokGlyph,
  HermesGlyph,
  KimiGlyph,
  MimoGlyph,
  OpenClawGlyph,
  OpencodeGlyph,
} from "@/components/agents/agent-icons";
import type { ServiceName } from "@/features/settings/store/SettingsStore";
import type { SettingsAccess } from "@/features/settings/navigation/settings-access";

/**
 * Settings information architecture.
 *
 * Independent settings pages, with legacy fragment aliases preserved.
 * This module remains the source for labels, visibility,
 * search metadata, and persistence hints.
 */

export type Lang = { zh: string; en: string };

export interface SettingsLeaf {
  key: string;
  href: string;
  label: Lang;
  blurb: Lang;
  icon: LucideIcon;
  /** Colored icon-tile accent for the sub-hub grid (full class strings). */
  tile: string;
  /** Model-service leaves carry a configured/not chip from the catalog. */
  service?: ServiceName;
  /** Hidden from non-admin users (the backend rejects them anyway). */
  adminOnly?: boolean;
}

export interface SettingsCategory {
  key: string;
  label: Lang;
  /** One-line descriptor shown on the hub block. */
  blurb: Lang;
  icon: LucideIcon;
  /** Canonical in-document category anchor. */
  href: string;
  /** Nested anchors (omitted for direct-section categories). */
  children?: SettingsLeaf[];
  /** Shown only when the backend reports an active learner policy. */
  learnerOnly?: boolean;
  /** Shown only to authenticated standard users who may act as guardians. */
  guardianOnly?: boolean;
}

export function isSettingsLeafVisible(
  leaf: SettingsLeaf,
  access: SettingsAccess,
): boolean {
  return !(leaf.adminOnly && access.hideAdminOnly);
}

export function isSettingsCategoryVisible(
  category: SettingsCategory,
  access: SettingsAccess,
): boolean {
  if (category.learnerOnly && !access.showLearnerOnly) return false;
  if (category.guardianOnly && !access.showGuardianOnly) return false;
  return (
    !category.children ||
    category.children.some((leaf) => isSettingsLeafVisible(leaf, access))
  );
}

export function visibleSettingsChildren(
  categoryKey: string,
  access: SettingsAccess,
): SettingsLeaf[] {
  return (
    SETTINGS_CATEGORIES.find((category) => category.key === categoryKey)
      ?.children ?? []
  ).filter((leaf) => isSettingsLeafVisible(leaf, access));
}

const MODEL_CHILDREN: SettingsLeaf[] = [
  {
    key: "voice",
    href: "/settings/voice",
    label: { en: "Voice", zh: "Voice" },
    blurb: {
      en: "Speech synthesis and transcription models with saved providers.",
      zh: "Speech synthesis and transcription models with saved providers.",
    },
    icon: AudioLines,
    tile: "bg-rose-500/10 text-rose-600",
  },
  {
    key: "multimodal",
    href: "/settings/multimodal",
    label: { en: "Multimodal generation", zh: "Multimodal generation" },
    blurb: {
      en: "Image and video generation models with saved providers.",
      zh: "Image and video generation models with saved providers.",
    },
    icon: ImageIcon,
    tile: "bg-violet-500/10 text-violet-600",
  },
  {
    key: "connections",
    href: "/settings#connections",
    label: { zh: "Providers", en: "Providers" },
    blurb: {
      zh: "Manage provider names, addresses, credentials, and connectivity.",
      en: "Manage provider names, addresses, credentials, and connectivity.",
    },
    icon: KeyRound,
    tile: "bg-sky-500/10 text-sky-600 dark:text-sky-400",
  },
  {
    key: "llm",
    href: "/settings#llm",
    label: { zh: "Language models", en: "Language models" },
    blurb: {
      zh: "Model names, context windows, capabilities, and connection tests.",
      en: "Model names, context windows, capabilities, and connection tests.",
    },
    icon: Brain,
    tile: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
    service: "llm",
  },
  {
    key: "task-models",
    href: "/settings#task-models",
    label: { zh: "Task models", en: "Task models" },
    blurb: {
      zh: `The model behind the calls ${PRODUCT_NAME} makes on its own.`,
      en: `The model behind the calls ${PRODUCT_NAME} makes on its own.`,
    },
    icon: ListChecks,
    tile: "bg-cyan-500/10 text-cyan-600 dark:text-cyan-400",
  },
  {
    key: "embedding",
    href: "/settings#embedding",
    label: { zh: "Embedding models", en: "Embedding models" },
    blurb: {
      zh: "Embedding models, dimensions, and connection tests.",
      en: "Embedding models, dimensions, and connection tests.",
    },
    icon: Database,
    tile: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
    service: "embedding",
  },
  {
    key: "search",
    href: "/settings#search",
    label: { zh: "Search", en: "Search" },
    blurb: { zh: "Web search providers.", en: "Web search providers." },
    icon: Search,
    tile: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
    service: "search",
  },
  {
    key: "tts",
    href: "/settings#tts",
    label: { zh: "Text-to-Speech", en: "Text-to-Speech" },
    blurb: {
      zh: "Text-to-speech for reading replies aloud.",
      en: "Text-to-speech for reading replies aloud.",
    },
    icon: AudioLines,
    tile: "bg-rose-500/10 text-rose-600 dark:text-rose-400",
    service: "tts",
  },
  {
    key: "stt",
    href: "/settings#stt",
    label: { zh: "Speech-to-Text", en: "Speech-to-Text" },
    blurb: {
      zh: "Speech-to-text for the composer microphone.",
      en: "Speech-to-text for the composer microphone.",
    },
    icon: Mic,
    tile: "bg-pink-500/10 text-pink-600 dark:text-pink-400",
    service: "stt",
  },
  {
    key: "imagegen",
    href: "/settings#imagegen",
    label: { zh: "Image Generation", en: "Image Generation" },
    blurb: {
      zh: "Text-to-image model for the chat imagegen tool.",
      en: "Text-to-image model for the chat imagegen tool.",
    },
    icon: ImageIcon,
    tile: "bg-fuchsia-500/10 text-fuchsia-600 dark:text-fuchsia-400",
    service: "imagegen",
  },
  {
    key: "videogen",
    href: "/settings#videogen",
    label: { zh: "Video Generation", en: "Video Generation" },
    blurb: {
      zh: "Text-to-video model for the chat videogen tool.",
      en: "Text-to-video model for the chat videogen tool.",
    },
    icon: Clapperboard,
    tile: "bg-indigo-500/10 text-indigo-600 dark:text-indigo-400",
    service: "videogen",
  },
];

const CHAT_CHILDREN: SettingsLeaf[] = [
  {
    key: "video-learning",
    href: "/settings#video-learning",
    label: { zh: "Video Learning", en: "Video Learning" },
    blurb: {
      zh: "Native YouTube and local Invidious playback providers.",
      en: "Native YouTube and local Invidious playback providers.",
    },
    icon: Clapperboard,
    tile: "bg-red-500/10 text-red-600 dark:text-red-400",
    adminOnly: true,
  },
  {
    key: "tools",
    href: "/settings#tools",
    label: { zh: "Tools", en: "Tools" },
    blurb: {
      zh: "Built-in tools the chat agent can invoke.",
      en: "Built-in tools the chat agent can invoke.",
    },
    icon: Wrench,
    tile: "bg-orange-500/10 text-orange-600 dark:text-orange-400",
  },
  {
    key: "capabilities",
    href: "/settings#capabilities",
    label: { zh: "Capabilities", en: "Capabilities" },
    blurb: {
      zh: "Per-capability LLM parameters and runtime knobs.",
      en: "Per-capability LLM parameters and runtime knobs.",
    },
    icon: SlidersHorizontal,
    tile: "bg-lime-500/10 text-lime-600 dark:text-lime-400",
  },
  {
    key: "starters",
    href: "/settings#starters",
    label: { zh: "Starting points", en: "Starting points" },
    blurb: {
      zh: "How much history shapes the three lines under the composer.",
      en: "How much history shapes the three lines under the composer.",
    },
    icon: Sparkles,
    tile: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
  },
  {
    key: "attachments",
    href: "/settings#attachments",
    label: { zh: "Attachments", en: "Attachments" },
    blurb: {
      zh: "Upload caps and extraction budgets for chat attachments.",
      en: "Upload caps and extraction budgets for chat attachments.",
    },
    icon: Paperclip,
    tile: "bg-teal-500/10 text-teal-600 dark:text-teal-400",
    adminOnly: true,
  },
];

const AGENT_CHILDREN: SettingsLeaf[] = [
  {
    key: "agent-claude-code",
    href: "/settings#agent-claude-code",
    label: { zh: "Claude Code", en: "Claude Code" },
    blurb: {
      zh: "Model, reasoning effort, and run params for the local Claude Code.",
      en: "Model, reasoning effort, and run params for the local Claude Code.",
    },
    // Brand glyph shares the lucide call signature (size/className).
    icon: ClaudeGlyph as unknown as LucideIcon,
    tile: "bg-orange-500/10 text-orange-600 dark:text-orange-400",
    adminOnly: true,
  },
  {
    key: "agent-codex",
    href: "/settings#agent-codex",
    label: { zh: "Codex", en: "Codex" },
    blurb: {
      zh: "Model, reasoning effort, and run params for the local Codex.",
      en: "Model, reasoning effort, and run params for the local Codex.",
    },
    icon: CodexGlyph as unknown as LucideIcon,
    tile: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
    adminOnly: true,
  },
  {
    key: "agent-grok",
    href: "/settings#agent-grok",
    label: { zh: "Grok CLI", en: "Grok CLI" },
    blurb: {
      zh: "Model, reasoning effort, and permission mode for the local Grok CLI.",
      en: "Model, reasoning effort, and permission mode for the local Grok CLI.",
    },
    icon: GrokGlyph as unknown as LucideIcon,
    tile: "bg-zinc-500/10 text-zinc-700 dark:text-zinc-300",
    adminOnly: true,
  },
  {
    // Gemini CLI's supported replacement.
    key: "agent-antigravity",
    href: "/settings#agent-antigravity",
    label: { zh: "Antigravity CLI", en: "Antigravity CLI" },
    blurb: {
      zh: "Model and run params for the local Antigravity CLI.",
      en: "Model and run params for the local Antigravity CLI.",
    },
    icon: GeminiGlyph as unknown as LucideIcon,
    tile: "bg-sky-500/10 text-sky-600 dark:text-sky-400",
    adminOnly: true,
  },
  {
    key: "agent-kimi",
    href: "/settings#agent-kimi",
    label: { zh: "Kimi CLI", en: "Kimi CLI" },
    blurb: {
      zh: "Model and run params for the local Kimi CLI.",
      en: "Model and run params for the local Kimi CLI.",
    },
    icon: KimiGlyph as unknown as LucideIcon,
    tile: "bg-zinc-500/10 text-zinc-700 dark:text-zinc-300",
    adminOnly: true,
  },
  {
    key: "agent-opencode",
    href: "/settings#agent-opencode",
    label: { zh: "opencode", en: "opencode" },
    blurb: {
      zh: "Model, reasoning effort, and run params for the local opencode.",
      en: "Model, reasoning effort, and run params for the local opencode.",
    },
    icon: OpencodeGlyph as unknown as LucideIcon,
    tile: "bg-neutral-500/10 text-neutral-700 dark:text-neutral-300",
    adminOnly: true,
  },
  {
    key: "agent-mimo",
    href: "/settings#agent-mimo",
    label: { zh: "MiMo Code", en: "MiMo Code" },
    blurb: {
      zh: "Model, reasoning effort, and run params for the local MiMo Code.",
      en: "Model, reasoning effort, and run params for the local MiMo Code.",
    },
    icon: MimoGlyph as unknown as LucideIcon,
    tile: "bg-orange-500/10 text-orange-600 dark:text-orange-400",
    adminOnly: true,
  },
  {
    key: "agent-hermes",
    href: "/settings#agent-hermes",
    label: { zh: "Hermes Agent", en: "Hermes Agent" },
    blurb: {
      zh: "Model, reasoning effort, and run params for the local Hermes Agent.",
      en: "Model, reasoning effort, and run params for the local Hermes Agent.",
    },
    icon: HermesGlyph as unknown as LucideIcon,
    tile: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
    adminOnly: true,
  },
  {
    key: "agent-hermes-remote",
    href: "/settings#agent-hermes-remote",
    label: { zh: "Hermes Agent (remote)", en: "Hermes Agent (remote)" },
    blurb: {
      zh: "Call a remote Hermes Agent over HTTP with per-chat session continuity.",
      en: "Call a remote Hermes Agent over HTTP with per-chat session continuity.",
    },
    icon: HermesGlyph as unknown as LucideIcon,
    tile: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
    adminOnly: true,
  },
  {
    key: "agent-openclaw",
    href: "/settings#agent-openclaw",
    label: { zh: "OpenClaw", en: "OpenClaw" },
    blurb: {
      zh: "Gateway or local-mode run params for the local OpenClaw agent.",
      en: "Gateway or local-mode run params for the local OpenClaw agent.",
    },
    icon: OpenClawGlyph as unknown as LucideIcon,
    tile: "bg-red-500/10 text-red-600 dark:text-red-400",
    adminOnly: true,
  },
  {
    key: "agent-deepseek-harness",
    href: "/settings#agent-deepseek-harness",
    label: { zh: "DeepSeek Harness", en: "DeepSeek Harness" },
    blurb: {
      zh: "Python SDK or headless CLI settings for DeepSeek Harness.",
      en: "Python SDK or headless CLI settings for DeepSeek Harness.",
    },
    icon: DeepSeekGlyph as unknown as LucideIcon,
    tile: "bg-indigo-500/10 text-indigo-600 dark:text-indigo-400",
    adminOnly: true,
  },
];

export const SETTINGS_CATEGORIES: SettingsCategory[] = [
  {
    key: "appearance",
    label: { zh: "Appearance", en: "Appearance" },
    blurb: { zh: "Theme and code blocks", en: "Theme and code blocks" },
    icon: Palette,
    href: "/settings#appearance",
  },
  {
    key: "network",
    label: { zh: "Network", en: "Network" },
    blurb: {
      zh: "Ports, browser API base, and CORS",
      en: "Ports, browser API base, and CORS",
    },
    icon: Network,
    href: "/settings#network",
  },
  {
    key: "workspace",
    label: { zh: "Workspace", en: "Workspace" },
    blurb: {
      zh: "System, general and custom workspaces, root folder and storage migration",
      en: "System, general and custom workspaces, root folder and storage migration",
    },
    icon: FolderOpen,
    href: "/settings#workspace",
  },
  {
    key: "models",
    label: { zh: "Models", en: "Models" },
    blurb: {
      zh: "Language, embedding, search, voice, and generation models",
      en: "Language, embedding, search, voice, and generation models",
    },
    icon: Boxes,
    href: "/settings#models",
    children: MODEL_CHILDREN,
  },
  {
    key: "knowledge",
    label: { zh: "Knowledge Base", en: "Knowledge Base" },
    blurb: { zh: "Document parsing engine", en: "Document parsing engine" },
    icon: Library,
    href: "/settings#document-parsing",
  },
  {
    key: "chat",
    label: { zh: "Chat", en: "Chat" },
    blurb: {
      zh: "Tools, capabilities, and attachments",
      en: "Tools, capabilities, and attachments",
    },
    icon: MessagesSquare,
    href: "/settings#chat",
    children: CHAT_CHILDREN,
  },
  {
    key: "agents",
    label: { zh: "Partners & Agents", en: "Partners & Agents" },
    blurb: {
      zh: "Configure the subagents you can call on in chat",
      en: "Configure the subagents you can call on in chat",
    },
    icon: Bot,
    href: "/settings#agents",
    children: AGENT_CHILDREN,
  },
  {
    key: "progress",
    label: { zh: "Learning progress", en: "Learning progress" },
    blurb: { zh: "Review your reading and learning activity.", en: "Review your reading and learning activity." },
    icon: ChartNoAxesCombined,
    href: "/settings/progress",
  },
  {
    key: "learner-profile",
    learnerOnly: true,
    label: { zh: "Learner profile", en: "Learner profile" },
    blurb: {
      zh: "Adjust age, grade, and explanation preferences.",
      en: "Adjust age, grade, and explanation preferences.",
    },
    icon: UserRound,
    href: "/settings#learner-profile",
  },
  {
    key: "guardian",
    guardianOnly: true,
    label: { zh: "Guardian", en: "Guardian" },
    blurb: {
      zh: "Review authorized learners and learning materials.",
      en: "Review authorized learners and learning materials.",
    },
    icon: ShieldCheck,
    href: "/settings#guardian",
  },
  {
    key: "memory",
    label: { zh: "Memory", en: "Memory" },
    blurb: {
      zh: "Chunking, budget, dedup, and reference policies",
      en: "Chunking, budget, dedup, and reference policies",
    },
    icon: BrainCircuit,
    href: "/settings#memory",
  },
  {
    key: "about",
    label: { zh: "Open source & components", en: "Open source & components" },
    blurb: {
      zh: "Upstream component versions, licenses and project resources",
      en: "Upstream component versions, licenses and project resources",
    },
    icon: Info,
    href: "/settings#about",
  },
];

export const SETTINGS_HUB_HREF = "/settings";

/** Stable aliases keep existing bookmarks and links from older clients working. */
export const SETTINGS_ALIASES: Record<string, string> = {
  tts: "voice",
  stt: "voice",
  imagegen: "multimodal",
  videogen: "multimodal",
  overview: "general",
  models: "llm",
  chat: "starters",
  agents: "agent-claude-code",
  "document-parsing": "knowledge",
  image: "multimodal",
  video: "multimodal",
};

export function resolveSettingsKey(key: string): string {
  return SETTINGS_ALIASES[key] ?? key;
}

/** Kept as an API name for callers; URLs now address independent pages. */
export function settingsAnchorHref(key: string): string {
  return `${SETTINGS_HUB_HREF}/${resolveSettingsKey(key)}`;
}

// The on-disk file (under data/user/settings/) each leaf module persists to.
// Surfaced in the toolbar status line so every page says where its parameters
// live, without duplicating the string on each page. Singleton pages (no
// merged category) are keyed by pathname; leaves inside a merged category
// page share one pathname, so those are keyed by `leaf.key` instead and
// looked up via the currently scrolled-to section (see `storagePathFor`).
const STORAGE_PATHS: Record<string, string> = {
  "/settings#appearance": "data/user/settings/interface.json",
  "/settings#network": "data/user/settings/system.json",
  "/settings#workspace": "data/user/.runtime/workspaces.sqlite3",
  "/settings#llm": "data/user/settings/model_catalog.json",
  "/settings#embedding": "data/user/settings/model_catalog.json",
  "/settings#search": "data/user/settings/model_catalog.json",
  "/settings#tts": "data/user/settings/model_catalog.json",
  "/settings#stt": "data/user/settings/model_catalog.json",
  "/settings#image": "data/user/settings/model_catalog.json",
  "/settings#video": "data/user/settings/model_catalog.json",
  "/settings#video-learning": "data/user/settings/video_learning.json",
  "/settings#document-parsing": "data/user/settings/document_parsing.json",
  "/settings#memory": "data/user/settings/main.yaml",
  appearance: "data/user/settings/interface.json",
  network: "data/user/settings/system.json",
  workspace: "data/user/.runtime/workspaces.sqlite3",
  voice: "data/user/settings/model_catalog.json",
  multimodal: "data/user/settings/model_catalog.json",
  connections: "data/user/settings/model_catalog.json",
  "task-models": "data/user/settings/model_catalog.json",
  knowledge: "data/user/settings/document_parsing.json",
  "video-learning": "data/user/settings/video_learning.json",
  starters: "data/user/settings/interface.json",
  memory: "data/user/settings/main.yaml",
  llm: "data/user/settings/model_catalog.json",
  embedding: "data/user/settings/model_catalog.json",
  search: "data/user/settings/model_catalog.json",
  tts: "data/user/settings/model_catalog.json",
  stt: "data/user/settings/model_catalog.json",
  imagegen: "data/user/settings/model_catalog.json",
  videogen: "data/user/settings/model_catalog.json",
  tools: "data/user/settings/interface.json",
  attachments: "data/user/settings/system.json",
  capabilities: "data/user/settings/main.yaml · agents.yaml",
  "agent-claude-code": "data/user/settings/subagent.json",
  "agent-codex": "data/user/settings/subagent.json",
  "agent-grok": "data/user/settings/subagent.json",
  "agent-antigravity": "data/user/settings/subagent.json",
  "agent-kimi": "data/user/settings/subagent.json",
  "agent-opencode": "data/user/settings/subagent.json",
  "agent-mimo": "data/user/settings/subagent.json",
};

export function storagePathFor(
  pathname: string,
  activeSection?: string | null,
): string | null {
  if (pathname === SETTINGS_HUB_HREF) {
    return activeSection ? (STORAGE_PATHS[activeSection] ?? null) : null;
  }
  const key = resolveSettingsKey(pathname.replace(/^\/settings[\/#]?/, ""));
  if (key === "general") return "data/user/settings/interface.json";
  if (key.startsWith("agent-")) return "data/user/settings/subagent.json";
  return STORAGE_PATHS[key] ?? STORAGE_PATHS[pathname] ?? null;
}
