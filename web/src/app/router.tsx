// Copyright (c) 2024-2026 TaskForge Team
// SPDX-License-Identifier: BSL-1.1

import { createBrowserRouter, Navigate } from 'react-router-dom'
import { lazy, Suspense } from 'react'
import type { ReactNode } from 'react'

// Skeleton spinner for Suspense fallback
function PageSpinner() {
  return (
    <div className="tf-page-spinner">
      <div className="tf-spinner">
        <svg className="tf-spinner__svg" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.25" />
          <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
        </svg>
      </div>
    </div>
  )
}

function withSuspense(el: ReactNode) {
  return <Suspense fallback={<PageSpinner />}>{el}</Suspense>
}

// Lazy-loaded pages — each page is an independent chunk
const Auth = lazy(() => import('../pages/Auth'))
const Dashboard = lazy(() => import('../pages/Dashboard'))

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Navigate to="/dashboard" replace />,
  },
  {
    path: '/auth',
    element: withSuspense(<Auth />),
  },
  {
    path: '/dashboard',
    element: withSuspense(<Dashboard />),
  },
  {
    path: '*',
    element: <Navigate to="/dashboard" replace />,
  },
])
