/**
 * DeepSteam application display identity. Upstream names, package IDs and user
 * content do not pass through this module's static catalog adapter.
 */
export const PRODUCT_NAME = "DeepSteam";
export const PRODUCT_MARK = "/deepsteam-mark.svg";

/** Reviewed application-copy keys; keys remain compatible with upstream i18n. */
export const PRODUCT_COPY_KEYS: ReadonlySet<string> = new Set([
  "Attach its textbook or knowledge base and DeepTutor can start planning from the material itself.",
  "Attach its textbook, then let DeepTutor plan from there.",
  "Bring a paper, book, web page, lecture or recording. DeepTutor will keep the material, notes and conversations together.",
  "Configure your endpoints below, run tests, then launch DeepTutor.",
  "Connect to a searchable ZIM already served by kiwix-serve. DeepTutor reads matching articles on demand and does not import the archive.",
  "DeepTutor Admin · User Management",
  "DeepTutor Drafting…",
  "DeepTutor Exploring…",
  "DeepTutor Logo",
  "DeepTutor Planning…",
  "DeepTutor Quizzing…",
  "DeepTutor Reasoning…",
  "DeepTutor Reflecting…",
  "DeepTutor Responding…",
  "DeepTutor asks",
  "DeepTutor can make mistakes. Please verify important information.",
  "DeepTutor responded.",
  "DeepTutor searches and browses this library, and reads full sources when a matched snippet is too short. It only writes to IMA when you ask it to.",
  "DeepTutor will respond in {{count}}s. Continue here to keep discussing.",
  "DeepTutor · Agent-Native Learning",
  "Each knowledge base connects one searchable ZIM on one kiwix-serve instance. Connect other archives or servers separately. DeepTutor reads matching articles on demand.",
  "Embedding requests are sent to this URL exactly; DeepTutor does not append /embeddings or /api/embed at request time.",
  "Every call DeepTutor makes on its own runs here unless the task below names its own model.",
  "Everything DeepTutor remembers about you, organised across three layers. Click into any layer to inspect or curate it.",
  "Hosted engine: the library lives in Tencent IMA and DeepTutor keeps no copy. Requires an IMA Client ID and API key. Chat searches it, browses its documents, reads full sources, and — only when you ask — collects a web page or saves a note.",
  "Import a ChatGPT data export or add a Claude Code or Codex folder, then open any conversation to continue it in DeepTutor.",
  "Import a local Claude Code or Codex folder, or choose the conversations.json file from an official ChatGPT data export. DeepTutor parses it in your browser before saving the conversations you import.",
  "Make DeepTutor feel at home. Apply your preferences using the bar below.",
  "Make DeepTutor feel at home. Preferences here are saved automatically.",
  "Manage home suggestions and how long DeepTutor waits for replies.",
  "Max rounds DeepTutor may ask",
  "Mix as many sources as useful — your library, and the work you have already done here. Your goal is always included; the rest grounds the outline in your own material.",
  "Model usage and activity across your saved DeepTutor conversations.",
  "Name a subject and DeepTutor writes you a book on it — a spine of chapters first, then each page written out in full.",
  "Network settings saved. Restart DeepTutor to apply them.",
  "No adapter for this model type is on record for this provider. DeepTutor calls it as an OpenAI-compatible endpoint derived from the provider URL; run the model test below to confirm it answers.",
  "One unit per line. Add keywords after a | so DeepTutor can tell which questions belong to it:\n\nProcesses and threads | context switch, scheduling\nVirtual memory | address translation, page replacement",
  "Only the backend and its own children. Start DeepTutor through the launcher to include the web server.",
  "Override what DeepTutor assumes about this model. Auto follows the built-in tables.",
  "Pick Auto to let DeepTutor decide, or choose specific skills to apply.",
  "Pick your local .claude or .codex folder — DeepTutor finds each project and brings the chats in.",
  "Point DeepTutor at a folder that is your Obsidian vault. Nothing is uploaded or copied — DeepTutor reads (and, when you ask, writes) the notes in place. The path must be reachable by the server, so this works on a local / self-hosted DeepTutor.",
  "Redirecting to DeepTutor in {{count}}s...",
  "Reserved — uses DeepTutor's vision model to caption images during conversion.",
  "Search articles in this ZIM. DeepTutor retrieves matches for chat, Book, and Guided Learning without importing the archive.",
  "Select your local .claude or .codex folder. DeepTutor reads it right here in your browser — nothing leaves your machine until you choose what to import.",
  "Sending to DeepTutor",
  "Set up with DeepTutor",
  "Sign in with your Invidious account, then approve read-only access to return here. Your DeepTutor login is separate.",
  "Stored at memory/backup/{{name}}. v2 starts fresh — interact with DeepTutor and click Update on each doc to build memory.",
  "Tell DeepTutor what you want to learn, mix in your books, notes, and knowledge bases, and it will draft the first outline.",
  "The MinerU CLI must be reachable by the DeepTutor server process. Reserve >=20 GB of free disk (official guidance): ~2-4 GB install, ~1-2 GB models lazily downloaded on first parse, plus parsing cache.",
  "The MinerU CLI must be visible to the DeepTutor server process.",
  "The base URL of your self-hosted WeKnora deployment. Documents remain there; DeepTutor only runs retrieval searches.",
  "The model behind the calls DeepTutor makes on its own — titles, suggestions, lookups. Set one for all of them, or give a task its own.",
  "The model behind work DeepTutor starts on its own, rather than in a turn you asked for.",
  "This Bilibili video would not load in an embedded player. Open it on Bilibili; DeepTutor can still use its captions.",
  "This engine ships as an optional dependency. Install it, then restart DeepTutor to enable it.",
  "This test runs from the DeepTutor backend. In Docker, localhost points to the DeepTutor container. Use a shared-network service name and container port, or host.docker.internal and the published host port.",
  "This video's owner disabled embedded playback. Open it on YouTube; DeepTutor can still use captions when they are available.",
  "Track a GitHub repo's Markdown docs. DeepTutor auto-syncs daily; you can also trigger a sync manually.",
  "Uploaded to DeepTutor",
  "Use a folder path on the machine running DeepTutor. Linking records the source; files are not imported until you click Sync now.",
  "Verified by DeepTutor Logic Engine",
  "Verified by DeepTutor Vision Engine",
  "Welcome to DeepTutor",
  "What DeepTutor has noticed",
  "When you are ready, click here to test and launch DeepTutor.",
  "Your DeepTutor login expired during authorization. Sign in, then start a new Invidious connection.",
  "codebuddy.auth.description",
  "codebuddy.auth.sdkMissing",
  "codex.oauth.callbackMissing",
  "codex.oauth.callbackMissingUnknown",
  "codex.oauth.callbackUnavailable",
  "codex.oauth.invalidResponse",
  "codex.oauth.isolated",
  "settings.agentSetup.instructions",
  "settings.agentSetup.description",
  "settings.agentSetup.prompt",
  "settings.configNote",
  "settings.serviceConfig.video",
  "settingsTour.status.desc",
  "Your place is kept, and the tutor reads along with you",
  "Every provider is selectable. One with no adapter on record for this model type is called as an OpenAI-compatible endpoint derived from its provider URL — add the model, then run the model test to see whether it answers.",
]);

/**
 * Adapt only bundled static catalog values, before i18next interpolates user
 * filenames or agent names. Never use this function on API data or messages.
 * Repository paths, URLs, package names and technical IDs remain verbatim.
 */
export function brandAppCatalog<T extends Record<string, string>>(catalog: T): T {
  return Object.fromEntries(
    Object.entries(catalog).map(([key, value]) => [
      key,
      PRODUCT_COPY_KEYS.has(key)
        ? value.replace(/(^|[^A-Za-z0-9_/.-])DeepTutor(?![A-Za-z0-9_/-]|\.[A-Za-z0-9])/g, `$1${PRODUCT_NAME}`)
        : value,
    ]),
  ) as T;
}

