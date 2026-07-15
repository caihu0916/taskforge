
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""文件上传大小限制配置"""

from __future__ import annotations

from pydantic import BaseModel, Field


class UploadConfig(BaseModel):
    """文件上传大小限制配置"""

    max_file_size_mb: int = Field(default=50, ge=1, le=500, description="通用上传大小限制(MB)")
    max_audio_size_mb: int = Field(default=50, ge=1, le=200, description="音频上传大小限制(MB)")
    max_video_size_mb: int = Field(default=200, ge=1, le=1000, description="视频上传大小限制(MB)")
    max_image_size_mb: int = Field(default=20, ge=1, le=100, description="图片上传大小限制(MB)")
    max_import_size_mb: int = Field(default=100, ge=1, le=500, description="数据导入文件大小限制(MB)")
