type LocalizedCopy = { zh: string; en: string };

export const TEACH_FIRST_PROFILE_LABEL: LocalizedCopy = {
  zh: "Teach first, then check understanding",
  en: "Teach first, then check understanding",
};

export const NEXT_LABELS: Record<string, LocalizedCopy> = {
  probe: {
    zh: "Start with a probe and test out if you already know it",
    en: "Start with a probe and test out if you already know it",
  },
  teach: {
    zh: "Learn this knowledge point before checking understanding",
    en: "Learn this knowledge point before checking understanding",
  },
  practice: {
    zh: "Practice until you reliably clear the mastery gate",
    en: "Practice until you reliably clear the mastery gate",
  },
  assess: {
    zh: "Explain this clearly in your own words",
    en: "Explain this clearly in your own words",
  },
  review: { zh: "Revisit this memory beacon", en: "Revisit this memory beacon" },
  answer_pending: {
    zh: "Complete the answer your tutor is waiting for",
    en: "Complete the answer your tutor is waiting for",
  },
  complete: {
    zh: "The whole territory is illuminated",
    en: "The whole territory is illuminated",
  },
};

export const NEXT_CTA_LABELS: Record<string, LocalizedCopy> = {
  teach: { zh: "Learn this knowledge point", en: "Learn this knowledge point" },
  review: { zh: "Start this review", en: "Start this review" },
  answer_pending: {
    zh: "Answer in the original session",
    en: "Answer in the original session",
  },
  complete: { zh: "Keep exploring", en: "Keep exploring" },
};
