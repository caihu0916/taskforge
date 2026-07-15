// Copyright (c) 2024-2026 TaskForge Team
// SPDX-License-Identifier: BSL-1.1

export const invoke = () => Promise.reject(new Error('Tauri not available in web mode'))
export const convertFileSrc = (s: string) => s
