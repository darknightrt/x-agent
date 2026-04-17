"""
业务数据模型

定义业务验证相关的数据模型
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime


# ============================================================================
# 关键词相关
# ============================================================================

class KeywordModel(BaseModel):
    """关键词模型"""
    keywords: List[str] = Field(description="关键词列表")


class KeywordRefinement(BaseModel):
    """关键词优化结果"""
    original_keywords: List[str] = Field(description="原始关键词")
    refined_keywords: List[str] = Field(description="优化后的关键词")
    refinement_reason: str = Field(description="优化原因")
    suggested_additions: List[str] = Field(description="建议添加的关键词")


# ============================================================================
# 小红书笔记相关
# ============================================================================

class XhsNoteModel(BaseModel):
    """小红书笔记模型"""
    note_id: str = Field(description="笔记 ID")
    title: str = Field(description="标题")
    desc: Optional[str] = Field(default=None, description="描述")
    type: str = Field(default="normal", description="笔记类型: normal/video")
    publish_time: int = Field(description="发布时间戳")
    collected_count: int = Field(default=0, description="收藏数")
    shared_count: int = Field(default=0, description="分享数")
    comments_count: int = Field(default=0, description="评论数")
    user_id: str = Field(description="用户 ID")
    user_nickname: str = Field(description="用户昵称")
    user_avatar: Optional[str] = Field(default=None, description="用户头像")
    cover_url: Optional[str] = Field(default=None, description="封面图 URL")
    images: List[str] = Field(default_factory=list, description="图片列表")
    keyword_matched: Optional[str] = Field(default=None, description="匹配的关键词")


class XhsCommentModel(BaseModel):
    """评论模型"""
    comment_id: str = Field(description="评论 ID")
    note_id: str = Field(description="笔记 ID")
    content: str = Field(description="评论内容")
    publish_time: int = Field(description="发布时间戳")
    ip_location: Optional[str] = Field(default=None, description="IP 地理位置")
    user_id: str = Field(description="用户 ID")
    user_nickname: str = Field(description="用户昵称")
    parent_comment_id: Optional[str] = Field(default=None, description="父评论 ID")


class PostWithComments(BaseModel):
    """Post with embedded comments for unified analysis"""
    # All fields from XhsNoteModel
    note_id: str = Field(description="笔记 ID")
    title: str = Field(description="标题")
    desc: Optional[str] = Field(default=None, description="描述")
    type: str = Field(default="normal", description="笔记类型: normal/video")
    publish_time: int = Field(description="发布时间戳")
    collected_count: int = Field(default=0, description="收藏数")
    shared_count: int = Field(default=0, description="分享数")
    comments_count: int = Field(default=0, description="评论数")
    user_id: str = Field(description="用户 ID")
    user_nickname: str = Field(description="用户昵称")
    user_avatar: Optional[str] = Field(default=None, description="用户头像")
    cover_url: Optional[str] = Field(default=None, description="封面图 URL")
    images: List[str] = Field(default_factory=list, description="图片列表")
    keyword_matched: Optional[str] = Field(default=None, description="匹配的关键词")

    # Embedded comments (NEW)
    comments_data: List[XhsCommentModel] = Field(default_factory=list, description="该帖子的评论数据")
    comments_fetched: bool = Field(default=False, description="是否已获取评论")
    comments_fetch_error: Optional[str] = Field(default=None, description="评论获取错误信息")


# ============================================================================
# 分析相关
# ============================================================================

class XhsPostAnalysis(BaseModel):
    """x帖子分析结果"""
    relevant: bool = Field(description="是否与业务创意相关")
    hot_topics: List[str] = Field(default_factory=list, description="热点话题（用于推导 Highlights）")
    sentiment: str = Field(description="情感倾向: positive/negative/neutral")
    engagement_score: int = Field(default=0, ge=1, le=10, description="互动评分 1-10")
    analysis_summary: Optional[str] = Field(default=None, description="分析摘要")


class PostWithCommentsAnalysis(BaseModel):
    """Unified analysis result for post + its comments"""
    note_id: str = Field(description="笔记 ID")
    title: str = Field(description="标题")

    # Core analysis (from post + comments)
    relevant: bool = Field(description="是否与业务创意相关")
    hot_topics: List[str] = Field(default_factory=list, description="热点话题（来自帖子+评论，用于推导 Highlights）")
    feedback_sentiment: str = Field(description="评论情感倾向: positive/negative/neutral")

    # Overall assessment
    sentiment: str = Field(description="整体情感倾向: positive/negative/neutral")
    engagement_score: int = Field(default=0, ge=1, le=10, description="互动评分 1-10")
    analysis_summary: Optional[str] = Field(default=None, description="分析摘要")
    comments_count: int = Field(default=0, description="分析的评论数")


class BriefingAnalysis(BaseModel):
    """行业新闻简报分析结果"""
    metadata: Dict[str, Any] = Field(default_factory=dict, description="简报元数据")


class CommentsAnalysis(BaseModel):
    """评论分析结果"""
    hot_topics: List[str] = Field(default_factory=list, description="热点话题（来自评论，用于推导 Highlights）")


# ============================================================================
# 验证结果相关
# ============================================================================

class ValidationResult(BaseModel):
    """验证结果"""
    business_idea: str = Field(description="业务创意")
    run_id: str = Field(description="运行 ID")
    timestamp: datetime = Field(default_factory=datetime.now, description="验证时间")
    analysis: BriefingAnalysis = Field(description="简报分析")
    raw_data: Dict[str, Any] = Field(default_factory=dict, description="原始数据引用")
    execution_stats: Dict[str, Any] = Field(default_factory=dict, description="执行统计")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
