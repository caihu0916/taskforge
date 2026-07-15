// Copyright (c) 2024-2026 TaskForge Team
// SPDX-License-Identifier: BSL-1.1

/**
 * 统一响应类型 - 所有 services 的 API 调用应使用此类型
 *
 * 设计目标：
 *   1. 前后端约定统一信封格式：{ success: boolean; data: T; error?: string | ApiError }
 *   2. 解包时自动抛出错误，简化调用端代码
 *   3. TypeScript 泛型确保类型安全
 *
 * F3-1: error 字段兼容后端两种格式：
 *   - 后端异常处理器返回 string: { "success": false, "error": "错误信息" }
 *   - 前端 Chat/storage.ts 构造对象: { "success": false, "error": { code, message } }
 */

export interface ApiError {
  code: string
  message: string
  details?: any
}

/** 标准后端响应信封 — error 兼容 string 和 ApiError */
export interface ApiResponse<T> {
  success: boolean
  data: T
  error?: string | ApiError
  /** FIX-C6: 结构化错误码 (如 "DB-0006"), 成功时为 null */
  code?: string | null
  /** FIX-C6: 请求追踪 ID, 成功时为 null */
  trace_id?: string | null
  /** FIX-C6: 结构化错误详情, 成功时为 null */
  details?: Record<string, unknown> | null
}

/** 后端返回的分页列表格式 — 与后端 schemas.common.PaginatedResponse 对齐 */
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

/**
 * 从 unknown 类型的 catch 变量中安全提取错误消息
 * 用于 catch(e: unknown) 替代 catch(e: any)
 *
 * usage: catch (e: unknown) { toast('error', getErrorMessage(e)) }
 */
export function getErrorMessage(e: unknown, fallback = '请求失败'): string {
  if (e instanceof Error) return e.message
  if (typeof e === 'string') return e
  if (e && typeof e === 'object' && 'message' in e) return String((e as { message: unknown }).message) || fallback
  return fallback
}

/**
 * 检查 unknown 类型的 catch 变量是否为 AbortError
 * 用于 catch(e: unknown) { if (!isAbortError(e)) ... }
 */
export function isAbortError(e: unknown): boolean {
  return e instanceof DOMException && e.name === 'AbortError'
    || (e instanceof Error && e.name === 'AbortError')
}

/**
 * 后端可能返回 { success, data } 或 直接返回 T - 此类型兼容两者 */
export type MaybeEnveloped<T> = T | ApiResponse<T>

/**
 * 解包响应，将错误转换为异常抛出
 * 使用方式：
 *   const user = unwrap(await api.get('auth/me').json<ApiResponse<UserOut>>())
 */
export function unwrap<T>(resp: ApiResponse<T> | T): T {
  if (resp && typeof resp === 'object' && 'success' in (resp as Record<string, unknown>)) {
    const enveloped = resp as ApiResponse<T>
    if (!enveloped.success) {
      // F3-1: error 可能是 string（后端异常处理器）或 ApiError 对象（前端构造）
      const errObj = enveloped.error
      const msg = typeof errObj === 'string' ? errObj : errObj?.message || '请求失败'
      const err = new Error(msg)
      ;(err as unknown as Record<string, unknown>).code = typeof errObj === 'string' ? 'UNKNOWN' : errObj?.code || 'UNKNOWN'
      throw err
    }
    return enveloped.data
  }
  return resp as T
}

/**
 * 安全调用 API - 自动 try-catch 并返回统一结果
 * 使用方式：
 *   const { ok, data, error } = await safeApiCall(() => api.get('...').json<ApiResponse<T>>())
 */
export async function safeApiCall<T>(fn: () => Promise<T>): Promise<{
  ok: boolean
  data: T | null
  error: string | null
}> {
  try {
    const data = await fn()
    return { ok: true, data, error: null }
  } catch (e: unknown) {
    return {
      ok: false,
      data: null,
      error: getErrorMessage(e),
    }
  }
}
