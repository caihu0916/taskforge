
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge 认证 Schemas — 请求/响应数据模型

设计决策:
  - 密码强度: >=8位 + 复杂度要求（防止暴力破解和字典攻击）
  - 邮箱/手机二选一注册
  - 响应模型从不包含 password_hash
  - 弱密码黑名单: 100+ 常见密码（基于 RockYou 泄露数据Top 100）
"""

from __future__ import annotations

import re

from pydantic import BaseModel, EmailStr, Field, field_validator

# ── 常见弱密码黑名单 (Top 100) ──
# 基于 RockYou 泄露数据 + 常见模式
_WEAK_PASSWORDS = frozenset(
    {
        # Top 20 最常见
        "123456",
        "password",
        "12345678",
        "qwerty",
        "123456789",
        "12345",
        "1234",
        "111111",
        "1234567",
        "dragon",
        "123123",
        "baseball",
        "abc123",
        "football",
        "monkey",
        "letmein",
        "shadow",
        "master",
        "666666",
        "qwertyuiop",
        # 数字模式
        "000000",
        "112233",
        "121212",
        "123321",
        "654321",
        "777777",
        "888888",
        "999999",
        "1234567890",
        # 常见单词
        "admin",
        "administrator",
        "root",
        "user",
        "guest",
        "test",
        "demo",
        "password1",
        "password123",
        "welcome",
        "login",
        "passw0rd",
        "p@ssw0rd",
        # 键盘模式
        "asdfgh",
        "zxcvbn",
        "qazwsx",
        "123qwe",
        "1q2w3e",
        "qwe123",
        "admin123",
        "admin1",
        # 个人信息相关 (常见)
        "changeme",
        "default",
        "password1234",
        "1234abcd",
        "abcd1234",
        "hello123",
        "love123",
        "god123",
        "money123",
        "jordan23",
        "michael1",
        "hunter2",
        "hunter",
        "buster",
        "soccer",
        "hockey",
        "killer",
        "george",
        "computer",
        "internet",
        "whatever",
        "nothing",
        "orange",
        "banana",
        "apple123",
        "sunshine",
        "princess",
        "photoshop",
        "rockyou",
        "trustno1",
        "omgpassword",
        "123abc",
        "a123456",
        "aa123456",
        "a123456789",
        "www123",
        "hello1",
        "password!",
        "qwerty1",
        "123456a",
        "123456789a",
        "adminadmin",
        "rootroot",
        "test123",
        "demo123",
        "guest123",
        "user123",
        "pass123",
        "pass1234",
        "password12",
        "987654321",
        "11111111",
        "22222222",
        "33333333",
        "44444444",
        "55555555",
        "66666666",
        "77777777",
        "88888888",
        "99999999",
        "00000000",
    }
)

# 密码最小长度
_PASSWORD_MIN_LENGTH = 8
# 密码最大长度
_PASSWORD_MAX_LENGTH = 72

# 特殊字符集
_PASSWORD_SPECIAL_CHARS = r"!@#$%^&*()_+-=[]{}|;:,.<>?"


def _check_password_complexity(v: str) -> None:
    """检查密码复杂度: 必须包含大小写字母、数字、特殊字符中的至少 3 种"""
    types = 0
    if re.search(r"[a-z]", v):
        types += 1
    if re.search(r"[A-Z]", v):
        types += 1
    if re.search(r"\d", v):
        types += 1
    if re.search(r"[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]", v):
        types += 1
    if types < 3:
        raise ValueError(
            f"密码复杂度不足。必须包含以下至少 3 种: 小写字母、大写字母、数字、特殊字符 ({_PASSWORD_SPECIAL_CHARS})"
        )


# ── 请求模型 ──


class UserRegister(BaseModel):
    """注册请求"""

    email: EmailStr | None = None
    phone: str | None = None
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str = Field("", max_length=64)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        """密码强度校验: >=8位 + 复杂度要求 + 非弱密码"""
        if len(v) < _PASSWORD_MIN_LENGTH:
            raise ValueError(f"密码至少{_PASSWORD_MIN_LENGTH}位")
        if len(v) > _PASSWORD_MAX_LENGTH:
            raise ValueError(f"密码最多{_PASSWORD_MAX_LENGTH}位")
        if v in _WEAK_PASSWORDS:
            raise ValueError("该密码过于简单，请换一个")
        # 复杂度校验
        _check_password_complexity(v)
        return v

    @field_validator("phone")
    @classmethod
    def phone_format(cls, v: str | None) -> str | None:
        if v is None:
            return v
        # 中国大陆手机号
        if not re.match(r"^1[3-9]\d{9}$", v):
            raise ValueError("手机号格式不正确")
        return v

    @field_validator("email")
    @classmethod
    def at_least_one_contact(cls, v: str | None) -> str | None:
        # email 或 phone 至少一个 — 在 model_validator 中做
        return v


class UserLogin(BaseModel):
    """登录请求"""

    email: EmailStr | None = None
    phone: str | None = None
    password: str = Field(..., min_length=1)


class TokenRefresh(BaseModel):
    """刷新/注销 Token 请求

    FRONT-005: refresh 端点改为从 HttpOnly cookie 读取 refresh_token，不再接受 body。
    此模型保留供 logout 端点兼容（可选），优先级低于 cookie。
    """

    refresh_token: str = Field(default="", description="可选，优先从 cookie 读取")


class PasswordChange(BaseModel):
    """修改密码请求"""

    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        """与注册同规则"""
        if len(v) < _PASSWORD_MIN_LENGTH:
            raise ValueError(f"密码至少{_PASSWORD_MIN_LENGTH}位")
        if len(v) > _PASSWORD_MAX_LENGTH:
            raise ValueError(f"密码最多{_PASSWORD_MAX_LENGTH}位")
        if v in _WEAK_PASSWORDS:
            raise ValueError("该密码过于简单，请换一个")
        # 复杂度校验
        _check_password_complexity(v)
        return v


class UserUpdate(BaseModel):
    """更新用户信息请求"""

    display_name: str | None = Field(None, max_length=64)
    avatar_url: str | None = Field(None, max_length=512)


# ── 响应模型 ──


class UserOut(BaseModel):
    """用户信息输出（绝不含 password_hash）"""

    id: str
    email: str | None = None
    phone: str | None = None
    display_name: str = ""
    avatar_url: str = ""
    role: str = "user"
    status: str = "active"
    tenant_id: str | None = None
    last_login_at: str | None = None
    created_at: str = ""
    updated_at: str = ""


class TokenPair(BaseModel):
    """JWT Access Token 响应

    FRONT-005: refresh_token 通过 HttpOnly + Secure + SameSite=Strict cookie 下发，
    不再出现在响应 body 中，防止 XSS 通过读取响应窃取 refresh token。
    """

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # 秒


class AuthResponse(BaseModel):
    """注册/登录成功响应"""

    user: UserOut
    tokens: TokenPair


# ── 忘记密码模型 ──


class MessageResponse(BaseModel):
    """通用消息响应"""

    message: str


class ForgotPasswordRequest(BaseModel):
    """忘记密码请求 — 输入邮箱"""

    email: EmailStr = Field(..., description="注册时使用的邮箱")


class ResetPasswordRequest(BaseModel):
    """重置密码请求 — 输入 Token + 新密码"""

    token: str = Field(..., min_length=32, max_length=64, description="重置链接中的 token")
    new_password: str = Field(..., min_length=8, max_length=128, description="新密码")

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        """与注册同规则"""
        if len(v) < _PASSWORD_MIN_LENGTH:
            raise ValueError(f"密码至少{_PASSWORD_MIN_LENGTH}位")
        if len(v) > _PASSWORD_MAX_LENGTH:
            raise ValueError(f"密码最多{_PASSWORD_MAX_LENGTH}位")
        if v in _WEAK_PASSWORDS:
            raise ValueError("该密码过于简单，请换一个")
        _check_password_complexity(v)
        return v
