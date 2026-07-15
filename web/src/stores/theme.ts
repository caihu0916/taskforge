// Copyright (c) 2024-2026 TaskForge Team
// SPDX-License-Identifier: BSL-1.1

import { create } from 'zustand'
import { theme } from 'antd'

/** 可用主题 —— 3 套 Apple HIG 风格主题 */
export type ThemeKey =
  | 'apple-light'
  | 'apple-dark'
  | 'apple-graphite'

/** 对外统一的元数据 —— 用于主题切换器的展示 */
export interface ThemeMeta {
  key: ThemeKey
  label: string
  description: string
  labelKey: string
  descriptionKey: string
  swatches: string[]
  isApple?: boolean
}

export const THEME_LIST: ThemeMeta[] = [
  {
    key: 'apple-light',
    label: 'Apple · Liquid',
    description: '液态玻璃 · Apple Blue 0071E3',
    labelKey: 'common.themeSwitcher.appleLiquid',
    descriptionKey: 'common.themeSwitcher.appleLiquidDesc',
    swatches: ['#F5F5F7', '#FFFFFF', '#0071E3', '#34C759'],
    isApple: true,
  },
  {
    key: 'apple-dark',
    label: 'Apple · Midnight',
    description: 'OLED 纯黑 · 深空灰 1C1C1E',
    labelKey: 'common.themeSwitcher.appleMidnight',
    descriptionKey: 'common.themeSwitcher.appleMidnightDesc',
    swatches: ['#000000', '#1C1C1E', '#0A84FF', '#30D158'],
    isApple: true,
  },
  {
    key: 'apple-graphite',
    label: 'Apple · Graphite',
    description: '石墨灰 · 高级感中性配色',
    labelKey: 'common.themeSwitcher.appleGraphite',
    descriptionKey: 'common.themeSwitcher.appleGraphiteDesc',
    swatches: ['#E8E8ED', '#F2F2F7', '#3A3A3C', '#5E5CE6'],
    isApple: true,
  },
]

const STORAGE_KEY = 'taskforge-theme'
const DEFAULT_THEME: ThemeKey = 'apple-light'

/** 读初始主题 —— 支持 SSR / No-Window 环境安全 */
function readInitialTheme(): ThemeKey {
  if (typeof window === 'undefined') return DEFAULT_THEME
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored) {
      const match = THEME_LIST.find((t) => t.key === (stored as ThemeKey))
      if (match) return match.key
    }
    if (window.matchMedia?.('(prefers-color-scheme: dark)').matches) {
      return 'apple-dark'
    }
  } catch (_e) {
    // ignore
  }
  return DEFAULT_THEME
}

/** 判断当前主题是否为 Apple 家族 */
export function isAppleTheme(themeKey: ThemeKey): boolean {
  return themeKey.startsWith('apple')
}

/** 判断是否为暗色系 */
export function isDarkTheme(themeKey: ThemeKey): boolean {
  return themeKey === 'apple-dark'
}

