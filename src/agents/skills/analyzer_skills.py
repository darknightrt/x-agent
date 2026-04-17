"""
数据分析 Skills

提供笔记和评论分析的业务技能
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from models.business_models import (
    XhsNoteModel,
    XhsCommentModel,
    XhsPostAnalysis,
    PostWithCommentsAnalysis,
    CommentsAnalysis
)
from agents.base_agent import BaseAgent


logger = logging.getLogger(__name__)


async def analyze_post_skill(
    agent: BaseAgent,
    note: Dict[str, Any],
    business_idea: str,
    max_retries: int = 2
) -> Dict[str, Any]:
    """
    分析单条笔记

    Args:
        agent: Agent 实例
        note: 笔记数据
        business_idea: 业务创意
        max_retries: 最大重试次数

    Returns:
        分析结果
    """
    note_id = note.get('note_id', 'unknown')
    logger.info(f"Analyzing note: {note.get('title', 'Unknown')} (id={note_id})")

    # 构建分析提示
    note_text = f"""
标题: {note.get('title', '')}
描述: {note.get('desc', '')}
收藏: {note.get('collected_count', 0)}
评论: {note.get('comments_count', 0)}
分享: {note.get('shared_count', 0)}
作者: {note.get('user_nickname', '')}
"""

    prompt = f"""
你是一位“每日行业新闻简报”内容分析专家。请分析以下小红书笔记与业务创意的相关性：

业务创意："{business_idea}"

笔记内容：
{note_text}

请把这条笔记的关键信息提炼为“行业新闻简报”可用素材：
 - `analysis_summary`：用于“热点帖子内容（Hot News）”卡片摘要（建议 全文输出，包含主题 + 为什么重要）
 - `hot_topics/engagement_score`：用于推导“本期看点（Highlights）”的要点关键词和互动评分（不需要写长段叙事）

请分析：
1. 相关性：这个笔记是否与新闻关键词相关？
   【重要】相关性判断要宽松：只要笔记内容与业务创意有**一定关联**（包括直接相关、间接相关等），都应该判断为相关。
   - 直接相关：明确提到业务创意相关的内容
   - 间接相关：提到相关关键词、用户需求、热点话题等
2. 情感倾向（sentiment）：
   - positive（正面）：笔记内容积极、充满希望、表达认可或支持
   - negative（负面）：笔记内容消极、表达担忧、不满或反对
   - neutral（中性）：笔记内容客观描述，或无明显情感倾向
   注意：只有当笔记确实没有明显情感倾向时才使用neutral，不要过度使用
3. 互动评分：根据收藏/分享/评论数与互动强度给出 1-10 分的互动评分（用于统计平均互动评分）

请以 JSON 格式返回：
{{
    "relevant": true/false,
    "sentiment": "positive/negative/neutral",
    "engagement_score": 8,
    "analysis_summary": "简短分析摘要"
}}
"""

    # 重试逻辑
    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                logger.warning(f"Retry attempt {attempt}/{max_retries} for note {note_id}")
                await asyncio.sleep(2 ** attempt)  # 指数退避

            result = await agent.use_llm(
                prompt=prompt,
                response_model=XhsPostAnalysis
            )

            if hasattr(result, 'model_dump'):
                analysis = result.model_dump()
            else:
                analysis = result

            logger.info(f"Analysis complete: relevant={analysis.get('relevant')}, sentiment={analysis.get('sentiment')}")

            return {
                "success": True,
                "note_id": note_id,
                "analysis": analysis
            }

        except (ValueError, ConnectionError, TimeoutError) as e:
            # 可重试的错误
            if attempt < max_retries:
                logger.warning(f"Attempt {attempt + 1} failed for note {note_id}: {type(e).__name__}: {e}")
                # 如果是 ValueError，打印更详细的信息
                if isinstance(e, ValueError):
                    import traceback
                    logger.debug(f"ValueError traceback for note {note_id}:\n{''.join(traceback.format_tb(e.__traceback__))}")
                continue
            else:
                logger.error(f"All retries exhausted for note {note_id}: {type(e).__name__}: {e}")
                # 如果是 ValueError，打印更详细的信息
                if isinstance(e, ValueError):
                    import traceback
                    logger.error(f"ValueError details for note {note_id}:\n{''.join(traceback.format_tb(e.__traceback__))}")

                # 使用 fallback 分析
                fallback_analysis = _fallback_analysis(note, business_idea)
                logger.info(f"Using fallback analysis for note {note_id}")

                return {
                    "success": False,
                    "note_id": note_id,
                    "analysis": fallback_analysis,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "fallback": True
                }

        except Exception as e:
            # 不可重试的错误（如 JSON 解析错误）
            logger.error(f"Analyze post skill failed for note {note_id}: {type(e).__name__}: {e}")
            return {
                "success": False,
                "note_id": note_id,
                "analysis": {
                    "relevant": False,
                    "pain_points": [],
                    "solutions_mentioned": [],
                    "market_signals": [],
                    "sentiment": "neutral",
                    "engagement_score": 1,
                    "analysis_summary": f"分析失败: {type(e).__name__}"
                },
                "error": str(e),
                "error_type": type(e).__name__
            }


async def analyze_post_with_comments_skill(
    agent: BaseAgent,
    post_with_comments: Dict[str, Any],
    business_idea: str,
    max_retries: int = 2
) -> Dict[str, Any]:
    """
    分析帖子及其评论（统一分析）

    将帖子和它的评论作为一个整体进行综合分析，保留上下文关系。

    Args:
        agent: Agent 实例
        post_with_comments: 帖子数据（包含 comments_data）
        business_idea: 业务创意
        max_retries: 最大重试次数

    Returns:
        分析结果
    """
    note_id = post_with_comments.get('note_id', 'unknown')
    title = post_with_comments.get('title', 'Unknown')
    logger.info(f"Analyzing post with comments: {title} (id={note_id})")

    # 构建帖子内容
    post_text = f"""
