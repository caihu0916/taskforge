// Copyright (c) 2024-2026 TaskForge Team
// SPDX-License-Identifier: BSL-1.1

export const listen = () => Promise.reject(new Error('Tauri not available in web mode'))
export const emit = () => Promise.reject(new Error('Tauri not available in web mode'))
