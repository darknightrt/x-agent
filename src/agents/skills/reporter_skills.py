import logging
import re
from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path

from agents.base_agent import BaseAgent


logger = logging.getLogger(__name__)


def _strip_sentiment_labels(text: str) -> str:
    """
    简报展示层不展示情感标签（例如“情感: positive/negative/neutral”）。
    这里做最小侵入清洗，避免 analysis_summary 的 fallback 把“情感”字样带到页面/文本。
    """
    if not text:
        return ""

    # 清理形如：情感: positive / sentiment: negative / feedback_sentiment: neutral
    text = re.sub(
        r"(情感|sentiment|feedback_sentiment)[:：]\s*(positive|negative|neutral|正面|负面|中性|积极|消极|中立)\b",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # 清理孤立的正负中性词（仅作为短标签出现）
    text = re.sub(r"\b(positive|negative|neutral)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(正面|负面|中性|积极|消极|中立)\b", "", text)

    # 清理多余标点/空格
    text = re.sub(r"[，,]\s*$", "", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


def _extract_brief_topic(post: Dict[str, Any], max_len: int = 44) -> str:
    """
    用于“本期看点”的短主题：
    - 优先使用帖子 title
    - 若 title 缺失，则从 analysis_summary 中提取第一句/主题行
    """
    title = str(post.get("title", "") or "").strip()
    if title:
        return title[:max_len] + ("..." if len(title) > max_len else "")

    summary = _strip_sentiment_labels(str(post.get("analysis_summary", "") or "").strip())
    if not summary:
        return "未命名主题"

    # 常见模式：主题：xxx。/ 标题: xxx。/ 第一行即主题
    first_line = summary.splitlines()[0].strip()
    m = re.search(r"(主题|标题)\s*[:：]\s*(.+)$", first_line)
    topic = (m.group(2).strip() if m else first_line)
    topic = re.split(r"[。！？!?\n\r]", topic, maxsplit=1)[0].strip()
    if not topic:
        topic = summary[:max_len]
    return topic[:max_len] + ("..." if len(topic) > max_len else "")


def _extract_highlight_item(post: Dict[str, Any]) -> str:
    """
    “本期要点”条目应同时包含：主题 + 摘要（与用户阅读目标一致）。
    - 主题：优先 title；否则从 summary 中抽取
    - 摘要：优先 analysis_summary；否则回退到内容片段
    """
    topic = _extract_brief_topic(post, max_len=44)
    summary = _safe_snippet(post, max_len=180)
    summary = _strip_sentiment_labels(str(summary or "").strip())
    if not summary or summary == "暂无摘要":
        return f"{topic}"
    return f"{topic} — {summary}"


def _build_briefing_data(analysis: Dict[str, Any]) -> Dict[str, Any]:
    combined_analysis = analysis.get("analysis", {}) or {}
    metadata = combined_analysis.get("metadata", {}) or {}

    total_posts = int(metadata.get("total_posts_analyzed", 0) or 0)
    relevant_posts = int(metadata.get("relevant_posts", 0) or 0)
    avg_engagement_score = float(metadata.get("avg_engagement_score", 0) or 0)
    total_comments_analyzed = int(metadata.get("total_comments_analyzed", 0) or 0)
    top_posts = metadata.get("top_posts", []) or []
    related_posts = metadata.get("related_posts", []) or []

    # 本期要点：展示“主题 + 摘要”，更符合阅读与复盘
    highlight_items: List[str] = []
    seen_items: set[str] = set()
    source_posts = related_posts if related_posts else top_posts
    for post in source_posts[:10]:
        item = _extract_highlight_item(post)
        normalized = re.sub(r"\s+", " ", (item or "").strip())
        if not normalized or normalized in seen_items:
            continue
        seen_items.add(normalized)
        highlight_items.append(normalized)
        if len(highlight_items) >= 5:
            break

    if not highlight_items:
        highlight_items.append("暂无明确要点（样本不足）")

    return {
        "metadata": metadata,
        "stats": {
            "total_posts_analyzed": total_posts,
            "relevant_posts": relevant_posts,
            "avg_engagement_score": avg_engagement_score,
            "total_comments_analyzed": total_comments_analyzed,
        },
        "top_posts": top_posts,
        "related_posts": related_posts,
        "highlights": highlight_items[:5],
    }


def _safe_snippet(post: Dict[str, Any], max_len: int = 180) -> str:
    summary = _strip_sentiment_labels(str(post.get("analysis_summary", "")).strip())
    if summary:
        return summary[:max_len] + ("..." if len(summary) > max_len else "")
    raw = str(post.get("content") or post.get("desc") or "").strip()
    if not raw:
        return "暂无摘要"
    return raw[:max_len] + ("..." if len(raw) > max_len else "")


async def generate_text_report_skill(
    agent: BaseAgent,
    analysis: Dict[str, Any],
    business_idea: str,
    run_id: str
) -> Dict[str, Any]:
    logger.info("Generating text briefing report")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    briefing = _build_briefing_data(analysis)
    stats = briefing["stats"]
    highlights = briefing["highlights"]

    lines = [
        "=" * 80,
        "行业新闻简报",
        "=" * 80,
        f"业务创意: {business_idea}",
        f"日期时间: {now}",
        f"运行 ID: {run_id}",
        "",
        "[本期看点]",
    ]
    for idx, item in enumerate(highlights, start=1):
        lines.append(f"{idx}. {item}")

    lines.extend([
        "",
        "[统计数据]",
        f"- 分析帖子: {stats['total_posts_analyzed']}",
        f"- 相关帖子: {stats['relevant_posts']}",
        f"- 平均互动评分: {stats['avg_engagement_score']:.1f}",
        f"- 分析评论数: {stats['total_comments_analyzed']}",
    ])

    report = "\n".join(lines).rstrip() + "\n"
    return {"success": True, "report_format": "text", "content": report, "length": len(report)}


async def generate_html_report_skill(
    agent: BaseAgent,
    analysis: Dict[str, Any],
    business_idea: str,
    run_id: str,
    posts_data: Optional[Dict[str, Any]] = None,
    comments_data: Optional[Dict[str, Any]] = None,
    tag_analysis: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    logger.info("Generating HTML briefing report")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    briefing = _build_briefing_data(analysis)
    stats = briefing["stats"]
    highlights = briefing["highlights"]

    def _render_news_cards(posts: List[Dict[str, Any]]) -> str:
        if not posts:
            return '<div class="news-card">暂无相关内容</div>'
        blocks: List[str] = []
        for i, post in enumerate(posts, start=1):
            title = str(post.get("title", "") or "未命名").strip()
            summary = _safe_snippet(post, max_len=260)
            collected = int(post.get("collected_count", 0) or 0)
            shared = int(post.get("shared_count", 0) or 0)
            comments = int(post.get("comments_count", 0) or 0)
            total_eng = int(post.get("total_engagement", collected * 2 + shared * 3 + comments * 3) or 0)
            blocks.append(f"""
            <div class="news-card">
                <div class="news-header">
                    <div style="display: flex; align-items: center; flex: 1;">
                        <div class="news-rank">{i}</div>
                        <div class="news-title">{title}</div>
                    </div>
                </div>
                <div class="news-summary">{summary}</div>
                <div class="news-stats">
                    <div class="news-stat">总互动: <span class="news-stat-value">{total_eng}</span></div>
                    <div class="news-stat">藏: <span class="news-stat-value">{collected}</span></div>
                    <div class="news-stat">分享: <span class="news-stat-value">{shared}</span></div>
                    <div class="news-stat">评: <span class="news-stat-value">{comments}</span></div>
                </div>
            </div>""")
        return "\n".join(blocks)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>行业新闻简报 - {business_idea}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
            line-height: 1.6;
            max-width: 980px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #333;
            border-bottom: 3px solid #ff2442;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #555;
            margin-top: 30px;
            border-left: 4px solid #ff2442;
            padding-left: 10px;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(4, minmax(140px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }}
        .stat-box {{
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }}
        .stat-label {{
            font-size: 12px;
            color: #666;
            margin-bottom: 5px;
        }}
        .stat-value {{
            font-size: 24px;
            font-weight: bold;
            color: #333;
        }}
        .metadata {{
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            font-size: 14px;
            color: #666;
            margin-bottom: 20px;
        }}
        .hot-news-section {{
            margin: 20px 0;
        }}
        .news-card {{
            background: white;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            margin: 15px 0;
            padding: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }}
        .news-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 2px solid #f0f0f0;
        }}
        .news-title {{
            font-size: 18px;
            font-weight: bold;
            color: #333;
            flex: 1;
        }}
        .news-rank {{
            background: #ff2442;
            color: white;
            width: 32px;
            height: 32px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            margin-right: 15px;
            flex-shrink: 0;
        }}
        .news-stats {{
            display: flex;
            gap: 15px;
            margin: 10px 0;
            flex-wrap: wrap;
        }}
        .news-stat {{
            background: #f8f9fa;
            padding: 6px 12px;
            border-radius: 4px;
            font-size: 13px;
            color: #666;
        }}
        .news-stat-value {{
            font-weight: bold;
            color: #333;
        }}
        .news-summary {{
            margin: 10px 0;
            padding: 12px;
            background: #f8f9fa;
            border-left: 3px solid #ff2442;
            border-radius: 4px;
            font-size: 14px;
            color: #555;
        }}
        .highlight-list {{ margin: 10px 0; padding-left: 18px; }}
        .highlight-list li {{ margin: 8px 0; color: #444; }}
        .highlight-ordered {{ padding-left: 22px; }}
        .highlight-ordered li {{ margin: 10px 0; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>行业新闻简报</h1>

        <div class="metadata">
            <strong>业务创意:</strong> {business_idea}<br>
            <strong>日期时间:</strong> {now}<br>
            <strong>运行 ID:</strong> {run_id}
        </div>

        <h2>本期要点</h2>
        <ol class="highlight-list highlight-ordered">
            {"".join([f"<li>{item}</li>" for item in highlights])}
        </ol>

        <h2>统计数据</h2>
        <div class="stats-grid">
            <div class="stat-box">
                <div class="stat-label">分析帖子数</div>
                <div class="stat-value">{stats["total_posts_analyzed"]}</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">相关帖子</div>
                <div class="stat-value">{stats["relevant_posts"]}</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">平均互动评分</div>
                <div class="stat-value">{stats["avg_engagement_score"]:.1f}</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">分析评论数</div>
                <div class="stat-value">{stats["total_comments_analyzed"]}</div>
            </div>
        </div>

        <h2>热点帖子内容</h2>
        <div class="hot-news-section">
            {_render_news_cards(briefing["top_posts"])}
        </div>

        <h2>相关内容</h2>
        <div class="hot-news-section">
            {_render_news_cards(briefing["related_posts"])}
        </div>
    </div>
</body>
</html>
"""

    return {"success": True, "report_format": "html", "content": html, "length": len(html)}


async def save_report_skill(
    agent: BaseAgent,
    report_content: str,
    report_format: str,
    output_path: str
) -> Dict[str, Any]:
    """
    保存报告到文件

    Args:
        agent: Agent 实例
        report_content: 报告内容
        report_format: 报告格式 (text/html)
        output_path: 输出路径

    Returns:
        保存结果
    """
    logger.info(f"Saving report to: {output_path}")

    try:
        # 创建输出目录
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # 写入文件
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(report_content)

        file_size = output_file.stat().st_size

        logger.info(f"Report saved: {output_path} ({file_size} bytes)")

        return {
            "success": True,
            "path": str(output_file.absolute()),
            "format": report_format,
            "size": file_size
        }

    except Exception as e:
        logger.error(f"Save report failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }

