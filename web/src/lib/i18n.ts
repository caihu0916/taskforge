// Copyright (c) 2024-2026 TaskForge Team
// SPDX-License-Identifier: BSL-1.1

import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './locales/en.json'
import zhCN from './locales/zh-CN.json'

const resources = {
  en: { translation: en },
  'zh-CN': { translation: zhCN },
}

const detectLocale = (): string => {
  try {
    const stored = localStorage.getItem('tf_locale')
    if (stored && ['en', 'zh-CN'].includes(stored)) return stored
  } catch {
    // localStorage unavailable (e.g. test environment)
  }
  return (navigator?.language?.startsWith('zh')) ? 'zh-CN' : 'en'
}

i18n
  .use(initReactI18next)
  .init({
    resources,
    lng: detectLocale(),
    fallbackLng: 'en',
    interpolation: {
      escapeValue: false,
    },
    react: {
      useSuspense: false,
    },
    saveMissing: false,
    missingKeyHandler: () => undefined,
  })

export const changeLanguage = (lang: string) => {
  if (['en', 'zh-CN'].includes(lang)) {
    localStorage.setItem('tf_locale', lang)
    i18n.changeLanguage(lang)
  }
}

export const supportedLanguages = [
  { code: 'en', name: 'English', nativeName: 'English' },
  { code: 'zh-CN', name: 'Chinese (Simplified)', nativeName: '简体中文' },
]

export default i18n
