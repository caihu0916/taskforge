// P0-21/P0-22/P0-23 tests — 双模式配置读取 + 远程模式分支 + CSP 动态化

use super::*;

// ---------- P0-21: BackendMode 读取 ----------

#[test]
fn test_backend_mode_default_is_local() {
    // 未设 TF_DESKTOP_MODE → 默认 Local
    std::env::remove_var("TF_DESKTOP_MODE");
    assert_eq!(read_backend_mode(), BackendMode::Local);
}

#[test]
fn test_backend_mode_remote_when_env_set() {
    // TF_DESKTOP_MODE=remote → Remote
    std::env::set_var("TF_DESKTOP_MODE", "remote");
    assert_eq!(read_backend_mode(), BackendMode::Remote);
    std::env::remove_var("TF_DESKTOP_MODE");
}

#[test]
fn test_backend_mode_local_when_env_set() {
    // TF_DESKTOP_MODE=local → Local
    std::env::set_var("TF_DESKTOP_MODE", "local");
    assert_eq!(read_backend_mode(), BackendMode::Local);
    std::env::remove_var("TF_DESKTOP_MODE");
}

#[test]
fn test_backend_mode_case_insensitive() {
    // REMOTE/Remote/remote 都识别
    std::env::set_var("TF_DESKTOP_MODE", "REMOTE");
    assert_eq!(read_backend_mode(), BackendMode::Remote);
    std::env::set_var("TF_DESKTOP_MODE", "Remote");
    assert_eq!(read_backend_mode(), BackendMode::Remote);
    std::env::remove_var("TF_DESKTOP_MODE");
}

#[test]
fn test_backend_mode_unknown_falls_back_to_local() {
    // 未知值 → Local (安全降级)
    std::env::set_var("TF_DESKTOP_MODE", "invalid");
    assert_eq!(read_backend_mode(), BackendMode::Local);
    std::env::remove_var("TF_DESKTOP_MODE");
}

// ---------- P0-22: should_start_sidecar ----------

#[test]
fn test_should_start_sidecar_local_mode() {
    // Local 模式 → 启动 sidecar
    assert!(should_start_sidecar(BackendMode::Local));
}

#[test]
fn test_should_not_start_sidecar_remote_mode() {
    // Remote 模式 → 不启动 sidecar (前端连远程 API)
    assert!(!should_start_sidecar(BackendMode::Remote));
}

// ---------- P0-23: CSP 动态化 ----------

#[test]
fn test_csp_local_mode_allows_localhost() {
    // Local 模式 CSP 允许 localhost
    let csp = build_csp(BackendMode::Local);
    assert!(csp.contains("localhost"));
    assert!(csp.contains("127.0.0.1"));
}

#[test]
fn test_csp_remote_mode_allows_taskforge_cn() {
    // Remote 模式 CSP 允许 *.taskforge.cn
    let csp = build_csp(BackendMode::Remote);
    assert!(csp.contains("*.taskforge.cn"));
}

#[test]
fn test_csp_both_modes_allow_self() {
    // 两种模式都允许 'self'
    assert!(build_csp(BackendMode::Local).contains("'self'"));
    assert!(build_csp(BackendMode::Remote).contains("'self'"));
}

// ---------- P0-22: get_api_base_url ----------

#[test]
fn test_get_api_base_url_local_mode() {
    // Local 模式 → 本地 API
    let url = get_api_base_url(BackendMode::Local);
    assert!(url.contains("localhost") || url.contains("/api/v1"));
}

#[test]
fn test_get_api_base_url_remote_mode() {
    // Remote 模式 → SaaS API
    let url = get_api_base_url(BackendMode::Remote);
    assert!(url.contains("taskforge.cn"));
}
