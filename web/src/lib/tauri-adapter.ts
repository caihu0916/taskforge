// Copyright (c) 2024-2026 TaskForge Team
// SPDX-License-Identifier: BSL-1.1

/**
 * Tauri Desktop Adapter
 * 桌面版前端适配层：自动检测运行环境，切换API base URL
 *
 * - Web版：API前缀 /api/v1 (相对路径，走Nginx反代)
 * - 桌面版：API前缀 http://localhost:{port}/api/v1 (走sidecar后端)
 */

let _backendPort: number | null = null;
let _isDesktop = false;
let _initialized = false;

/**
 * 检测是否运行在Tauri桌面环境中
 */
export function isDesktopMode(): boolean {
    return _isDesktop;
}

/**
 * 获取当前后端端口号
 */
export function getPort(): number | null {
    return _backendPort;
}

/**
 * 获取API前缀路径
 * - Web版：'/api/v1'
 * - 桌面版：'http://localhost:{port}/api/v1'
 */
export function getApiPrefixUrl(): string {
    if (_isDesktop && _backendPort) {
        return `http://127.0.0.1:${_backendPort}/api/v1`;
    }
    return '/api/v1';
}

/**
 * 初始化桌面模式适配
 * 应在App入口调用一次，返回是否桌面模式
 */
export async function initDesktopAdapter(): Promise<boolean> {
    if (_initialized) return _isDesktop;
    _initialized = true;

    // 检测Tauri环境
    if (typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window) {
        _isDesktop = true;

        // 尝试获取后端端口
        try {
            const { invoke } = await import(/* @vite-ignore */ '@tauri-apps/api/core');
            _backendPort = await invoke<number>('get_backend_port');
        } catch {
            _backendPort = 8001;
        }

        // 监听后端就绪事件
        try {
            const { listen } = await import(/* @vite-ignore */ '@tauri-apps/api/event');
            await listen<number>('backend-ready', (event) => {
                _backendPort = event.payload;
                window.dispatchEvent(new CustomEvent('tf:backend-ready', { detail: { port: _backendPort } }));
            });

            await listen<string>('backend-error', (event) => {
                console.error(`[TaskForge Desktop] Backend error: ${event.payload}`);
                window.dispatchEvent(new CustomEvent('tf:backend-error', { detail: { error: event.payload } }));
            });

            await listen<string>('backend-start-failed', (event) => {
                console.error(`[TaskForge Desktop] Backend start failed: ${event.payload}`);
                window.dispatchEvent(new CustomEvent('tf:backend-error', { detail: { error: event.payload } }));
            });

            await listen<number>('backend-timeout', () => {
                console.error('[TaskForge Desktop] Backend startup timeout');
                window.dispatchEvent(new CustomEvent('tf:backend-error', { detail: { error: 'Backend startup timeout' } }));
            });
        } catch {
            // event listeners not available
        }

        // ── Deep Link 监听 ──
        // 官网注册后通过 taskforge://provision?token=xxx 唤起桌面应用
        try {
            const { onOpenUrl } = await import(/* @vite-ignore */ '@tauri-apps/plugin-deep-link');
            await onOpenUrl((urls: string[]) => {
                for (const url of urls) {
                    console.info('[TaskForge Desktop] Deep link received:', url);
                    window.dispatchEvent(new CustomEvent('tf:deep-link', { detail: { url } }));
                }
            });
        } catch {
            // deep-link plugin not available (web mode)
        }
    }

    return _isDesktop;
}

/**
 * 重启后端（桌面版）
 */
export async function restartBackend(): Promise<number | null> {
    if (!_isDesktop) return null;

    try {
        const { invoke } = await import(/* @vite-ignore */ '@tauri-apps/api/core');
        const port = await invoke<number>('restart_backend');
        _backendPort = port;
        return port;
    } catch {
        return null;
    }
}
