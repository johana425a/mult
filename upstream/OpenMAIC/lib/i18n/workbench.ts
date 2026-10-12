/**
 * Pro workbench product copy.
 *
 * This map is shared by i18next (see `live.ts`) and hook-free presentation
 * helpers, which is why it is TypeScript and not one more locale JSON: the
 * presentation table (`components/workbench/chat/tool-presentation.ts`), the
 * progress captions and the session store are pure functions with no hook to
 * read a language from, so they take a translator and this module can build one
 * synchronously.
 *
 * The built-in English copy map is shared by all product surfaces. Unknown
 * locale requests fall back to readable English instead of exposing a key.
 */

export const workbenchEn = {
  common: {
    loading: 'Loading',
    send: 'Send',
    backToWorkspace: 'Back to workspace',
  },
  launch: {
    createFailed: 'Could not create the task. Please try again.',
    unknownSkill: 'That skill is no longer available. Retrying without it.',
  },
  chat: {
    stopFailed: 'Could not stop. Please try again.',
    sendFailed: 'Could not send. Please try again.',
    elementRefsNotAccepted: 'The server is temporarily unavailable. Please try again shortly.',
    jumpToBottom: 'Jump to bottom',
    interruptPlaceholder: 'Add a note, then press Enter to send',
    continuePlaceholder: 'Say what to do next, then press Enter to send',
    refsNeedInstruction: 'Type an instruction for the selected elements',
    stopping: 'Stopping…',
    stoppingAria: 'Stopping',
    stop: 'Stop this build',
    waiting: 'Processing',
    emptyTitle: 'Start a new conversation',
    emptyHint: 'Describe the change you want, or use @ to name a classroom',
  },
  question: {
    waiting: 'Waiting for your answer',
    answered: 'Answered',
    revive: 'Return to answer form',
    multiHint: 'Select any that apply, then choose “Confirm”',
    other: 'Other…',
    keyHint: '↑↓ Select · Enter Confirm',
    placeholder: 'Write your answer',
    confirm: 'Confirm',
    submit: 'Submit',
    dismiss: 'Dismiss',
    /**
     * The transcript row while this question owns the composer: the form below
     * already shows the question and its options, so the row says where the
     * answer goes instead of repeating them.
     */
    inFormBelow: 'Answer it in the form below',
    /**
     * How several picked labels become one message. It ends up in the user's own
     * bubble. The built-in English interface uses "A, B" for the joined labels.
     */
    multiAnswerSeparator: ', ',
  },
  material: {
    maxSelected: 'You can select up to {{count}} materials at once',
    remove: 'Remove {{name}}',
    removeFailed: 'Remove failed upload',
    uploadFailed: 'Could not upload {{name}}. Please try again.',
    fileTooLarge: 'File too large. Compress or split the file and try again.',
    fileTooLargeWithLimit: 'File too large. Please select a file no larger than {{limit}} MB.',
  },
  /**
   * The installed skills, as the product names them.
   *
   * A built-in skill's `title:` frontmatter can differ from its product name, and
   * the registry shares it with every surface — so the display name lives HERE, keyed by
   * the skill's own directory name (its `/handle`, the English contract that
   * never translates). The frontmatter stays the fallback: a user Skill has no
   * key, and neither does a built-in one whose copy has not landed yet.
   * `tests/workbench/workbench-i18n.test.ts` reconciles the skills directory
   * against this map, so a new built-in skill without a title here fails that
   * test rather than shipping an untranslated row in an English menu.
   *
   * `description` is NOT here on purpose: it is the model's selection contract
   * (the agent reads it to choose a skill), not product copy.
   */
  skill: {
    listFailed: 'Could not load the skill list',
    contentLoadFailed: 'Could not load the full Skill content',
    settings: {
      menuLabel: 'Skill settings',
      title: 'Skill settings',
      description:
        'Manage your skills: upload a zip to install one, download to share, remove what you no longer need.',
      upload: 'Upload skill',
      uploadZip: 'Upload a zip archive',
      uploadFolder: 'Upload a folder',
      officialDownload: 'OpenMAIC official skill',
      officialDownloadDesc:
        'Agent-guided SOP: import this skill into another agent workspace to get Live Demo classroom generation, local deployment, key configuration, classroom generation, and secondary development.',
      errNotZip: 'Only zip archives can be uploaded',
      errNoSkillMdZip: 'No SKILL.md found in the archive',
      errNoSkillMdFolder: 'No SKILL.md found in the folder',
      errNoName: 'The SKILL.md frontmatter is missing a name',
      errDuplicate: 'A skill named {{name}} already exists; rename it and retry',
      errTimeout: 'The upload timed out; please retry',
      errRejected: 'The server rejected this upload',
      retry: 'Retry',
      mySkills: 'My skills',
      builtinSkills: 'Built-in skills',
      emptyMySkills:
        'No skills of your own yet — upload a zip, or ask the agent in a chat to create one from history.',
      newUpload: 'new',
      refsNote: '· {{count}} reference docs',
      downloadLabel: 'Download',
      removeLabel: 'Delete',
      removeConfirm: 'Delete this skill? It will no longer be available in chats.',
      cancel: 'Cancel',
      confirmDelete: 'Delete',
    },
    title: {
      'build-personal-skill': 'Build a personal Skill',
      'curriculum-planner': 'Series planning',
      'zone-of-proximal-development': 'Practice lesson (zone of proximal development)',
      'stage-dsl': 'Classroom document structure',
      'deep-interactive': 'Deep interactive',
      'deep-research': 'Deep research',
      'fact-check': 'Fact Check',
      'feynman-learning': 'Feynman learning',
      'k12-core-literacy-planning': 'K-12 core-literacy design',
      'learning-to-learn': 'Learning to Learn',
      'lecture-style': 'Masterclass lecture',
      'page-clone': 'Page clone',
      'pptx-import': 'PPT import',
      'pro-editing': 'Professional editing',
      'slide-craft': 'Page design',
      'slide-dsl': 'Page data model',
      'social-emotional-learning': 'Social-emotional learning (SEL)',
      'spiral-curriculum': 'Spiral curriculum design',
      'stage-design': 'Classroom design',
      'style-clone': 'Deck style clone',
      'teacher-style-clone': 'Teacher style',
      'understanding-by-design': 'Understanding by Design (UbD)',
      vocational: 'Vocational training',
      'workshop-style': 'Interactive workshop',
    },
  },
  thinking: {
    active: 'Thinking…',
    done: 'Thought',
    doneWithDuration: 'Thought for {{duration}}',
  },
  system: {
    technicalDetails: 'Technical details',
    repeated: 'Same notice appeared {{count}} times in a row',
    resumed: 'Continued from the interruption',
    recovering: 'Generation was interrupted and is recovering automatically',
    steerQueued: 'The agent will respond after finishing the current step',
    runFailed: 'This build failed',
    retryHint: 'Send another message to retry',
    stopped: 'This build was stopped',
    workerInterrupted:
      'Interrupted by a worker restart. This call produced no result; the agent will retry it if needed.',
    userStopped: 'Interrupted by stop. This call produced no result.',
  },
  tool: {
    errorSeparator: ': ',
    recoverySeparator: '; ',
    /** How a list of names (the roster's cast) is joined on one row. */
    listSeparator: ', ',
    group: {
      tools: '{{count}} tool calls',
      skills: '{{count}} skills',
      running: 'Running',
      error: 'Has errors',
      done: 'Completed',
    },
    section: {
      input: 'Input',
      error: 'Error',
      result: 'Raw result',
      outline: 'Outline',
      process: 'Process',
      truncated: 'Result too long; truncated',
    },
    pageType: {
      quiz: 'Quiz',
      practice: 'Practice',
      interactive: 'Interactive',
      slide: 'Slide',
    },
    label: {
      listMaterials: 'Check materials',
      extractMaterial: 'Extract material',
      waitMaterials: 'Wait for material extraction',
      readMaterial: 'Read material',
      useMaterialMedia: 'Use material media',
      searchMaterial: 'Search materials',
      clipAudio: 'Clip reference audio',
      registerVoice: 'Register cloned voice',
      listVoices: 'List available voices',
      webSearch: 'Search the web',
      fetchUrl: 'Fetch webpage',
      readFile: 'Read file',
      loadSkill: 'Load skill',
      createSkillSaved: 'Skill saved',
      createSkillFailed: 'Could not save skill',
      readSkill: 'Read skill source',
      patchSkill: 'Edit skill',
      searchClassrooms: 'Search classrooms',
      readClassroom: 'Read classroom',
      searchChats: 'Search chats',
      readChat: 'Read chat',
      generateOutline: 'Plan classroom',
      generateScene: 'Generate page',
      generateSceneOrder: 'Generate page {{order}}',
      duplicateScene: 'Duplicate page',
      generateActions: 'Generate narration',
      generateActionsOrder: 'Generate narration for page {{order}}',
      generateTts: 'Synthesize speech',
      generateTtsOrder: 'Synthesize speech for page {{order}}',
      generateImage: 'Generate illustration',
      generateVideo: 'Generate video',
      previewScene: 'Preview page',
      readCourse: 'Read classroom',
      patchCourse: 'Edit classroom',
      grepCourse: 'Search classroom',
      editDeck: 'Reorder pages',
      editPage: 'Edit page',
      listScenes: 'Check current classroom',
      generateRoster: 'Design classroom roles',
      setRoster: 'Set classroom roles',
      importPptx: 'Import PPT',
      askUser: 'Ask you to confirm',
      createFolder: 'Create folder',
      moveToFolder: 'Move to folder',
      listFolderCourses: 'View classroom library',
      createStage: 'Create classroom',
      renameStage: 'Rename classroom',
      readStageOutline: 'Read classroom outline',
    },
    chip: {
      seconds: '{{count}} sec',
      results: '{{count}} results',
      grepHits: '{{count}} hits',
      untrustedSource: 'Source is outside this session',
      availableInNewSession: 'Available in a new session',
      records: '{{count}} records',
      moreResults: 'More results available',
      pages: '{{count}} pages',
      constraintViolations: '{{count}} constraint violations',
      reusedOutline: 'Reused existing outline',
      reviseAsDirected: 'Revised as directed',
      pageOrder: 'Page {{order}}',
      duplicateExists: 'Copy already exists',
      actions: '{{count}} actions',
      voicedLines: '{{count}} lines voiced',
      unvoicedLines: '{{count}} lines without audio',
      synthesizedLines: '{{count}} lines synthesized',
      existingLines: '{{count}} lines already had audio',
      failedLines: '{{count}} lines failed',
      persistedPages: '{{count}} pages saved',
      missingPages: '{{count}} pages missing',
      roles: '{{count}} roles',
      noVoices: 'No voices available',
      notesPages: '{{count}} pages with speaker notes',
      sourceTruncated: 'Source had {{count}} pages; truncated',
      truncated: 'Truncated',
      options: '{{count}} options',
      courses: '{{count}} classrooms',
      allCourses: 'All classrooms',
      folderCourses: 'Classrooms in a folder',
      reusedCourse: 'Reused existing classroom',
      movedToFolder: 'Moved to folder',
    },
    error: {
      materialExtraction: 'Material extraction failed',
      listMaterials: 'Could not check materials',
      readMaterial: 'Could not read material',
      searchMaterial: 'Could not search materials',
      clipAudio: 'Could not clip reference audio',
      registerVoice: 'Could not register cloned voice',
      listVoices: 'Could not list available voices',
      webSearch: 'Search failed',
      fetchUrl: 'Could not fetch webpage',
      readFile: 'Could not read file',
      loadSkill: 'Could not load skill',
      createSkill: 'Skill was not saved',
      readSkill: 'Could not read the skill',
      patchSkill: 'Skill was not changed',
      historyRead: 'Could not read history',
      generateOutline: 'Could not plan the classroom',
      generateScene: 'Could not generate page {{order}}',
      duplicateScene: 'Could not duplicate page',
      generateActions: 'Could not generate narration',
      noTtsProvider: 'Speech synthesis is not configured, so this page still has no audio',
      generateTts: 'Could not synthesize speech',
      generateImage: 'Could not generate illustration',
      generateVideo: 'Could not generate video',
      previewScene: 'Could not generate page preview',
      readCourse: 'Could not read the classroom',
      patchCourse: 'Could not edit the classroom',
      grepCourse: 'Could not search the classroom',
      editPage: 'Could not apply the edit',
      listScenes: 'Could not read the classroom',
      roster: 'Could not set the classroom roles',
      importPptx: 'Could not import the PPT',
      askUser: 'Could not send this question',
      createFolder: 'Could not create the folder',
      moveToFolder: 'Could not move the classroom into the folder',
      listFolderCourses: 'Could not read the classroom library',
      createStage: 'Could not create the classroom',
      renameStage: 'Could not rename the classroom',
      readStageOutline: 'Could not read the classroom outline',
      generic: 'Tool call failed',
    },
    progress: {
      scene: {
        prep: 'Lock page',
        content: 'Write content',
        actions: 'Add actions',
        save: 'Save',
        aligning: 'Aligning this page',
        arrangingReturnedActions: 'Actions are ready; arranging them',
        arrangingActions: 'Arranging classroom actions',
        layingOutReturnedContent: 'Layout is ready; placing it on the page',
        draftingContent: 'Drafting page content',
        failed: 'Could not generate this page',
        done: 'Page saved',
      },
      outline: {
        read: 'Read brief',
        plan: 'Plan structure',
        write: 'Write outline',
        reading: 'Reading your brief',
        ordering: 'Organizing page order',
        planning: 'Planning classroom structure',
        failed: 'Could not plan the outline',
        done: 'Outline ready',
      },
    },
  },
} as const;

