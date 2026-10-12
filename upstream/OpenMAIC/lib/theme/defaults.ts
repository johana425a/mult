// DeepSteam app chrome only: slide/document themes retain their own settings.
export const DEFAULT_THEME = 'dark' as const;

// Run before the first paint. Browser preferences always win; unavailable
// storage falls back to the same warm-dark palette as the desktop shell.
export const THEME_BOOTSTRAP_SCRIPT = `
  (function () {
    var theme = 'dark';
    try {
      var saved = localStorage.getItem('theme');
      if (saved === 'light' || saved === 'dark' || saved === 'system') theme = saved;
    } catch (_) {}
    var dark = theme === 'dark' ||
      (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.classList.toggle('dark', dark);
    document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
  })();
`;
