import i18n from 'i18next';
import { useTranslation } from 'react-i18next';

/** Product integration copy shares the current UI locale without changing IDs. */
export function standaloneCopy(text: string): string {
  return i18n.t(text, { ns: 'deepsteam', nsSeparator: false, keySeparator: false, defaultValue: text });
}

/** Subscribe component rendering to language changes, including helper labels. */
export function useStandaloneCopy(): void {
  useTranslation('deepsteam');
}