type LocaleShape<T> = {
  readonly [K in keyof T]: T[K] extends string ? string : LocaleShape<T[K]>;
};

/** Compatibility export: every built-in surface uses the English copy map. */
export const workbenchZh = workbenchEn;

export type WorkbenchCopyKey = `workbench.${string}`;

export type WorkbenchTranslator = (
  key: WorkbenchCopyKey,
  options?: Record<string, unknown>,
) => string;

function readPath(value: unknown, path: readonly string[]): unknown {
  let current = value;
  for (const part of path) {
    if (!current || typeof current !== 'object') return undefined;
    current = (current as Record<string, unknown>)[part];
  }
  return current;
}

type WorkbenchResource = Record<string, unknown>;

/**
 * Optional locale overlays. This distribution includes English only, so the
 * hook-free translator and the React `t` resolve the same English strings.
 */
const localeOverrides: Record<string, WorkbenchResource> = {};

function isRecord(value: unknown): value is WorkbenchResource {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function mergeResource(base: WorkbenchResource, overlay: WorkbenchResource): WorkbenchResource {
  const result: WorkbenchResource = { ...base };
  for (const [key, value] of Object.entries(overlay)) {
    result[key] =
      isRecord(value) && isRecord(result[key])
        ? mergeResource(result[key] as WorkbenchResource, value)
        : value;
  }
  return result;
}

const resourceCache = new Map<string, WorkbenchResource>();

/**
 * The whole workbench copy map for one locale — the resource i18next registers
 * under `workbench.*` and the table the hook-free translator reads.
 */
export function workbenchResourceFor(locale: string): WorkbenchResource {
  const cached = resourceCache.get(locale);
  if (cached) return cached;
  const base: WorkbenchResource = workbenchEn;
  const overlay = localeOverrides[locale];
  const resource = overlay ? mergeResource(base, overlay) : base;
  resourceCache.set(locale, resource);
  return resource;
}

/** Hook-free translator for pure presentation helpers and unit tests. */
export function createWorkbenchTranslator(locale: string): WorkbenchTranslator {
  const resource = workbenchResourceFor(locale);
  return (key, options) => {
    const path = key.replace(/^workbench\./, '').split('.');
    const value = readPath(resource, path);
    if (typeof value !== 'string') return key;
    return value.replace(/{{(\w+)}}/g, (_, name: string) => String(options?.[name] ?? ''));
  };
}

export const defaultWorkbenchTranslator = createWorkbenchTranslator('en-US');
