// P0-21/P0-22/P0-23: TaskForge 开源版 Tauri 主程序 — 双模式配置
//
// 数据链路: env TF_DESKTOP_MODE → BackendMode → setup() 分支决策
//
// ponytail: 主项目 lib.rs 963行含完整 sidecar/fs/sysinfo/notification,
// 开源版仅保留双模式核心 (~120行), 不启动 Python sidecar,
// Remote 模式前端直接连 SaaS API, Local 模式由用户自行启动 python app.py.

use serde::Serialize;
use std::env;

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;

/// P0-21: 后端模式枚举
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BackendMode {
    /// 本地模式 — 用户自行启动 python app.py, Tauri 仅作前端壳
    Local,
    /// 远程模式 — 前端直连 SaaS API, 无需本地 Python
    Remote,
}

/// P0-21: 从 TF_DESKTOP_MODE 环境变量读取后端模式
///
/// - 未设置 / 空值 / 未知值 → Local (安全降级)
/// - "remote" / "REMOTE" / "Remote" → Remote
/// - "local" / "LOCAL" / "Local" → Local
pub fn read_backend_mode() -> BackendMode {
    match env::var("TF_DESKTOP_MODE").unwrap_or_default().to_lowercase().as_str() {
        "remote" => BackendMode::Remote,
        _ => BackendMode::Local,
    }
}

/// P0-22: 判断是否应启动 sidecar (Python 后端)
///
/// Local 模式 → 启动 (但开源版由用户手动启动, Tauri 不自动拉起)
/// Remote 模式 → 不启动
pub fn should_start_sidecar(mode: BackendMode) -> bool {
    matches!(mode, BackendMode::Local)
}

/// P0-23: 根据模式生成 CSP connect-src
///
/// Local: 允许 localhost/127.0.0.1 (本地 Python 后端)
/// Remote: 允许 *.taskforge.cn (SaaS API)
pub fn build_csp(mode: BackendMode) -> String {
    let connect_src = match mode {
        BackendMode::Local => {
            "connect-src 'self' http://localhost:* http://127.0.0.1:* ws://localhost:* ws://127.0.0.1:* http://ipc.localhost"
        }
        BackendMode::Remote => {
            "connect-src 'self' https://*.taskforge.cn http://ipc.localhost"
        }
    };
    format!(
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' data: blob: https:; {}",
        connect_src
    )
}

/// P0-22: 获取前端应使用的 API base URL
///
/// Local: /api/v1 (相对路径, 同源)
/// Remote: https://api.taskforge.cn/api/v1 (SaaS)
pub fn get_api_base_url(mode: BackendMode) -> String {
    match mode {
        BackendMode::Local => "/api/v1".to_string(),
        BackendMode::Remote => "https://api.taskforge.cn/api/v1".to_string(),
    }
}

/// P0-22: 获取后端模式 (Tauri 命令, 供前端查询)
#[tauri::command]
fn get_backend_mode() -> String {
    match read_backend_mode() {
        BackendMode::Local => "local".to_string(),
        BackendMode::Remote => "remote".to_string(),
    }
}

/// P0-22: 获取 API base URL (Tauri 命令, 供前端查询)
#[tauri::command]
fn get_api_base_url_command() -> String {
    get_api_base_url(read_backend_mode())
}

/// 应用配置信息 (序列化给前端)
#[derive(Serialize)]
pub struct AppConfig {
    pub mode: String,
    pub api_base_url: String,
    pub csp: String,
}

/// P0-22: 获取完整应用配置 (Tauri 命令)
#[tauri::command]
fn get_app_config() -> AppConfig {
    let mode = read_backend_mode();
    AppConfig {
        mode: match mode {
            BackendMode::Local => "local".to_string(),
            BackendMode::Remote => "remote".to_string(),
        },
        api_base_url: get_api_base_url(mode),
        csp: build_csp(mode),
    }
}

pub fn run() {
    env_logger::init();
    let mode = read_backend_mode();
    log::info!("TaskForge Desktop (Open Source) starting in {:?} mode", mode);

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            get_backend_mode,
            get_api_base_url_command,
            get_app_config
        ])
        .setup(move |_app| {
            log::info!("Backend mode: {:?}, sidecar will {} (开源版由用户手动启动)",
                mode,
                if should_start_sidecar(mode) { "be needed" } else { "not be needed" });
            Ok(())
        })
        .build(tauri::generate_context!())
        .unwrap_or_else(|e| {
            log::error!("startup_failed stage=tauri_build error=\"{}\"", e);
            panic!("TaskForge startup failed: {}", e)
        })
        .run(|_app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                log::info!("TaskForge Desktop exiting");
            }
        });
}
