
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Settings 主类 — TaskForge 唯一配置入口 + get_settings 单例 + load_hermes_config

优先级: 环境变量 > .env 文件 > 默认值

环境变量命名:
  顶层:  TF_APP_NAME, TF_VERSION
  嵌套:  TF_DB__URL, TF_DB__POOL_SIZE, TF_LLM__PROVIDER ...
  注意:  前缀 TF_ 后直接接大写段落名(如DB)，再用 __ 分隔子字段
"""

from __future__ import annotations

import threading

import structlog
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from src.infra.config.remote import RemoteConfig

from src.infra.config._constants import _is_weak_encryption_key
from src.infra.config.auth import AuthConfig
from src.infra.config.billing import BillingConfig
from src.infra.config.bridge import BridgeConfig
from src.infra.config.browser import BrowserConfig
from src.infra.config.butler import ButlerConfig
from src.infra.config.channel import ChannelConfig
from src.infra.config.code_execution import CodeExecutionConfig
from src.infra.config.contract import ContractConfig
from src.infra.config.credential_pool import CredentialPoolConfig
from src.infra.config.database import DatabaseConfig
from src.infra.config.delegate import DelegateConfig
from src.infra.config.desktop import DesktopConfig
from src.infra.config.gateway import GatewayConfig
from src.infra.config.llm import LLMConfig
from src.infra.config.memory import MemoryConfig
from src.infra.config.payment import PaymentConfig
from src.infra.config.redis import RedisConfig
from src.infra.config.security import SecurityConfig
from src.infra.config.server import ImageGenConfig, ObsidianConfig, ServerConfig
from src.infra.config.social import SocialConfig
from src.infra.config.task import TaskConfig
from src.infra.config.terminal import TerminalConfig
from src.infra.config.upload import UploadConfig
from src.infra.config.watermark import WatermarkConfig
from src.infra.config.ws import WSConfig

_logger = structlog.get_logger(__name__)

# 密钥脱敏路径表 (点分路径，叶子字段做简单脱敏)
_SECRET_MASK_PATHS = (
    # Auth 配置
    "auth.api_key",
    "auth.jwt_secret",
    # LLM 配置
    "llm.api_key",
    "llm.freellmapi_api_key",
    "llm.agnes.api_key",
    # Server 配置 (关键：encryption_key 必须脱敏)
    "server.encryption_key",
    "server.baidu_ocr_api_key",
    "server.baidu_ocr_secret_key",
    # ImageGen 配置
    "image_gen.api_key",
    # 支付密钥脱敏
    "payment.wechat_api_key",
    "payment.alipay_private_key",
    "payment.alipay_public_key",
    "payment.stripe_api_key",
    "payment.stripe_webhook_secret",
    "payment.stripe_publishable_key",
    # 通道密钥脱敏
    "channels.feishu_app_secret",
    "channels.feishu_verification_token",
    "channels.feishu_encrypt_key",
    "channels.wechat_work_secret",
    "channels.wechat_work_token",
    "channels.wechat_work_encoding_aes_key",
    "channels.dingtalk_app_key",
    "channels.dingtalk_app_secret",
    "channels.dingtalk_token",
    # 社交媒体密钥脱敏
    "social.douyin_client_secret",
    "social.douyin_access_token",
    "social.bilibili_app_secret",
    "social.bilibili_access_token",
    "social.weibo_app_secret",
    "social.weibo_access_token",
    "social.wechat_app_secret",
    # Redis 密码脱敏
    "redis.password",
    "redis.sentinel_password",
    # 桥接凭据脱敏
    "bridge.tools_bridge_token",
    "bridge.vision_api_key",
    # 合同webhook密钥脱敏 + 合同签名服务商密钥脱敏
    "contract.webhook_secret",
    "contract.docusign.private_key",
    "contract.docusign.app_secret",
    "contract.docusign.integration_key",
    "contract.docusign.access_token",
    "contract.adobe_sign.private_key",
    "contract.adobe_sign.app_secret",
    "contract.adobe_sign.integration_key",
    "contract.adobe_sign.access_token",
    "contract.fadada.private_key",
    "contract.fadada.app_secret",
    "contract.fadada.integration_key",
    "contract.fadada.access_token",
    "contract.esign.private_key",
    "contract.esign.app_secret",
    "contract.esign.integration_key",
    "contract.esign.access_token",
    # Butler 邮件密钥脱敏
    "butler.email.smtp.password",
    "butler.email.mailgun.api_key",
)


class HardLimitsConfig(BaseModel):
    """AGENT-016: hard_limits.yaml 完整性校验配置

    环境变量: TF_HARD_LIMITS__EXPECTED_SHA256
    生产环境启动时校验 hard_limits.yaml 的 SHA256 是否与期望值匹配，
    不匹配则拒绝启动（防篡改）。
    """

    expected_sha256: str = Field(
        default="",
        description="期望的 hard_limits.yaml SHA256（64 字符 hex），生产环境必须配置 (TF_HARD_LIMITS__EXPECTED_SHA256)",
    )


class Settings(BaseSettings):
    """TaskForge 唯一配置入口

    优先级: 环境变量 > .env > 默认值
    环境变量用 TF_ 前缀，嵌套用 __ 分隔:
      TF_APP_NAME=TaskForge
      TF_DB__URL=sqlite:///data/tf.db
      TF_LLM__PROVIDER=openai
      TF_AUTH__CORS_ORIGINS=http://a.com,http://b.com
    """

    app_name: str = Field(default="TaskForge")
    version: str = Field(default="0.1.0")
    scenario: str = Field(default="content_ecommerce", description="行业场景包 ID (切换行业改此行)")

    db: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    payment: PaymentConfig = Field(default_factory=PaymentConfig)
    channels: ChannelConfig = Field(default_factory=ChannelConfig)
    obsidian: ObsidianConfig = Field(default_factory=ObsidianConfig)
    image_gen: ImageGenConfig = Field(default_factory=ImageGenConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    terminal: TerminalConfig = Field(default_factory=TerminalConfig)
    delegate: DelegateConfig = Field(default_factory=DelegateConfig)
    bridge: BridgeConfig = Field(default_factory=BridgeConfig)
    credential_pool: CredentialPoolConfig = Field(default_factory=CredentialPoolConfig)
    code_execution: CodeExecutionConfig = Field(default_factory=CodeExecutionConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    desktop: DesktopConfig = Field(default_factory=DesktopConfig)
    billing: BillingConfig = Field(default_factory=BillingConfig)
    contract: ContractConfig = Field(default_factory=ContractConfig)
    upload: UploadConfig = Field(default_factory=UploadConfig)
    watermark: WatermarkConfig = Field(default_factory=WatermarkConfig)
    social: SocialConfig = Field(default_factory=SocialConfig)
    task: TaskConfig = Field(default_factory=TaskConfig)
    ws: WSConfig = Field(default_factory=WSConfig)
    butler: ButlerConfig = Field(default_factory=ButlerConfig)
    remote: RemoteConfig = Field(default_factory=RemoteConfig)
    hard_limits: HardLimitsConfig = Field(default_factory=HardLimitsConfig)

    model_config = SettingsConfigDict(
        env_prefix="TF_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    def is_production(self) -> bool:
        return self.server.environment == "production"

    def mask_secrets(self) -> dict:
        """导出配置为dict，自动脱敏密钥字段"""
        data = self.model_dump()
        for path in _SECRET_MASK_PATHS:
            self._mask_path(data, path)
        self._mask_browser_cdp_url(data)
        self._mask_credential_pool(data)
        return data

    @staticmethod
    def _mask_value(value: str) -> str:
        """安全脱敏（处理空值、短密钥）"""
        if not value:
            return value
        return value[:4] + "***" if len(value) >= 4 else "***"

    def _mask_path(self, data: dict, path: str) -> None:
        """按点分路径脱敏叶子字段"""
        parts = path.split(".")
        node = data
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                return
            node = child
        key = parts[-1]
        if node.get(key):
            node[key] = self._mask_value(node[key])

    def _mask_browser_cdp_url(self, data: dict) -> None:
        """浏览器 cdp_url 脱敏 (可能含认证信息 user:pass@)"""
        br = data.get("browser", {})
        cdp = br.get("cdp_url", "")
        if not cdp or "@" not in cdp:
            return
        at_idx = cdp.rindex("@")
        scheme_end = cdp.index("://") + 3 if "://" in cdp else 0
        br["cdp_url"] = cdp[:scheme_end] + "***" + cdp[at_idx:]

    def _mask_credential_pool(self, data: dict) -> None:
        """凭证池自定义Provider密钥脱敏"""
        cp = data.get("credential_pool", {})
        if cp.get("custom_providers"):
            # custom_providers 可能是复杂结构，简单处理为字符串脱敏
            cp["custom_providers"] = self._mask_value(str(cp["custom_providers"]))

    def set_scenario(self, scenario_id: str) -> None:
        """安全切换场景 — 替代直接修改 settings.scenario 的唯一途径"""
        self.scenario = scenario_id

    def validate(self) -> list[str]:
        """集中配置校验，返回错误列表（空列表=全部通过）

        校验项目:
        - 生产环境: JWT密钥强度、SQLite警告、加密密钥
        - LLM配置: provider与api_key一致性
        - Redis: 生产环境建议启用
        """
        errors: list[str] = []
        self._warn_dev_encryption_key()
        self._validate_production_settings(errors)
        self._validate_llm_settings(errors)
        self._validate_redis_settings(errors)
        self._validate_channel_settings(errors)
        self._validate_cors_settings(errors)
        return errors

    def _warn_dev_encryption_key(self) -> None:
        """开发环境 encryption_key 警告（仅日志，不产生 errors）"""
        if self.is_production():
            return
        if not self.server.encryption_key:
            _logger.warning(
                "encryption_key_not_set",
                hint="开发环境未设置 encryption_key，重启后已加密数据将无法解密。"
                "建议设置 TF_SERVER__ENCRYPTION_KEY (Fernet 对称密钥，格式: 长度32字节 base64)",
            )
        elif _is_weak_encryption_key(self.server.encryption_key):
            _logger.warning("encryption_key_weak", hint="encryption_key 使用了已知弱密钥，安全性不足。建议更换新密钥。")

    def _validate_production_settings(self, errors: list[str]) -> None:
        """生产环境强校验: environment/JWT/SQLite/encryption_key/plaintext_fallback/Sentry"""
        if not self.is_production():
            return

        # 检测是否显式设置 environment（防止默认值误判）
        import os

        env_from_env = os.environ.get("TF_SERVER__ENVIRONMENT", "")
        if not env_from_env:
            errors.append(
                "PRODUCTION: TF_SERVER__ENVIRONMENT 未显式设置！"
                "当前值可能为默认值误判，生产环境必须显式设置 TF_SERVER__ENVIRONMENT=production"
            )

        # JWT secret
        try:
            self.auth.validate_jwt_secret_for_production()
        except RuntimeError as e:
            errors.append(f"AUTH: {e}")

        # SQLite 在生产环境 — 硬阻断，不支持高并发写入
        if self.db.is_sqlite:
            errors.append(
                "PRODUCTION: 检测到 SQLite 数据库！SQLite 不支持多 Worker 并发写入，"
                "生产环境必须使用 PostgreSQL。设置 TF_DB__URL=postgresql+asyncpg://user:pass@host:5432/taskforge"
            )

        # encryption_key
        if not self.server.encryption_key:
            errors.append("PRODUCTION: server.encryption_key 未配置，API Key 将明文存储")
        elif _is_weak_encryption_key(self.server.encryption_key):
            errors.append("PRODUCTION: server.encryption_key 是已知泄露的弱密钥，请立即轮换！")

        # SP-1: 生产环境禁止明文回退 — 不再允许 Base64 明文存储 API Key
        if self.server.allow_plaintext_fallback:
            errors.append(
                "PRODUCTION: server.allow_plaintext_fallback=True 禁止在生产环境使用，"
                "请设置 TF_SERVER__ENCRYPTION_KEY (Fernet 密钥)"
            )

        # Sentry
        if not self.server.sentry_dsn:
            errors.append("PRODUCTION: server.sentry_dsn 未配置，建议启用错误监控")

    def _validate_llm_settings(self, errors: list[str]) -> None:
        """LLM 配置一致性 + 生产 API Key 安全校验"""
        # ── LLM 配置一致性 ──
        if self.llm.provider and not self.llm.api_key:
            errors.append(f"LLM: provider={self.llm.provider} 已配置，但 api_key 为空")

        # ── LLM API Key 生产安全校验 ──
        if not self.is_production():
            return

        # 主 Provider trial key 检测
        if self.llm.api_key and self.llm.is_trial_key():
            errors.append(
                f"PRODUCTION: LLM API Key 似乎是试用/演示 Key (pattern: trial/demo/sample)。"
                f"生产环境必须使用正式的 API Key，请到 {self.llm.provider} 官网申请正式版"
            )
        # Agnes trial key 检测
        if self.llm.agnes.enabled and self.llm.agnes.is_trial_key():
            errors.append(
                "PRODUCTION: Agnes AI 使用试用 Key (sk-agnes-trial)！"
                "试用 Key 仅用于开发/测试，生产环境必须注册正式账号: https://platform.agnes-ai.com/"
            )
        # 如果 Agnes 启用但未配置正式 key（仅试用）
        if self.llm.agnes.enabled and not self.llm.agnes.api_key:
            _logger.warning("agnes_trial_key_in_production", hint="Agnes AI 试用 Key 已启用，生产环境建议注册正式 Key")

    def _validate_redis_settings(self, errors: list[str]) -> None:
        """Redis 生产环境自动启用 + 安全强校验"""
        # ── Redis 生产环境自动启用 ──
        if self.is_production() and not self.redis.enabled:
            self.redis.enabled = True
            errors.append("PRODUCTION: Redis 已自动启用（生产环境必需，限流/会话依赖 Redis）")

        # ── Redis 生产安全强校验 ──
        if not self.is_production() or not self.redis.enabled:
            return

        if not self.redis.password and "localhost" in self.redis.url:
            errors.append(
                "PRODUCTION: Redis 密码未设置！生产环境必须配置强密码。"
                "设置 TF_REDIS__PASSWORD=your_strong_password 或在 URL 中包含 :password@"
            )
        if not self.redis.is_ssl_mode and not self.redis.is_sentinel_mode:
            errors.append("PRODUCTION: Redis 未启用 SSL！生产环境必须使用 rediss:// 或设置 TF_REDIS__SSL=true")
        # Sentinel 高可用建议（不是硬阻断，因为单节点 Redis 也能运行）
        if not self.redis.is_sentinel_mode:
            _logger.warning(
                "redis_single_node_production",
                hint="生产环境建议配置 Redis Sentinel 实现高可用，设置 TF_REDIS__SENTINEL_HOSTS",
            )

    def _validate_channel_settings(self, errors: list[str]) -> None:
        """通道配置互斥校验"""
        ch = self.channels
        if ch.is_feishu_configured() and not ch.feishu_app_id:
            errors.append("CHANNEL: 飞书已配置但 app_id 为空")

    def _validate_cors_settings(self, errors: list[str]) -> None:
        """CORS 生产安全校验"""
        if not self.is_production():
            return
        cors_errors = self.auth.validate_cors_for_production()
        errors.extend(cors_errors)

    def validate_strict(self) -> None:
        """严格配置校验 — 生产环境中关键错误直接抛出 RuntimeError 阻止启动

        关键错误包括:
        - 生产环境使用 SQLite
        - JWT 密钥强度不足
        - 加密密钥未配置或使用弱密钥
        - 允许明文回退

        Returns:
            None — 通过验证返回 None，失败直接抛异常
        """
        errors = self.validate()

        if not errors:
            return

        # 分类错误: 关键错误(应阻止启动) vs 警告(可继续)
        critical_errors = []
        warnings = []

        for err in errors:
            # 关键错误: 生产环境配置问题、认证问题
            if any(
                keyword in err
                for keyword in ("PRODUCTION:", "AUTH:", "SQLite", "encryption_key", "allow_plaintext_fallback", "JWT")
            ):
                critical_errors.append(err)
            else:
                warnings.append(err)

        # 记录警告
        for warn in warnings:
            _logger.warning("config_validation_warning", message=warn)

        # 生产环境中关键错误阻止启动
        if critical_errors:
            error_msg = "\n".join([f"  - {e}" for e in critical_errors])
            raise RuntimeError(
                f"配置验证失败，无法启动应用:\n{error_msg}\n\n"
                "请修复以上配置问题后重试。\n"
                "如需在开发环境跳过验证，请设置 TF_SERVER__ENVIRONMENT=development"
            )


# ── 全局单例 ──
_settings: Settings | None = None
_settings_lock = threading.RLock()
_settings_loading = False


def get_settings() -> Settings:
    """获取全局配置单例（延迟初始化），自动触发集中校验

    注意: 使用 RLock + _settings_loading 标志防止递归死锁。
    Settings 构造期间 pydantic validator 可能触发日志，
    而 structlog 处理器 _add_app_info 会回调 get_settings()，
    导致 Lock 重入死锁。
    """
    global _settings, _settings_loading
    if _settings is None:
        with _settings_lock:
            if _settings is None:
                if _settings_loading:
                    # 递归调用（Settings 构造中）— 抛异常让调用方降级
                    raise RuntimeError("Settings is being initialized")
                _settings_loading = True
                try:
                    _settings = Settings()
                    # 集中配置校验
                    errors = _settings.validate()
                    import structlog

                    log = structlog.get_logger(__name__)
                    for err in errors:
                        if "AUTH:" in err or "PRODUCTION:" in err:
                            log.warning("config_validation", message=err)
                        else:
                            log.info("config_validation", message=err)

                    # 生产环境严格校验 — 关键错误阻止启动
                    if _settings.is_production():
                        try:
                            _settings.validate_strict()
                        except RuntimeError as e:
                            log.error("config_validation_failed", error=str(e))
                            raise
                finally:
                    _settings_loading = False
    return _settings


def reset_settings() -> None:
    """重置配置单例（仅用于测试）"""
    global _settings, _settings_loading
    with _settings_lock:
        _settings = None
        _settings_loading = False


# D6-2: Hermes 兼容配置入口
def load_hermes_config(path: str = "hermes_config.yaml") -> dict | None:
    """加载 Hermes 兼容配置文件

    支持的字段:
      model.default → TF_LLM__MODEL
      provider      → TF_LLM__PROVIDER
      max_iterations → TF_LLM__MAX_TURNS (默认 50)
      compression   → 上下文压缩开关
      soul          → 系统提示覆盖
      terminal      → TF_TERMINAL__SHELL

    Returns:
        解析后的配置字典, 文件不存在返回 None
    """
    import os as _os

    try:
        import yaml as _yaml
    except ImportError:
        try:
            import json as _yaml_lib

            _yaml = _yaml_lib
        except ImportError:
            return None

    if not _os.path.exists(path):
        return None

    try:
        with open(path, encoding="utf-8") as f:
            raw = _yaml.safe_load(f) if path.endswith((".yaml", ".yml")) else _yaml.load(f)
    except Exception:
        return None

    if not isinstance(raw, dict):
        return None

    result: dict = {}
    if "model" in raw and isinstance(raw["model"], dict):
        result["model"] = raw["model"].get("default", "")
    if "provider" in raw:
        result["provider"] = raw["provider"]
    if "max_iterations" in raw:
        result["max_iterations"] = int(raw["max_iterations"])
    if "compression" in raw:
        result["compression"] = bool(raw["compression"])
    if "soul" in raw:
        result["soul"] = str(raw["soul"])
    if "terminal" in raw:
        result["terminal"] = str(raw["terminal"])
    return result