标题: {post_with_comments.get('title', '')}
描述: {post_with_comments.get('desc', '')}
收藏: {post_with_comments.get('collected_count', 0)}
分享: {post_with_comments.get('shared_count', 0)}
评论: {post_with_comments.get('comments_count', 0)}
作者: {post_with_comments.get('user_nickname', '')}
"""

    # 提取评论内容
    comments = post_with_comments.get('comments_data', [])
    comments_text = ""
    if comments:
        # 选取前20条评论进行分析（避免token过多）
        sample_comments = comments[:20]
        comments_text = "\n".join([
            f"- [{c.get('user_nickname', 'Anonymous')}] {c.get('content', '')}"
            for c in sample_comments
        ])
    else:
        comments_text = "(该帖子暂无评论)"

    # 构建统一分析提示
    prompt = f"""
你是一位“每日行业新闻简报”内容分析专家。请综合分析以下推特帖子及其评论，判断其与业务创意的相关性：

业务创意："{business_idea}"

=== 帖子内容 ===
{post_text}

=== 用户评论 ({len(comments)} 条，显示前 {min(20, len(comments))} 条) ===
{comments_text}

请把这条“帖子+评论”的关键信息提炼为“行业新闻简报”可用素材：
 - `analysis_summary`：用于“热点帖子内容（Hot News）”卡片摘要（建议全文输出，包含主题 + 讨论要点）
 - `hot_topics/engagement_score`：用于推导“本期看点（Highlights）”的要点关键词和互动评分（不需要写长段叙事）

请进行综合分析：

1. 相关性判断：这个帖子（包括评论）是否与业务创意相关？
   【重要】相关性判断要宽松：只要帖子内容或评论与业务创意有**任何关联**（包括直接相关、间接相关、潜在相关、场景相关、用户群体相关等），都应该判断为相关。
   - 直接相关：明确提到业务创意相关的产品/服务
   - 间接相关：提到相关场景、用户需求、痛点等
7. 评论情感（feedback_sentiment）：基于评论整体情感判断
   - positive（正面）：评论中包含赞美、满意、推荐、期待等积极情绪
   - negative（负面）：评论中包含抱怨、不满、批评、担忧等消极情绪
   - neutral（中性）：评论主要是客观描述、询问、或情绪不明显
   注意：只有当评论确实没有明显情感倾向时才使用neutral，不要过度使用
8. 整体情感（sentiment）：综合帖子和评论的整体情感倾向
   - positive（正面）：整体氛围积极，用户表达出兴趣、认可或支持
   - negative（负面）：整体氛围消极，用户表达出不满、担忧或反对
   - neutral（中性）：整体内容客观，或积极与消极情绪相当
9. 互动评分：1-10分，基于收藏/分享/评论数量和质量

