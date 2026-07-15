// Copyright (c) 2024-2026 TaskForge Team
// SPDX-License-Identifier: BSL-1.1

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../../stores/auth'
import { api } from '../../lib/api'
import type { ApiResponse } from '../../lib/api-types'

interface LoginResponse {
  access_token: string
  token_type: string
}

export default function Auth() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const login = useAuthStore((s) => s.login)

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const resp = await api
        .post('auth/login', { json: { username, password } })
        .json<ApiResponse<LoginResponse>>()
      if (resp.success && resp.data) {
        login(resp.data)
        navigate('/dashboard')
      } else {
        setError(typeof resp.error === 'string' ? resp.error : 'Login failed')
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-bg-primary">
      <div className="tf-card tf-card--plain" style={{ width: 380 }}>
        <h1 className="text-2xl font-bold mb-6 text-text-primary">{t('authPage.title')}</h1>
        {error && (
          <div className="mb-4 p-3 rounded-apple-md text-sm" style={{ background: 'rgba(255,59,48,0.12)', color: 'var(--accent-red)' }}>
            {error}
          </div>
        )}
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="tf-input-wrapper">
            <label className="tf-input__label">{t('authPage.username')}</label>
            <input
              className="tf-input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
            />
          </div>
          <div className="tf-input-wrapper">
            <label className="tf-input__label">{t('authPage.password')}</label>
            <input
              className="tf-input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>
          <button
            className="tf-button btn-variant-primary btn-size-md"
            type="submit"
            disabled={loading}
          >
            {loading ? t('common.loading') : t('authPage.submit')}
          </button>
        </form>
      </div>
    </div>
  )
}