/** 从主题 Key 推导出 AntD ConfigProvider 的主题配置 */
export function buildAntdThemeConfig(key: ThemeKey): {
  algorithm: typeof theme.defaultAlgorithm | typeof theme.darkAlgorithm
  token: Record<string, string | number>
  components?: Record<string, Record<string, string | number | boolean>>
} {
  // ===== Apple Themes —— 基于 Apple Human Interface Guidelines
  const appleBase: Record<string, string | number> = {
    colorPrimary: '#0071e3',
    borderRadius: 12,
    colorInfo: '#0071e3',
    colorSuccess: '#34c759',
    colorWarning: '#ff9500',
    colorError: '#ff3b30',
    colorLink: '#0071e3',
    fontSize: 14,
    controlHeight: 36,
    controlHeightLG: 44,
  }

  // ===== Apple 组件级 Token（跨主题通用） =====
  const appleComponents: Record<string, Record<string, string | number | boolean>> = {
    Button: {
      borderRadius: 9999,
      controlHeight: 36,
      controlHeightLG: 44,
      controlHeightSM: 32,
      paddingInline: 20,
      fontWeight: 500,
    },
    Card: {
      borderRadius: 16,
      paddingLG: 20,
    },
    Input: {
      borderRadius: 12,
      controlHeight: 36,
      paddingInline: 12,
    },
    InputNumber: {
      borderRadius: 12,
      controlHeight: 36,
    },
    Select: {
      borderRadius: 12,
      controlHeight: 36,
      optionFontSize: 14,
    },
    Badge: {
      borderRadius: 9999,
    },
    Tag: {
      borderRadius: 9999,
    },
    Switch: {
      trackHeight: 31,
      trackMinWidth: 51,
    },
    Modal: {
      borderRadius: 16,
    },
    Tooltip: {
      borderRadius: 8,
    },
    Tabs: {
      horizontalMargin: '0 0 0 0',
    },
    Menu: {
      itemBorderRadius: 8,
      itemMarginInline: 4,
    },
    Table: {
      borderRadius: 12,
      headerBorderRadius: 12,
    },
    Message: {
      borderRadius: 12,
    },
    Notification: {
      borderRadius: 16,
    },
  }

  if (key === 'apple-light') {
    return {
      algorithm: theme.defaultAlgorithm,
      token: {
        ...appleBase,
        colorBgContainer: '#ffffff',
        colorBgElevated: '#ffffff',
        colorBgLayout: '#f5f5f7',
        colorBorder: 'rgba(0,0,0,0.08)',
        colorBorderSecondary: 'rgba(0,0,0,0.04)',
        colorText: '#1d1d1f',
        colorTextSecondary: '#6e6e73',
        colorTextTertiary: '#86868b',
        colorFill: 'rgba(0,0,0,0.06)',
        colorFillSecondary: 'rgba(0,0,0,0.04)',
        colorFillTertiary: 'rgba(0,0,0,0.02)',
      },
      components: appleComponents,
    }
  }

  if (key === 'apple-dark') {
    return {
      algorithm: theme.darkAlgorithm,
      token: {
        ...appleBase,
        colorPrimary: '#0a84ff',
        colorInfo: '#0a84ff',
        colorSuccess: '#30d158',
        colorWarning: '#ff9f0a',
        colorError: '#ff453a',
        colorLink: '#0a84ff',
        colorBgContainer: '#1c1c1e',
        colorBgElevated: '#2c2c2e',
        colorBgLayout: '#000000',
        colorBorder: 'rgba(255,255,255,0.10)',
        colorBorderSecondary: 'rgba(255,255,255,0.06)',
        colorText: '#f5f5f7',
        colorTextSecondary: '#a1a1a6',
        colorTextTertiary: '#8e8e93',
        colorFill: 'rgba(255,255,255,0.12)',
        colorFillSecondary: 'rgba(255,255,255,0.08)',
        colorFillTertiary: 'rgba(255,255,255,0.04)',
      },
      components: appleComponents,
    }
  }

  // apple-graphite
  return {
    algorithm: theme.defaultAlgorithm,
    token: {
      ...appleBase,
      colorPrimary: '#3a3a3c',
      colorInfo: '#5e5ce6',
      colorBgContainer: '#ffffff',
      colorBgElevated: '#ffffff',
      colorBgLayout: '#e8e8ed',
      colorBorder: 'rgba(0,0,0,0.10)',
      colorBorderSecondary: 'rgba(0,0,0,0.05)',
      colorText: '#1c1c1e',
      colorTextSecondary: '#48484a',
      colorTextTertiary: '#636366',
      colorFill: 'rgba(58,58,60,0.08)',
      colorFillSecondary: 'rgba(58,58,60,0.05)',
    },
    components: appleComponents,
  }
}

export interface ThemeStore {
  theme: ThemeKey
  setTheme: (t: ThemeKey) => void
  toggleTheme: () => void
  isApple: boolean
  isDark: boolean
}

export const useThemeStore = create<ThemeStore>((set, get) => ({
  theme: readInitialTheme(),
  isApple: isAppleTheme(readInitialTheme()),
  isDark: isDarkTheme(readInitialTheme()),
  setTheme: (t: ThemeKey) => {
    if (typeof document !== 'undefined') {
      document.documentElement.setAttribute('data-theme', t)
    }
    if (typeof window !== 'undefined') {
      try {
        window.localStorage.setItem(STORAGE_KEY, t)
      } catch (_e) {
        // ignore
      }
    }
    set({ theme: t, isApple: isAppleTheme(t), isDark: isDarkTheme(t) })
    void get
  },
  toggleTheme: () => {
    const current = get().theme
    const order: ThemeKey[] = ['apple-light', 'apple-dark', 'apple-graphite']
    const idx = order.indexOf(current)
    const next = order[(idx + 1) % order.length]
    get().setTheme(next)
  },
}))

/** 启动时写入一次 data-theme（避免首次加载闪烁） */
export function bootstrapTheme(): void {
  if (typeof document === 'undefined') return
  const t = useThemeStore.getState().theme
  document.documentElement.setAttribute('data-theme', t)
}
