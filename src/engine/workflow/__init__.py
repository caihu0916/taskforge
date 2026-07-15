
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge 工作流模块 — PDCA引擎 + 工作流模板

PDCA (Plan-Do-Check-Act) 是核心业务引擎:
  - Plan: 掌柜/调研员制定计划
  - Do: 爆款制造机/成交猎手执行
  - Check: 数据分析师/合规官检查结果
  - Act: 掌柜决策调整，进入下一轮

结构:
  models.py   — 工作流/阶段/步骤数据模型
  engine.py   — PDCA引擎核心逻辑
  api.py      — API端点
"""

from __future__ import annotations
