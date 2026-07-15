import { create } from 'zustand'
import type { UserOut } from '../services/auth'

const REFRESH_KEY = 'tf_refresh_token'

/**
 * 集中式认证状态管理 - 替代 api.ts 中散落在模块变量的 token 管理
 *
 * 设计原则：
 *   1. Zustand store 为唯一真实数据源
 *   2. access token 仅保存在内存 (Zustand store)，不进任何持久化存储，防 XSS 窃取
 *   3. 页面刷新后通过 refresh cookie (HttpOnly) 调用 /auth/refresh 换取新 access token
 *   4. 状态变更触发组件重渲染（取代旧的事件分发）
 */

export interface AuthStore {
  // 状态
  token: string | null
  refreshToken: string | null
  user: UserOut | null

  // Actions
  setTokens: (access: string, refresh?: string) => void
  clearTokens: () => void
  setUser: (user: UserOut | null) => void
  login: (tokens: { access_token: string }, user?: UserOut) => void
  logout: () => void

  // 计算属性
  isAuthenticated: () => boolean
  getUserRole: () => string | null
  isAdmin: () => boolean
}

function readInitialToken(): string | null {
  return null
}

function readInitialRefresh(): string | null {
  return null
}

function decodeRole(token: string | null): string | null {
  if (!token) return null
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return null
    const payload = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')))
    return payload.role || null
  } catch {
    return null
  }
}

export const useAuthStore = create<AuthStore>((set, get) => ({
  token: readInitialToken(),
  refreshToken: readInitialRefresh(),
  user: null,

  setTokens: (access: string, _refresh?: string) => {
    set({ token: access, refreshToken: null })
  },

  clearTokens: () => {
    try {
      sessionStorage.removeItem(REFRESH_KEY)
    } catch {
      // ignore
    }
    set({ token: null, refreshToken: null, user: null })
  },

  setUser: (user: UserOut | null) => set({ user }),

  login: (tokens, user) => {
    get().setTokens(tokens.access_token)
    if (user) set({ user })
  },

  logout: () => {
    get().clearTokens()
  },

  isAuthenticated: () => !!get().token,

  getUserRole: () => decodeRole(get().token),

  isAdmin: () => decodeRole(get().token) === 'admin',
}))

/**
 * 向后兼容：api.ts 和 auth.ts 需要继续访问 token 变量
 */
export function getAuthTokenFromStore(): string | null {
  return useAuthStore.getState().token
}

export function setAuthTokenFromStore(token: string | null): void {
  const state = useAuthStore.getState()
  if (token) {
    state.setTokens(token, state.refreshToken || '')
  } else {
    state.clearTokens()
  }
}
