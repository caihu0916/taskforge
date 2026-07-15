
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge 开源版入口 — 开发模式快速启动

启动方式:
  python app.py              # 开发模式 (热重载)
"""

import uvicorn

from config import get_settings


def main():
    settings = get_settings()
    uvicorn.run(
        "src.infra.startup.app_factory:create_app",
        factory=True,
        host=settings.server.host,
        port=settings.server.port,
        reload=settings.server.reload,
        log_level=settings.server.log_level.lower(),
    )


if __name__ == "__main__":
    main()
