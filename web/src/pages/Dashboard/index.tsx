// Copyright (c) 2024-2026 TaskForge Team
// SPDX-License-Identifier: BSL-1.1

import { useTranslation } from 'react-i18next'
import { useAuthStore } from '../../stores/auth'

export default function Dashboard() {
  const { t } = useTranslation()
  const user = useAuthStore((s) => s.user)
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)

  return (
    <div className="min-h-screen bg-bg-primary p-8">
      <div className="dash-root">
        <div className="dash-header">
          <div>
            <h1 className="dash-title">{t('dashboardPage.title')}</h1>
            <p className="dash-subtitle">{t('dashboardPage.welcome')}</p>
          </div>
        </div>
        <div className="dash-content-grid">
          <div className="tf-card">
            <h2 className="text-lg font-semibold mb-4 text-text-primary">
              {t('dashboardPage.subtitle')}
            </h2>
            <p className="text-text-secondary">
              {isAuthenticated()
                ? `Logged in as: ${user?.username ?? 'User'}`
                : 'Not authenticated. Please sign in.'}
            </p>
          </div>
          <div className="tf-card tf-card--plain">
            <h3 className="text-sm font-semibold mb-2 text-text-secondary">TaskForge</h3>
            <p className="text-xs text-text-muted">
              AI Agent OS for Solo Entrepreneurs. Open source under BSL-1.1.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
