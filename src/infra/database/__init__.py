
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge 数据库基础设施 (开源版最小集)

P0-06 遗漏修复 — 原 __init__.py 引用 ddl_builder/orm 模块未开源,
P0-33 BetaProgramManager 需经此包导入 base_manager/connection,
故精简为空 __init__ (直接从子模块导入)。
"""