请以 JSON 格式返回：
{{
    "note_id": "{note_id}",
    "title": "{title}",
    "relevant": true/false,
    "user_needs": ["需求1", "需求2"],
    "feedback_sentiment": "positive/negative/neutral",
    "sentiment": "positive/negative/neutral",
    "engagement_score": 8,
    "analysis_summary": "热点帖子卡片摘要（建议全文输出，含主题+讨论要点）",
    "comments_count": {len(comments)}
}}
"""

    # 重试逻辑 - 失败后跳过（不使用 fallback）
    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                logger.warning(f"Retry attempt {attempt}/{max_retries} for post {note_id}")
                await asyncio.sleep(2 ** attempt)  # 指数退避

            result = await agent.use_llm(
                prompt=prompt,
                response_model=PostWithCommentsAnalysis
            )

            if hasattr(result, 'model_dump'):
                analysis = result.model_dump()
            else:
                analysis = result

            logger.info(f"Analysis complete for {note_id}: relevant={analysis.get('relevant')}, sentiment={analysis.get('sentiment')}")

            return {
                "success": True,
                "note_id": note_id,
                "analysis": analysis
            }

        except (ValueError, ConnectionError, TimeoutError) as e:
            # 可重试的错误
            if attempt < max_retries:
                logger.warning(f"Attempt {attempt + 1} failed for post {note_id}: {type(e).__name__}: {e}")
                # 如果是 ValueError，打印更详细的信息
                if isinstance(e, ValueError):
                    import traceback
                    logger.debug(f"ValueError traceback for post {note_id}:\n{''.join(traceback.format_tb(e.__traceback__))}")
                continue
            else:
                # 所有重试失败 - 跳过此帖子（不使用 fallback）
                logger.error(f"All retries exhausted for post {note_id}: {type(e).__name__}: {e}")
                return {
                    "success": False,
                    "note_id": note_id,
                    "analysis": None,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "skipped": True
                }

        except Exception as e:
            # 不可重试的错误
            logger.error(f"Analyze post with comments skill failed for post {note_id}: {type(e).__name__}: {e}")
            return {
                "success": False,
                "note_id": note_id,
                "analysis": None,
                "error": str(e),
                "error_type": type(e).__name__,
                "skipped": True
            }


async def analyze_comments_skill(
    agent: BaseAgent,
    comments: List[Dict[str, Any]],
    business_idea: str,
    max_retries: int = 2
) -> Dict[str, Any]:
    """
    分析评论

    Args:
        agent: Agent 实例
        comments: 评论列表或字典 {note_id: [comments]}
        business_idea: 业务创意
        max_retries: 最大重试次数

    Returns:
        评论分析结果
    """
    # 处理不同的输入格式
    if isinstance(comments, dict):
        # 如果是字典，展平所有评论
        all_comments = []
        for note_comments in comments.values():
            if isinstance(note_comments, list):
                all_comments.extend(note_comments)
        comments_list = all_comments
    else:
        comments_list = comments

    logger.info(f"Analyzing {len(comments_list)} comments")

    if not comments_list:
        return {
            "success": True,
            "total_comments": 0,
            "analysis": {
                "insights": [],
                "common_themes": [],
                "user_needs": [],
                "pain_points": []
            }
        }

    # 选取前20条评论进行分析（避免token过多）
    sample_comments = comments_list[:40]

    comments_text = "\n".join([
        f"- [{c.get('user_nickname', 'Anonymous')}] {c.get('content', '')}"
        for c in sample_comments
    ])

    prompt = f"""
你是一位“每日行业新闻简报”评论洞察专家。请分析以下小红书评论，提取用户对业务创意的反馈：

业务创意："{business_idea}"

评论内容：
{comments_text}

请把评论内容提炼为“本期看点（Highlights）/热点讨论要点”可用信息：
1. 用户洞察：从评论中提取的关键洞察（1-2 句话或短语）
2. 常见主题：评论中反复出现的主题（用于概括热点）

