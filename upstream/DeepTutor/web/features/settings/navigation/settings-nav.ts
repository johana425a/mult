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
    label: { en: "Voice", zh: "语音" },
    blurb: {
      en: "Speech synthesis and transcription models with saved providers.",
      zh: "配置语音合成和语音转写模型及其提供方。",
    },
    icon: AudioLines,
    tile: "bg-rose-500/10 text-rose-600",
  },
  {
    key: "multimodal",
    href: "/settings/multimodal",
    label: { en: "Multimodal generation", zh: "多模态生成" },
    blurb: {
      en: "Image and video generation models with saved providers.",
      zh: "配置图像和视频生成模型及其提供方。",
    },
    icon: ImageIcon,
    tile: "bg-violet-500/10 text-violet-600",
  },
  {
    key: "connections",
    href: "/settings#connections",
    label: { zh: "提供方", en: "Providers" },
    blurb: {
      zh: "管理提供方名称、地址、凭据与连接。",
      en: "Manage provider names, addresses, credentials, and connectivity.",
    },
    icon: KeyRound,
    tile: "bg-sky-500/10 text-sky-600 dark:text-sky-400",
  },
  {
    key: "llm",
    href: "/settings#llm",
    label: { zh: "语言模型", en: "Language models" },
    blurb: {
      zh: "管理模型名称、上下文长度、能力与连接测试。",
      en: "Model names, context windows, capabilities, and connection tests.",
    },
    icon: Brain,
    tile: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
    service: "llm",
  },
  {
    key: "task-models",
    href: "/settings#task-models",
    label: { zh: "后台任务模型", en: "Task models" },
    blurb: {
      zh: `${PRODUCT_NAME} 执行后台任务时使用的模型。`,
      en: `The model behind the calls ${PRODUCT_NAME} makes on its own.`,
    },
    icon: ListChecks,
    tile: "bg-cyan-500/10 text-cyan-600 dark:text-cyan-400",
  },
  {
    key: "embedding",
    href: "/settings#embedding",
    label: { zh: "嵌入模型", en: "Embedding models" },
    blurb: {
      zh: "管理嵌入模型、向量维度与连接测试。",
      en: "Embedding models, dimensions, and connection tests.",
    },
    icon: Database,
    tile: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
    service: "embedding",
  },
  {
    key: "search",
    href: "/settings#search",
    label: { zh: "搜索", en: "Search" },
    blurb: { zh: "配置网络搜索提供方。", en: "Web search providers." },
    icon: Search,
    tile: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
    service: "search",
  },
  {
    key: "tts",
    href: "/settings#tts",
    label: { zh: "语音合成", en: "Text-to-Speech" },
    blurb: {
      zh: "将回复转换为语音并朗读。",
      en: "Text-to-speech for reading replies aloud.",
    },
    icon: AudioLines,
    tile: "bg-rose-500/10 text-rose-600 dark:text-rose-400",
    service: "tts",
  },
  {
    key: "stt",
    href: "/settings#stt",
    label: { zh: "语音转写", en: "Speech-to-Text" },
    blurb: {
      zh: "将麦克风输入转写为文字。",
      en: "Speech-to-text for the composer microphone.",
    },
    icon: Mic,
    tile: "bg-pink-500/10 text-pink-600 dark:text-pink-400",
    service: "stt",
  },
  {
    key: "imagegen",
    href: "/settings#imagegen",
    label: { zh: "图像生成", en: "Image Generation" },
    blurb: {
      zh: "对话图像生成工具使用的文生图模型。",
      en: "Text-to-image model for the chat imagegen tool.",
    },
    icon: ImageIcon,
    tile: "bg-fuchsia-500/10 text-fuchsia-600 dark:text-fuchsia-400",
    service: "imagegen",
  },
  {
    key: "videogen",
    href: "/settings#videogen",
    label: { zh: "视频生成", en: "Video Generation" },
    blurb: {
      zh: "对话视频生成工具使用的文生视频模型。",
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
    label: { zh: "视频学习", en: "Video Learning" },
    blurb: {
      zh: "配置 YouTube 与本地 Invidious 播放服务。",
      en: "Native YouTube and local Invidious playback providers.",
    },
    icon: Clapperboard,
    tile: "bg-red-500/10 text-red-600 dark:text-red-400",
    adminOnly: true,
  },
  {
    key: "tools",
    href: "/settings#tools",
    label: { zh: "工具", en: "Tools" },
    blurb: {
      zh: "对话智能体可以调用的内置工具。",
      en: "Built-in tools the chat agent can invoke.",
    },
    icon: Wrench,
    tile: "bg-orange-500/10 text-orange-600 dark:text-orange-400",
  },
  {
    key: "capabilities",
    href: "/settings#capabilities",
    label: { zh: "能力", en: "Capabilities" },
    blurb: {
      zh: "配置各项能力使用的模型参数与运行选项。",
      en: "Per-capability LLM parameters and runtime knobs.",
    },
    icon: SlidersHorizontal,
    tile: "bg-lime-500/10 text-lime-600 dark:text-lime-400",
  },
  {
    key: "starters",
    href: "/settings#starters",
    label: { zh: "对话起点", en: "Starting points" },
    blurb: {
      zh: "控制输入框下方建议使用多少历史对话。",
      en: "How much history shapes the three lines under the composer.",
    },
    icon: Sparkles,
    tile: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
  },
  {
    key: "attachments",
    href: "/settings#attachments",
    label: { zh: "附件", en: "Attachments" },
    blurb: {
      zh: "配置对话附件的上传与内容提取选项。",
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
      zh: "配置本地 Claude Code 的模型、推理强度与运行参数。",
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
      zh: "配置本地 Codex 的模型、推理强度与运行参数。",
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
      zh: "配置本地 Grok CLI 的模型、推理强度与权限模式。",
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
      zh: "配置本地 Antigravity CLI 的模型与运行参数。",
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
      zh: "配置本地 Kimi CLI 的模型与运行参数。",
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
      zh: "配置本地 opencode 的模型、推理强度与运行参数。",
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
      zh: "配置本地 MiMo Code 的模型、推理强度与运行参数。",
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
      zh: "配置本地 Hermes Agent 的模型、推理强度与运行参数。",
      en: "Model, reasoning effort, and run params for the local Hermes Agent.",
    },
    icon: HermesGlyph as unknown as LucideIcon,
    tile: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
    adminOnly: true,
  },
  {
    key: "agent-hermes-remote",
    href: "/settings#agent-hermes-remote",
    label: { zh: "Hermes Agent（远程）", en: "Hermes Agent (remote)" },
    blurb: {
      zh: "通过 HTTP 调用远程 Hermes Agent，并保留每段对话的会话。",
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
      zh: "配置 OpenClaw 智能体的网关或本地运行参数。",
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
      zh: "配置 DeepSeek Harness 的 Python SDK 或后台命令行。",
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
    label: { zh: "外观", en: "Appearance" },
    blurb: { zh: "主题与代码块", en: "Theme and code blocks" },
    icon: Palette,
    href: "/settings#appearance",
  },
  {
    key: "network",
    label: { zh: "网络", en: "Network" },
    blurb: {
      zh: "端口、浏览器接口地址与跨域设置",
      en: "Ports, browser API base, and CORS",
    },
    icon: Network,
    href: "/settings#network",
  },
  {
    key: "workspace",
    label: { zh: "工作区", en: "Workspace" },
    blurb: {
      zh: "系统、通用与自定义工作区、根目录及存储迁移",
      en: "System, general and custom workspaces, root folder and storage migration",
    },
    icon: FolderOpen,
    href: "/settings#workspace",
  },
  {
    key: "models",
    label: { zh: "模型", en: "Models" },
    blurb: {
      zh: "语言、嵌入、搜索、语音与生成模型",
      en: "Language, embedding, search, voice, and generation models",
    },
    icon: Boxes,
    href: "/settings#models",
    children: MODEL_CHILDREN,
  },
  {
    key: "knowledge",
    label: { zh: "知识库", en: "Knowledge Base" },
    blurb: { zh: "文档解析引擎", en: "Document parsing engine" },
    icon: Library,
    href: "/settings#document-parsing",
  },
  {
    key: "chat",
    label: { zh: "聊天", en: "Chat" },
    blurb: {
      zh: "工具、能力与附件",
      en: "Tools, capabilities, and attachments",
    },
    icon: MessagesSquare,
    href: "/settings#chat",
    children: CHAT_CHILDREN,
  },
  {
    key: "agents",
    label: { zh: "伙伴与智能体", en: "Partners & Agents" },
    blurb: {
      zh: "配置可以在对话中调用的子智能体",
      en: "Configure the subagents you can call on in chat",
    },
    icon: Bot,
    href: "/settings#agents",
    children: AGENT_CHILDREN,
  },
  {
    key: "progress",
    label: { zh: "学习进度", en: "Learning progress" },
    blurb: { zh: "查看阅读与学习活动。", en: "Review your reading and learning activity." },
    icon: ChartNoAxesCombined,
    href: "/settings/progress",
  },
  {
    key: "learner-profile",
    learnerOnly: true,
    label: { zh: "学习者资料", en: "Learner profile" },
    blurb: {
      zh: "调整年龄、年级与讲解偏好。",
      en: "Adjust age, grade, and explanation preferences.",
    },
    icon: UserRound,
    href: "/settings#learner-profile",
  },
  {
    key: "guardian",
    guardianOnly: true,
    label: { zh: "监护人", en: "Guardian" },
    blurb: {
      zh: "查看获授权的学习者与学习资料。",
      en: "Review authorized learners and learning materials.",
    },
    icon: ShieldCheck,
    href: "/settings#guardian",
  },
  {
    key: "memory",
    label: { zh: "记忆", en: "Memory" },
    blurb: {
      zh: "内容分块、容量、去重与引用策略",
      en: "Chunking, budget, dedup, and reference policies",
    },
    icon: BrainCircuit,
    href: "/settings#memory",
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
