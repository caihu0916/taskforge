/**
 * ky 单例 — 统一 API 客户端，禁 raw fetch（G11/G12）
 *
 * P0-19: API_BASE 改为 env 驱动 — 支持本地/远程双模式
 *   - 不设 env → API_BASE = "/api/v1" (本地模式)
 *   - 设 VITE_API_BASE_URL=https://api.taskforge.cn/api/v1 → 远程模式
 *
 * Auth: 从 Zustand store (内存) 读取 token，不使用 localStorage
 */
import ky, { type BeforeRequestHook, type BeforeRetryHook } from "ky";
import { getAuthTokenFromStore, useAuthStore } from "../stores/auth";

// P0-19: env 驱动的 API_BASE — 本地/远程双模式
const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api/v1";

export interface ApiError {
  status: number;
  message: string;
}

/**
 * beforeRequest: 从 Zustand store 读取 token 注入 Authorization header
 */
const injectAuth: BeforeRequestHook = (request) => {
  const token = getAuthTokenFromStore();
  if (token) {
    request.headers.set("Authorization", `Bearer ${token}`);
  }
  return request;
};

/**
 * beforeRetry: 401 时清除 token 并跳转认证页
 */
const onAuthFailure: BeforeRetryHook = ({ error }) => {
  const err = error as unknown as { response?: { status: number } };
  if (err?.response?.status === 401) {
    useAuthStore.getState().clearTokens();
    if (typeof window !== "undefined" && window.location.pathname !== "/auth") {
      window.location.href = "/auth";
    }
    return ky.stop;
  }
};

export const api = ky.create({
  prefixUrl: API_BASE,
  hooks: {
    beforeRequest: [injectAuth],
    beforeRetry: [onAuthFailure],
  },
  retry: { limit: 2, methods: ["get"] },
});

/**
 * 获取当前 auth token (从 Zustand store)
 */
export function getAuthToken(): string | null {
  return getAuthTokenFromStore();
}

/**
 * 安全刷新 token — 通过 HttpOnly cookie 调用 /auth/refresh
 */
export async function safeRefresh(): Promise<boolean> {
  try {
    const res = await api.post("auth/refresh", { json: {} }).json<any>();
    if (res?.data?.access_token) {
      useAuthStore.getState().setTokens(res.data.access_token);
      return true;
    }
    return false;
  } catch {
    useAuthStore.getState().clearTokens();
    return false;
  }
}

/**
 * 检查当前用户是否为 admin
 */
export function isAdmin(): boolean {
  return useAuthStore.getState().isAdmin();
}

/**
 * SSE 流式请求 — 复用 auth token 注入 + env 驱动的 API_BASE
 */
export async function sseFetch(
  url: string,
  options: Omit<RequestInit, 'headers'> & { headers?: Record<string, string> },
): Promise<Response> {
  const prefixUrl = API_BASE.replace(/\/?$/, '/')
  const fullUrl = url.startsWith('/') ? url : `${prefixUrl}${url}`

  // 注入 auth — 与 ky beforeRequest hook 逻辑一致
  const headers: Record<string, string> = { ...options.headers }
  const token = getAuthTokenFromStore()
  if (token) headers['Authorization'] = `Bearer ${token}`

  return globalThis.fetch(fullUrl, { ...options, headers })
}
