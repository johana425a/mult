import { supportedLocales } from './locales';

export type Locale = (typeof supportedLocales)[number]['code'];

export const defaultLocale: Locale =
  process.env.NEXT_PUBLIC_DEEPSTEAM_DEFAULT_LANGUAGE === 'zh' ? 'zh-CN' : 'en-US';
