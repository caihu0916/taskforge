// Copyright (c) 2024-2026 TaskForge Team
// SPDX-License-Identifier: BSL-1.1

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import { I18nextProvider } from 'react-i18next'
import { App as AntApp, ConfigProvider } from 'antd'
import { router } from './app/router'
import i18n from './lib/i18n'
import { initDesktopAdapter } from './lib/tauri-adapter'
import './index.css'
import './styles/themes/apple.css'
import { bootstrapTheme, buildAntdThemeConfig, useThemeStore } from './stores/theme'

function RootApp() {
  const theme = useThemeStore((s) => s.theme)
  const antdCfg = buildAntdThemeConfig(theme)

  return (
    <I18nextProvider i18n={i18n}>
      <ConfigProvider
        theme={{
          algorithm: antdCfg.algorithm,
          token: antdCfg.token,
        }}
      >
        <AntApp>
          <RouterProvider router={router} />
        </AntApp>
      </ConfigProvider>
    </I18nextProvider>
  )
}

bootstrapTheme()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RootApp />
  </StrictMode>,
)

initDesktopAdapter().catch((e) => {
  console.error('[TaskForge Desktop] Desktop adapter init failed:', e)
})