请以 JSON 格式返回：
{{
    "insights": ["洞察1", "洞察2"],
    "common_themes": ["主题1", "主题2"],
}}
"""

    # 重试逻辑
    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                logger.warning(f"Retry attempt {attempt}/{max_retries} for comments analysis")
                await asyncio.sleep(2 ** attempt)  # 指数退避

            result = await agent.use_llm(
                prompt=prompt,
                response_model=CommentsAnalysis
            )

            # 转换为字典
            if hasattr(result, 'model_dump'):
                analysis_dict = result.model_dump()
            else:
                analysis_dict = result

            logger.info(f"Comments analysis complete: {len(analysis_dict.get('insights', []))} insights")

            return {
                "success": True,
                "total_comments": len(comments_list),
                "analyzed_comments": len(sample_comments),
                "analysis": analysis_dict
            }

        except (ValueError, ConnectionError, TimeoutError) as e:
            # 可重试的错误
            if attempt < max_retries:
                logger.warning(f"Attempt {attempt + 1} failed for comments analysis: {e}, will retry...")
                continue
            else:
                logger.error(f"All retries exhausted for comments analysis: {e}")
                return {
                    "success": False,
                    "total_comments": len(comments_list),
                    "analysis": {
                        "insights": [],
                        "common_themes": [],
                        "user_needs": [],
                        "pain_points": []
                    },
                    "error": str(e),
                    "error_type": type(e).__name__
                }

        except Exception as e:
            # 不可重试的错误（如 JSON 解析错误）
            logger.error(f"Analyze comments skill failed: {type(e).__name__}: {e}")
            return {
                "success": False,
                "total_comments": len(comments_list),
                "analysis": {
                    "insights": [],
                    "common_themes": [],
                    "user_needs": [],
                    "pain_points": []
                },
                "error": str(e),
                "error_type": type(e).__name__
            }


async def batch_analyze_posts_skill(
    agent: BaseAgent,
    posts: List[Dict[str, Any]],
    business_idea: str,
    progress_callback: Optional[callable] = None
) -> Dict[str, Any]:
    """
    批量分析笔记

    Args:
        agent: Agent 实例
        posts: 笔记列表
        business_idea: 业务创意
        progress_callback: 进度回调

    Returns:
        批量分析结果
    """
    logger.info(f"Batch analyzing {len(posts)} posts")

    if not posts:
        return {
            "success": True,
            "total_posts": 0,
            "analyses": [],
            "relevant_count": 0,
            "summary": {}
        }

    all_analyses = []
    relevant_posts = []

    total = len(posts)
    for idx, post in enumerate(posts):
        try:
            if progress_callback:
                # Import ProgressUpdate model
                from models.agent_models import ProgressUpdate
                progress = idx / total  # 0-1 range
                update = ProgressUpdate(
                    step="analyzing_posts",
                    progress=progress,
                    message=f"正在分析笔记 {idx + 1}/{total}"
                )
                progress_callback(update)

            result = await analyze_post_skill(agent, post, business_idea)

            if result.get("success"):
                analysis = result.get("analysis", {})
                all_analyses.append({
                    "note_id": post.get("note_id"),
                    "title": post.get("title"),
                    "analysis": analysis
                })

                if analysis.get("relevant"):
                    relevant_posts.append({
                        "post": post,
                        "analysis": analysis
                    })

        except asyncio.CancelledError:
            # 任务被取消（超时）
            logger.warning(f"Batch analysis cancelled at post {idx + 1}/{total} (likely timeout)")
            # 返回已分析的部分结果
            partial_summary = _calculate_partial_summary(all_analyses, total)
            return {
                "success": False,
                "total_posts": total,
                "analyses": all_analyses,
                "relevant_posts": relevant_posts,
                "summary": partial_summary,
                "error": f"Operation cancelled (timeout) - analysed {len(all_analyses)}/{total} posts",
                "error_type": "CancelledError",
                "completed": len(all_analyses),
                "partial": True
            }

        except Exception as e:
            logger.error(f"Failed to analyze post {post.get('note_id')}: {e}")
            continue

    # 统计摘要
    relevant_count = len(relevant_posts)
    avg_engagement = 0

    for a in all_analyses:
        analysis = a.get("analysis", {})
        avg_engagement += analysis.get("engagement_score", 0)

    if all_analyses:
        avg_engagement = avg_engagement / len(all_analyses)

    summary = {
        "total_posts": len(posts),
        "analyzed_count": len(all_analyses),
        "relevant_count": relevant_count,
        "relevance_rate": relevant_count / len(all_analyses) if all_analyses else 0,
        "avg_engagement_score": avg_engagement
    }

    logger.info(f"Batch analysis complete: {relevant_count}/{len(posts)} relevant")

    return {
        "success": True,
        "total_posts": len(posts),
        "analyses": all_analyses,
        "relevant_posts": relevant_posts,
        "summary": summary
    }


async def batch_analyze_posts_with_comments_skill(
    agent: BaseAgent,
    posts_with_comments: List[Dict[str, Any]],
    business_idea: str,
    progress_callback: Optional[callable] = None,
    max_posts: Optional[int] = None
) -> Dict[str, Any]:
    """
    批量分析帖子及其评论（统一分析）

    每个帖子与其评论作为一个整体进行综合分析，失败时跳过（不使用fallback）。

    Args:
        agent: Agent 实例
        posts_with_comments: 包含评论的帖子列表
        business_idea: 业务创意
        progress_callback: 进度回调
        max_posts: 最大分析帖子数（从配置获取，如果未指定则分析全部）

    Returns:
        批量分析结果
    """
    # 应用最大帖子数限制
    if max_posts is not None and max_posts > 0:
        original_count = len(posts_with_comments)
        posts_with_comments = posts_with_comments[:max_posts]
        logger.info(f"应用 max_posts 限制: 从 {original_count} 条减少到 {len(posts_with_comments)} 条")

    logger.info(f"Batch analyzing {len(posts_with_comments)} posts with comments")

    if not posts_with_comments:
        return {
            "success": True,
            "total_posts": 0,
            "analyses": [],
            "relevant_posts": [],
            "summary": {
                "total_posts": 0,
                "successful_count": 0,
                "failed_count": 0,
                "skipped_count": 0,
                "relevant_count": 0
            }
        }

    all_analyses = []
    relevant_posts = []
    successful_count = 0
    failed_count = 0
    skipped_count = 0

    total = len(posts_with_comments)
    for idx, post in enumerate(posts_with_comments):
        try:
            if progress_callback:
                from models.agent_models import ProgressUpdate
                progress = idx / total  # 0-1 range
                update = ProgressUpdate(
                    step="analyzing_posts_with_comments",
                    progress=progress,
                    message=f"正在分析帖子+评论 {idx + 1}/{total}"
                )
                progress_callback(update)

            result = await analyze_post_with_comments_skill(agent, post, business_idea)

            if result.get("success"):
                analysis = result.get("analysis", {})
                all_analyses.append({
                    "note_id": post.get("note_id"),
                    "title": post.get("title"),
                    "analysis": analysis
                })
                successful_count += 1

                if analysis.get("relevant"):
                    relevant_posts.append({
                        "post": post,
                        "analysis": analysis
                    })
            else:
                # 分析失败，跳过此帖子（不添加到结果中）
                failed_count += 1
                if result.get("skipped"):
                    skipped_count += 1
                # 记录日志但继续处理
                logger.warning(
                    f"Skipped post {post.get('note_id')}: "
                    f"{result.get('error_type', 'Unknown')}"
                )

        except asyncio.CancelledError:
            # 任务被取消（超时）
            logger.warning(f"Batch analysis cancelled at post {idx + 1}/{total} (likely timeout)")
            # 返回已分析的部分结果
            partial_summary = _calculate_partial_summary_with_comments(all_analyses, total)
            partial_summary["successful_count"] = successful_count
            partial_summary["failed_count"] = failed_count
            partial_summary["skipped_count"] = skipped_count
            return {
                "success": False,
                "total_posts": total,
                "analyses": all_analyses,
                "relevant_posts": relevant_posts,
                "summary": partial_summary,
                "error": f"Operation cancelled (timeout) - analysed {len(all_analyses)}/{total} posts",
                "error_type": "CancelledError",
                "completed": len(all_analyses),
                "partial": True
            }

        except Exception as e:
            logger.error(f"Unexpected error analyzing post {post.get('note_id')}: {e}")
            failed_count += 1
            continue

    # 统计摘要
    relevant_count = len(relevant_posts)
    avg_engagement = 0

    for a in all_analyses:
        analysis = a.get("analysis", {})
        avg_engagement += analysis.get("engagement_score", 0)

    if all_analyses:
        avg_engagement = avg_engagement / len(all_analyses)

    summary = {
        "total_posts": total,
        "successful_count": successful_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "relevant_count": relevant_count,
        "relevance_rate": relevant_count / successful_count if successful_count > 0 else 0,
        "avg_engagement_score": avg_engagement
    }

    logger.info(
        f"Batch analysis complete: {successful_count}/{total} successful, "
        f"{relevant_count} relevant, {skipped_count} skipped"
    )

    return {
        "success": True,
        "total_posts": total,
        "analyses": all_analyses,
        "relevant_posts": relevant_posts,
        "summary": summary
    }


# ============================================================================
# 辅助函数
# ============================================================================

def _calculate_partial_summary(all_analyses: list, total_posts: int) -> dict:
    """
    计算部分分析结果的摘要

    Args:
        all_analyses: 已完成的分析列表
        total_posts: 总笔记数

    Returns:
        部分摘要字典
    """
    relevant_count = 0
    avg_engagement = 0

    for a in all_analyses:
        analysis = a.get("analysis", {})
        avg_engagement += analysis.get("engagement_score", 0)

        if analysis.get("relevant"):
            relevant_count += 1

    if all_analyses:
        avg_engagement = avg_engagement / len(all_analyses)

    return {
        "total_posts": total_posts,
        "analyzed_count": len(all_analyses),
        "relevant_count": relevant_count,
        "relevance_rate": relevant_count / len(all_analyses) if all_analyses else 0,
        "avg_engagement_score": avg_engagement,
        "partial": True,
        "note": f"部分结果：仅分析了 {len(all_analyses)}/{total_posts} 篇笔记"
    }


def _calculate_partial_summary_with_comments(all_analyses: list, total_posts: int) -> dict:
    """
    计算部分分析结果的摘要（带评论的版本）

    Args:
        all_analyses: 已完成的分析列表
        total_posts: 总帖子数

    Returns:
        部分摘要字典
    """
    relevant_count = 0
    avg_engagement = 0

    for a in all_analyses:
        analysis = a.get("analysis", {})
        avg_engagement += analysis.get("engagement_score", 0)

        if analysis.get("relevant"):
            relevant_count += 1

    if all_analyses:
        avg_engagement = avg_engagement / len(all_analyses)

    return {
        "total_posts": total_posts,
        "successful_count": len(all_analyses),
        "relevant_count": relevant_count,
        "relevance_rate": relevant_count / len(all_analyses) if all_analyses else 0,
        "avg_engagement_score": avg_engagement,
        "partial": True,
        "note": f"部分结果：仅分析了 {len(all_analyses)}/{total_posts} 篇帖子"
    }


def _fallback_analysis(note: Dict[str, Any], business_idea: str) -> Dict[str, Any]:
    """
    Fallback 分析：基于规则的简单分析

    当 LLM 失败时使用，确保系统能继续运行

    Args:
        note: 笔记数据
        business_idea: 业务创意

    Returns:
        分析结果字典
    """
    title = note.get('title', '').lower()
    desc = note.get('desc', '').lower()
    content = title + ' ' + desc

    business_lower = business_idea.lower()

    # 简单的关键词匹配判断相关性
    # 提取业务创意中的关键词（去除常见词）
    business_keywords = set()
    for word in business_lower.split():
        if len(word) > 1 and word not in ['在', '的', '是', '和', '与', '或', '了', '吗', '呢']:
            business_keywords.add(word)

    # 检查内容中是否包含关键词
    match_count = 0
    for keyword in business_keywords:
        if keyword in content:
            match_count += 1

    # 相关性判断：至少匹配一个关键词
    relevant = match_count > 0 or len(business_keywords) == 0

    # 基于互动数据的评分
    collected = note.get('collected_count', 0)
    shared = note.get('shared_count', 0)
    comments = note.get('comments_count', 0)

    # 简单的互动评分 (1-10)：不再使用点赞数
    total_engagement = collected * 2 + shared * 3 + comments * 3
    if total_engagement > 1000:
        engagement_score = 10
    elif total_engagement > 500:
        engagement_score = 8
    elif total_engagement > 100:
        engagement_score = 6
    elif total_engagement > 50:
        engagement_score = 4
    else:
        engagement_score = 2

    # 简单的情感判断（基于关键词）
    positive_words = ['好', '棒', '推荐', '喜欢', '爱', '优秀', '完美', '不错', '值得']
    negative_words = ['差', '坏', '不好', '失望', '糟糕', '后悔', '问题', '坑']

    positive_count = sum(1 for word in positive_words if word in content)
    negative_count = sum(1 for word in negative_words if word in content)

    if positive_count > negative_count:
        sentiment = 'positive'
    elif negative_count > positive_count:
        sentiment = 'negative'
    else:
        sentiment = 'neutral'

    return {
        "relevant": relevant,
        "pain_points": ["需要人工分析痛点"],
        "solutions_mentioned": ["需要人工分析解决方案"],
        "market_signals": [f"互动数据: {total_engagement}"],
        "sentiment": sentiment,
        "engagement_score": engagement_score,
        "analysis_summary": f"[Fallback分析] 相关性:{'是' if relevant else '否'}, 互动:{total_engagement}, 情感:{sentiment}"
    }
