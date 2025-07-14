import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import { useTranslation as useI18nTranslation } from 'react-i18next';

// Import translation files
import esTranslations from './locales/es_419.json';
import frTranslations from './locales/fr.json';
import jaTranslations from './locales/ja.json';
import koTranslations from './locales/ko.json';

const resources = {
  es: {
    translation: esTranslations,
  },
  fr: {
    translation: frTranslations,
  },
  ja: {
    translation: jaTranslations,
  },
  ko: {
    translation: koTranslations,
  },
};

i18n.use(initReactI18next).init({
  resources,
  lng: localStorage.getItem('language') || 'en',
  fallbackLng: 'en',

  interpolation: {
    escapeValue: false,
  },

  react: {
    useSuspense: false,
  },
});

export const useTranslation = () => {
  const { t, i18n } = useI18nTranslation();

  return {
    t,
    i18n,
    changeLanguage: i18n.changeLanguage,
    currentLanguage: i18n.language,
  };
};

export default i18n;
