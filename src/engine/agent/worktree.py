
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""WorktreeManager — git worktree 空间隔离 (对标 v2.1.168 EnterWorktree/ExitWorktree)

特性:
  - create(name) → git worktree add + branch, 返回 (path, name)
  - cleanup(action) → git worktree remove (remove) 或保留 (keep)
  - 名称校验: 字母/数字/点/下划线/减号, 最长64字符
  - 自动清理: 子Agent完成后清理 worktree
"""

from __future__ import annotations

import subprocess
import uuid as _uuid
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

_NAME_RE = r"^[a-zA-Z0-9_.-]{1,64}$"


class WorktreeManager:
    """git worktree 管理器 — 为子Agent创建隔离的工作空间"""

    @staticmethod
    def create(name: str = "", base_ref: str = "fresh") -> tuple[str, str]:
        """创建 git worktree

        Args:
            name: worktree 名称 (字母/数字/./-/_ , max 64)
            base_ref: "fresh"=从 origin/main 分支, "head"=从当前 HEAD

        Returns:
            (worktree_path, branch_name)
        """
        import re

        safe_name = name or f"wt-{_uuid.uuid4().hex[:8]}"
        safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "-", safe_name)[:64]
        branch_name = f"worktree/{safe_name}"

        # 确保 .claude/worktrees 存在
        wt_dir = Path(".claude/worktrees")
        wt_dir.mkdir(parents=True, exist_ok=True)
        worktree_path = wt_dir / safe_name

        try:
            # 确定 base
            if base_ref == "fresh":
                # 尝试从 origin/main 或 origin/master 创建
                base = "origin/main"
                try:
                    subprocess.run(
                        ["git", "rev-parse", "--verify", "origin/main"],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                except Exception:
                    logger.warning("operation_failed", exc_info=True)
                    base = "HEAD"
            else:
                base = "HEAD"

            # git worktree add <path> <branch> <base>
            result = subprocess.run(
                ["git", "worktree", "add", str(worktree_path), "-b", branch_name, base],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                # 分支可能已存在 → 直接 add
                result2 = subprocess.run(
                    ["git", "worktree", "add", str(worktree_path), branch_name],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result2.returncode != 0:
                    logger.warning("worktree_create_failed", stderr=result.stderr, name=safe_name)
                    # 降级: 创建目录 (向后兼容)
                    worktree_path.mkdir(parents=True, exist_ok=True)
                    return str(worktree_path), branch_name

            logger.info("worktree_created", name=safe_name, branch=branch_name, path=str(worktree_path))
            return str(worktree_path), branch_name

        except FileNotFoundError:
            # git 不可用 → 降级目录模式
            logger.warning("worktree_git_not_found", name=safe_name)
            worktree_path.mkdir(parents=True, exist_ok=True)
            return str(worktree_path), branch_name
        except Exception as e:
            logger.error("worktree_create_exception", name=safe_name, error=str(e), exc_info=True)
            worktree_path.mkdir(parents=True, exist_ok=True)
            return str(worktree_path), branch_name

    @staticmethod
    def cleanup(worktree_path: str, action: str = "keep", discard_changes: bool = False) -> bool:
        """清理 git worktree

        Args:
            worktree_path: worktree 路径
            action: "keep" 保留 | "remove" 删除
            discard_changes: remove 时是否强制丢弃未提交变更

        Returns:
            True 清理成功
        """
        p = Path(worktree_path)
        if action != "remove":
            logger.info("worktree_kept", path=str(p))
            return True

        if not p.exists():
            logger.info("worktree_already_gone", path=str(p))
            return True

        try:
            # 尝试 git worktree remove
            cmd = ["git", "worktree", "remove", str(p)]
            if discard_changes:
                cmd.insert(2, "--force")
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                logger.warning("worktree_git_remove_failed", stderr=result.stderr, path=str(p))
                # 降级: 直接删除目录
                import shutil

                shutil.rmtree(p, ignore_errors=True)
                # 清理 git worktree list 中的引用
                subprocess.run(
                    ["git", "worktree", "prune"],
                    capture_output=True,
                    check=False,
                )
            logger.info("worktree_removed", path=str(p))
            return True
        except FileNotFoundError:
            # git 不可用 → 直接删目录
            import shutil

            shutil.rmtree(p, ignore_errors=True)
            logger.info("worktree_removed_fallback", path=str(p))
            return True
        except Exception as e:
            logger.error("worktree_cleanup_exception", path=str(p), error=str(e), exc_info=True)
            return False

    @staticmethod
    def list_worktrees() -> list[dict]:
        """列出所有 git worktree"""
        try:
            result = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                capture_output=True,
                text=True,
                check=False,
            )
            worktrees = []
            current: dict = {}
            for line in result.stdout.strip().split("\n"):
                if line.startswith("worktree "):
                    if current:
                        worktrees.append(current)
                    current = {"path": line.split(" ", 1)[1]}
                elif line.startswith(("HEAD ", "branch ")):
                    key, val = line.split(" ", 1)
                    current[key] = val
            if current:
                worktrees.append(current)
            return worktrees
        except Exception:
            logger.warning("list_worktrees_failed", exc_info=True)
            return []
