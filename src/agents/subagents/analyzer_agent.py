"""
数据分析 Agent

负责分析小红书笔记和评论数据
"""

import logging
import asyncio
from typing import Dict, Any, List
from datetime import datetime

from agents.base_agent import BaseAgent, AgentStatus, TaskResult
from agents.config import AgentConfig, ConfigManager, RetryConfig
from agents.context_store import ContextStore
from agents.skills.analyzer_skills import (
    analyze_post_skill,
    analyze_comments_skill,
    analyze_post_with_comments_skill,
    batch_analyze_posts_skill,
    batch_analyze_posts_with_comments_skill
)


logger = logging.getLogger("agent.analyzer")


class AnalyzerAgent(BaseAgent):
    """
    数据分析 Agent

    职责:
    1. 分析单条笔记的相关性和内容
    2. 分析评论提取用户洞察
    3. 批量分析笔记
    4. 输出统一分析结果供简报层消费

    Skills:
    - analyze_post: 分析单条笔记
    - analyze_comments: 分析评论
    - batch_analyze_posts: 批量分析笔记
    - batch_analyze_with_comments: 批量分析帖子+评论（统一分析）
    """

    def __init__(
        self,
        config: ConfigManager,
        context_store: ContextStore,
        mcp_clients: Dict[str, Any]
    ):
        # 从 ConfigManager 获取 agent 配置
        agent_configs = config.get_agent_configs()
        agent_config = agent_configs.get("analyzer", AgentConfig(
            name="analyzer_agent",
            type="analyzer",
            enabled=True,
            timeout=600.0
        ))

        super().__init__(
            name="analyzer_agent",
            config=agent_config,
            context_store=context_store,
            mcp_clients=mcp_clients
        )

    async def execute(
        self,
        task: str,
        context: Dict[str, Any],
        **kwargs
    ) -> TaskResult:
        """
        执行分析任务

        Args:
            task: 任务类型 (analyze_post/analyze_comments/batch_analyze/batch_analyze_with_comments)
            context: 执行上下文
            **kwargs: 额外参数

        Returns:
            TaskResult: 任务执行结果
        """
        self.status = AgentStatus.RUNNING
        start_time = datetime.now()

        try:
            if task == "analyze_post":
                result = await self._analyze_post(context, kwargs)
            elif task == "analyze_comments":
                result = await self._analyze_comments(context, kwargs)
            elif task == "batch_analyze":
                result = await self._batch_analyze(context, kwargs)
            elif task == "batch_analyze_with_comments":
                result = await self._batch_analyze_with_comments(context, kwargs)
            else:
                raise ValueError(f"Unknown task: {task}")

            execution_time = (datetime.now() - start_time).total_seconds()
            self._update_metrics(True, execution_time)

            self.status = AgentStatus.COMPLETED
            return TaskResult(
                success=True,
                data=result,
                agent_name=self.name,
                execution_time=execution_time
            )

        except Exception as e:
            logger.exception(f"Analyzer task failed: {task}")
            execution_time = (datetime.now() - start_time).total_seconds()
            self._update_metrics(False, execution_time)

            self.status = AgentStatus.FAILED
            return TaskResult(
                success=False,
                error=str(e),
                agent_name=self.name,
                execution_time=execution_time
            )

    async def _analyze_post(
        self,
        context: Dict[str, Any],
        kwargs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        分析单条笔记

        Args:
            context: 执行上下文
            kwargs: 参数
                - note: 笔记数据
                - business_idea: 业务创意

        Returns:
            分析结果
        """
        note = context.get("note", kwargs.get("note", {}))
        business_idea = context.get("business_idea", kwargs.get("business_idea", ""))

        if not note:
            raise ValueError("note is required")
        if not business_idea:
            raise ValueError("business_idea is required")

        self.update_progress(
            "analyzing_post",
            0.5,
            f"正在分析笔记: {note.get('title', 'Unknown')}"
        )

        # 调用 skill
        result = await analyze_post_skill(self, note, business_idea)

        if result.get("success"):
            self.update_progress("analyzing_post", 1.0, "笔记分析完成")
        else:
            self.update_progress("analyzing_post", 1.0, f"分析失败: {result.get('error', 'Unknown')}")

        return result

    async def _analyze_comments(
        self,
        context: Dict[str, Any],
        kwargs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        分析评论

        Args:
            context: 执行上下文
            kwargs: 参数
                - comments: 评论列表
                - business_idea: 业务创意

        Returns:
            评论分析结果
        """
        comments = context.get("comments", kwargs.get("comments", []))
        business_idea = context.get("business_idea", kwargs.get("business_idea", ""))

        if not business_idea:
            raise ValueError("business_idea is required")

        self.update_progress(
            "analyzing_comments",
            0.5,
            f"正在分析 {len(comments)} 条评论..."
        )

        # 调用 skill
        result = await analyze_comments_skill(self, comments, business_idea)

        if result.get("success"):
            self.update_progress("analyzing_comments", 1.0, "评论分析完成")
        else:
            self.update_progress("analyzing_comments", 1.0, f"分析失败: {result.get('error', 'Unknown')}")

        return result

    async def _batch_analyze(
        self,
        context: Dict[str, Any],
        kwargs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        批量分析笔记

        Args:
            context: 执行上下文
            kwargs: 参数
                - posts: 笔记列表
                - business_idea: 业务创意

        Returns:
            批量分析结果
        """
        posts = context.get("posts", kwargs.get("posts", []))
        business_idea = context.get("business_idea", kwargs.get("business_idea", ""))

        if not posts:
            raise ValueError("posts is required")
        if not business_idea:
            raise ValueError("business_idea is required")

        self.update_progress(
            "batch_analyzing",
            0.1,
            f"开始批量分析 {len(posts)} 条笔记..."
        )

        # 调用 skill - 直接传递 self 的进度回调
        result = await batch_analyze_posts_skill(
            self,
            posts=posts,
            business_idea=business_idea,
            progress_callback=self._progress_callback
        )

        # 处理结果（包括部分结果）
        if result.get("success") or result.get("partial"):
            summary = result.get("summary", {})
            analyzed = summary.get("analyzed_count", len(result.get("analyses", [])))
            total = summary.get("total_posts", len(posts))

            if result.get("partial"):
                self.update_progress(
                    "batch_analyzing",
                    1.0,
                    f"批量分析部分完成: {analyzed}/{total} 条笔记（超时）"
                )
                logger.warning(f"Batch analysis partial: {analyzed}/{total} posts analyzed")
            else:
                self.update_progress(
                    "batch_analyzing",
                    1.0,
                    f"批量分析完成: {summary.get('relevant_count', 0)}/{len(posts)} 条相关笔记"
                )

            # 保存检查点（即使是部分结果也保存）
            run_id = context.get("run_id")
            if run_id:
                await self.save_checkpoint(
                    run_id,
                    "analysis_complete",
                    {
                        "posts_analyses": result
                    }
                )
        else:
            self.update_progress("batch_analyzing", 1.0, "批量分析失败")

        return result

    async def _batch_analyze_with_comments(
        self,
        context: Dict[str, Any],
        kwargs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        批量分析帖子及其评论（统一分析）

        每个帖子与其评论作为一个整体进行综合分析，失败时跳过。

        Args:
            context: 执行上下文
            kwargs: 参数
                - posts_with_comments: 包含评论的帖子列表
                - business_idea: 业务创意

        Returns:
            批量分析结果
        """
        posts_with_comments = context.get("posts_with_comments", kwargs.get("posts_with_comments", []))
        business_idea = context.get("business_idea", kwargs.get("business_idea", ""))

        if not posts_with_comments:
            raise ValueError("posts_with_comments is required")
        if not business_idea:
            raise ValueError("business_idea is required")

        # 从配置获取最大分析帖子数
        from agents.config import ConfigManager
        config_mgr = ConfigManager()
        max_posts = config_mgr.get('agents.scraper.max_posts_to_analyze', 20)
        logger.info(f"配置的最大分析帖子数: {max_posts}")

        self.update_progress(
            "batch_analyzing_with_comments",
            0.1,
            f"开始统一分析 {min(len(posts_with_comments), max_posts)} 条帖子+评论..."
        )

        # 调用 skill - 直接传递 self 的进度回调和 max_posts 限制
        result = await batch_analyze_posts_with_comments_skill(
            self,
            posts_with_comments=posts_with_comments,
            business_idea=business_idea,
            progress_callback=self._progress_callback,
            max_posts=max_posts
        )

        # 处理结果（包括部分结果）
        if result.get("success") or result.get("partial"):
            summary = result.get("summary", {})
            successful = summary.get("successful_count", len(result.get("analyses", [])))
            total = summary.get("total_posts", len(posts_with_comments))

            if result.get("partial"):
                self.update_progress(
                    "batch_analyzing_with_comments",
                    1.0,
                    f"统一分析部分完成: {successful}/{total} 条（超时）"
                )
                logger.warning(f"Batch analysis partial: {successful}/{total} posts analyzed")
            else:
                self.update_progress(
                    "batch_analyzing_with_comments",
                    1.0,
                    f"统一分析完成: {summary.get('relevant_count', 0)}/{total} 条相关帖子，"
                    f"跳过 {summary.get('skipped_count', 0)} 条"
                )

            # 保存检查点（新格式）
            run_id = context.get("run_id")
            if run_id:
                await self.save_checkpoint(
                    run_id,
                    "analysis_complete",
                    {
                        "posts_with_comments_analyses": result
                    }
                )
        else:
            self.update_progress("batch_analyzing_with_comments", 1.0, "统一分析失败")

        return result

    def _update_metrics(
        self,
        success: bool,
        execution_time: float
    ):
        """更新运行指标"""
        self.metrics.tasks_completed += 1 if success else 0
        self.metrics.tasks_failed += 0 if success else 1
        self.metrics.total_execution_time += execution_time

        total = self.metrics.tasks_completed + self.metrics.tasks_failed
        if total > 0:
            self.metrics.avg_execution_time = self.metrics.total_execution_time / total

        self.metrics.last_execution = datetime.now()
