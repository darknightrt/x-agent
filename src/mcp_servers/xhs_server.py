"""
小红书 MCP 服务器

基于 TikHub API 提供小红书数据获取服务
"""

import asyncio
import logging
import time
import aiohttp
from typing import Dict, Any, List, Optional
from datetime import datetime
from models.business_models import XhsNoteModel, XhsCommentModel
from agents.logging_config import RequestLogger


logger = logging.getLogger("mcp.xhs_server")


# ============================================================================
# TikHub API Client
# ============================================================================

class TikHubXHSClient:
    """
    TikHub API 客户端（使用异步 HTTP）
    """

    def __init__(self, auth_token: str):
        """
        初始化客户端

        Args:
            auth_token: TikHub API Token
        """
        self.auth_token = auth_token
        self.base_url = "https://api.tikhub.io"
        self.headers = {
            "Authorization": f"Bearer {auth_token}",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        self._session: Optional[aiohttp.ClientSession] = None

        # 请求日志记录器
        self.request_logger = RequestLogger(logger)

    async def start(self):
        """启动客户端（初始化异步会话）"""
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self):
        """关闭客户端"""
        if self._session:
            await self._session.close()
            self._session = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建会话"""
        if self._session is None:
            await self.start()
        return self._session

    async def search_notes(
        self,
        query: Optional[str] = None,
        keyword: Optional[str] = None,
        search_type: str = "Top",
        cursor: Optional[str] = None,
        end_cursor: Optional[str] = None,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """
        搜索内容（X/Twitter: fetch_search_timeline）

        参考你截图的接口参数：
        - GET /api/v1/twitter/web/fetch_search_timeline?keyword=...&search_type=Top&cursor=...

        兼容旧调用：若仍传 query/end_cursor，则会映射到 keyword/cursor。
        """
        url = f"{self.base_url}/api/v1/twitter/web/fetch_search_timeline"

        kw = (keyword if keyword is not None else query) or ""
        cur = cursor if cursor is not None else end_cursor

        params: Dict[str, Any] = {
            # 注意：aiohttp 会对 params 做 URL 编码；这里不要预先 quote，
            # 否则会出现双重编码（% -> %25），导致 TikHub 返回 400。
            "keyword": kw,
            "search_type": search_type or "Top",
        }
        if cur:
            params["cursor"] = cur

        for attempt in range(max_retries):
            session = await self._get_session()

            # 记录请求日志
            self.request_logger.log_request(
                api_name="TikHub.XHS",
                method="GET",
                url=url,
                params=params
            )

            start_time = time.time()

            try:
                async with session.get(
                    url,
                    headers=self.headers,
                    params=params
                ) as response:
                    duration_ms = (time.time() - start_time) * 1000

                    # 处理 429 Too Many Requests
                    if response.status == 429:
                        retry_after = int(response.headers.get('Retry-After', 5))
                        wait_time = retry_after + 1  # 额外加 1 秒缓冲

                        # 记录速率限制日志
                        self.request_logger.log_response(
                            api_name="TikHub.XHS",
                            status=429,
                            body={"retry_after": retry_after},
                            duration_ms=duration_ms
                        )

                        logger.warning(f"Rate limited (429) for search '{query}', waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                        await asyncio.sleep(wait_time)
                        continue

                    response.raise_for_status()
                    data = await response.json()

                    # 记录响应日志
                    _d = data.get("data", {})
                    _p = _d.get("data", {}) if isinstance(_d.get("data"), dict) else _d
                    _raw_list = (
                        _p.get("threads")
                        or _p.get("items")
                        or _p.get("notes")
                        or []
                    )
                    self.request_logger.log_response(
                        api_name="TikHub.XHS",
                        status=response.status,
                        body={
                            "result_count": len(_raw_list),
                            "keyword": kw,
                            "search_type": search_type or "Top",
                        },
                        duration_ms=duration_ms
                    )

                    return data

            except aiohttp.ClientError as e:
                duration_ms = (time.time() - start_time) * 1000

                # 记录错误日志
                self.request_logger.log_response(
                    api_name="TikHub.XHS",
                    error=str(e),
                    duration_ms=duration_ms
                )

                if attempt < max_retries - 1:
                    logger.warning(f"Search request failed for '{query}': {e}, retrying...")
                    await asyncio.sleep(2 ** attempt)  # 指数退避
                    continue
                else:
                    raise

    async def get_note_comments(
        self,
        post_id: Optional[str] = None,
        tweet_id: Optional[str] = None,
        cursor: Optional[str] = None,
        end_cursor: Optional[str] = None,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """
        获取帖子评论（X/Twitter: fetch_post_comments）

        兼容旧调用：若仍传 post_id/end_cursor，则会映射到 tweet_id/cursor。
        """
        url = f"{self.base_url}/api/v1/twitter/web/fetch_post_comments"

        tid = (tweet_id if tweet_id is not None else post_id) or ""
        cur = cursor if cursor is not None else end_cursor

        params: Dict[str, Any] = {"tweet_id": tid}
        if cur:
            params["cursor"] = cur

        for attempt in range(max_retries):
            session = await self._get_session()

            # 记录请求日志
            self.request_logger.log_request(
                api_name="TikHub.X",
                method="GET",
                url=url,
                params=params
            )

            start_time = time.time()

            try:
                async with session.get(
                    url,
                    headers=self.headers,
                    params=params
                ) as response:
                    duration_ms = (time.time() - start_time) * 1000

                    # 处理 429 Too Many Requests
                    if response.status == 429:
                        retry_after = int(response.headers.get('Retry-After', 5))
                        wait_time = retry_after + 1  # 额外加 1 秒缓冲

                        # 记录速率限制日志
                        self.request_logger.log_response(
                            api_name="TikHub.XHS",
                            status=429,
                            body={"retry_after": retry_after, "tweet_id": tid},
                            duration_ms=duration_ms
                        )

                        logger.warning(f"Rate limited (429) for tweet {tid}, waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                        await asyncio.sleep(wait_time)
                        continue

                    response.raise_for_status()
                    data = await response.json()

                    # 记录响应日志
                    try:
                        d1 = data.get("data", {})
                        d2 = d1.get("data", d1) if isinstance(d1, dict) else {}
                        d3 = d2.get("data", d2) if isinstance(d2, dict) and isinstance(d2.get("data"), dict) else d2
                        comments_len = len(d3.get("comments", [])) if isinstance(d3, dict) else 0
                        next_cursor_present = bool(d3.get("next_cursor")) if isinstance(d3, dict) else False
                        has_more_val = d3.get("has_more") if isinstance(d3, dict) else None
                    except Exception:
                        comments_len = 0
                        next_cursor_present = False
                        has_more_val = None

                    self.request_logger.log_response(
                        api_name="TikHub.X",
                        status=response.status,
                        body={
                            "comments_count": comments_len,
                            "next_cursor": "yes" if next_cursor_present else "no",
                            "has_more": has_more_val,
                            "tweet_id": tid
                        },
                        duration_ms=duration_ms
                    )

                    return data

            except aiohttp.ClientError as e:
                duration_ms = (time.time() - start_time) * 1000

                # 记录错误日志
                self.request_logger.log_response(
                    api_name="TikHub.X",
                    error=str(e),
                    duration_ms=duration_ms
                )

                if attempt < max_retries - 1:
                    logger.warning(f"Request failed for tweet {tid}: {e}, retrying...")
                    await asyncio.sleep(2 ** attempt)  # 指数退避
                    continue
                else:
                    raise


# ============================================================================
# MCP Server
# ============================================================================


class XHSMCPServer:
    """
    MCP 服务器

    提供工具:
    - search_notes: 搜索笔记
    - get_note_comments: 获取评论
    - batch_get_comments: 批量获取评论
    """

    def __init__(self, auth_token: str, request_delay: float = 1.0):
        """
        初始化 XHS MCP 服务器

        Args:
            auth_token: TikHub API Token
            request_delay: 请求延迟(秒)
        """
        self.auth_token = auth_token
        self.request_delay = request_delay
        self._client = None

        logger.info("XHS MCP Server initialized")

    async def start(self):
        """启动服务器"""
        self._client = TikHubXHSClient(self.auth_token)
        await self._client.start()
        logger.info("XHS MCP Server started")

    async def stop(self):
        """停止服务器"""
        if self._client:
            await self._client.close()
        logger.info("XHS MCP Server stopped")

    # ========================================================================
    # MCP 工具实现
    # ========================================================================

    async def call_tool(self, tool_name: str, **kwargs) -> Any:
        """
        调用工具

        Args:
            tool_name: 工具名称
            **kwargs: 工具参数

        Returns:
            工具执行结果
        """
        if tool_name == "search_notes":
            return await self.search_notes(**kwargs)
        elif tool_name == "get_note_comments":
            return await self.get_note_comments(**kwargs)
        elif tool_name == "batch_get_comments":
            return await self.batch_get_comments(**kwargs)
        else:
            raise ValueError(f"Unknown tool: {tool_name}")

    async def search_notes(
        self,
        query: Optional[str] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        pages: int = 1
    ) -> Dict[str, Any]:
        """
        搜索热门内容（与 TikHub search_top 一致：query、end_cursor；返回 threads / next_cursor / has_more）

        Args:
            query: 搜索关键词（与接口参数 query 同名，优先使用）
            keyword: 兼容旧参数，与 query 二选一
            page: 起始页码（内部循环用）
            pages: 连续请求的“页”数（每页用上一页的 next_cursor）

        Returns:
            {
                "success": true,
                "query": "关键词",
                "keyword": "关键词（兼容字段）",
                "notes": [笔记列表],
                "total_count": 笔记总数,
                "execution_time": 执行时间
            }
        """
        q = (query if query is not None else keyword)
        if not q:
            return {
                "success": False,
                "error": "search_notes 需要参数 query 或 keyword",
                "query": "",
                "keyword": "",
                "notes": [],
                "total_count": 0,
                "execution_time": 0.0,
            }

        start_time = datetime.now()

        all_notes = []
        seen_ids = set()
        next_cursor = None

        def _unwrap_payload(resp: Dict[str, Any]) -> Dict[str, Any]:
            """
            TikHub 的返回经常出现 data/data 甚至 data/data/data 的嵌套。
            这里做最多两层的解包，保证 threads/comments 等字段更容易取到。
            """
            d1 = resp.get("data", {})
            if not isinstance(d1, dict):
                return {}
            d2 = d1.get("data", d1)
            if isinstance(d2, dict) and isinstance(d2.get("data"), dict):
                return d2.get("data", d2)
            return d2 if isinstance(d2, dict) else {}

        def _first_str(*candidates: Any) -> str:
            for c in candidates:
                if isinstance(c, str) and c.strip():
                    return c.strip()
            return ""

        def _to_int_ts(value: Any) -> int:
            """
            TikHub Twitter Web API 的 created_at 形如:
            'Wed Apr 01 06:00:45 +0000 2026'。
            这里尽量转成 Unix timestamp (seconds)；失败则返回 0。
            """
            if value is None:
                return 0
            if isinstance(value, (int, float)):
                return int(value)
            if isinstance(value, str):
                s = value.strip()
                if not s:
                    return 0
                # 纯数字字符串
                if s.isdigit():
                    try:
                        return int(s)
                    except Exception:
                        return 0
                try:
                    dt = datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y")
                    return int(dt.timestamp())
                except Exception:
                    return 0
            return 0

        def _extract_post_id(item: Dict[str, Any]) -> str:
            """
            threads 语义下帖子 ID 字段不一定叫 id，且可能嵌套在 thread/post/note 下。
            为了让下游能调用 fetch_post_comments(post_id=...)，这里做多路径兼容。
            """
            for key in ("tweet_id", "id", "post_id", "thread_id", "tid", "note_id"):
                v = item.get(key)
                if isinstance(v, (str, int)) and str(v):
                    return str(v)
            for container_key in ("thread", "post", "note", "data"):
                obj = item.get(container_key)
                if isinstance(obj, dict):
                    for key in ("tweet_id", "id", "post_id", "thread_id", "tid", "note_id"):
                        v = obj.get(key)
                        if isinstance(v, (str, int)) and str(v):
                            return str(v)
            return ""

        def _extract_text(item: Dict[str, Any]) -> Dict[str, str]:
            """
            尝试提取 title/desc（或 threads 的 content/text 等）用于分析。
            返回 dict: {title, desc}
            """
            title = _first_str(
                item.get("title"),
                item.get("name"),
            )
            desc = _first_str(
                item.get("desc"),
                item.get("content"),
                item.get("text"),
                item.get("caption"),
                item.get("body"),
            )
            for container_key in ("thread", "post", "note", "data"):
                obj = item.get(container_key)
                if not isinstance(obj, dict):
                    continue
                title = title or _first_str(obj.get("title"), obj.get("name"))
                desc = desc or _first_str(
                    obj.get("desc"),
                    obj.get("content"),
                    obj.get("text"),
                    obj.get("caption"),
                    obj.get("body"),
                )
            return {"title": title, "desc": desc}

        def _extract_user(item: Dict[str, Any]) -> Dict[str, str]:
            user = item.get("user")
            if isinstance(user, dict):
                return {
                    "id": _first_str(user.get("id"), user.get("user_id"), user.get("uid")),
                    "nickname": _first_str(user.get("nickname"), user.get("name"), user.get("username")),
                    "avatar": _first_str(user.get("avatar"), user.get("avatar_url"), user.get("profile_image_url")),
                }
            # X/Twitter: user_info / author
            user_info = item.get("user_info")
            if isinstance(user_info, dict):
                return {
                    "id": _first_str(user_info.get("rest_id"), user_info.get("id"), user_info.get("user_id")),
                    "nickname": _first_str(user_info.get("name"), user_info.get("screen_name")),
                    "avatar": _first_str(user_info.get("avatar"), user_info.get("image")),
                }
            author = item.get("author")
            if isinstance(author, dict):
                return {
                    "id": _first_str(author.get("rest_id"), author.get("id"), author.get("user_id")),
                    "nickname": _first_str(author.get("name"), author.get("screen_name")),
                    "avatar": _first_str(author.get("avatar"), author.get("image")),
                }
            for container_key in ("thread", "post", "note", "data"):
                obj = item.get(container_key)
                if isinstance(obj, dict) and isinstance(obj.get("user"), dict):
                    u = obj.get("user", {})
                    return {
                        "id": _first_str(u.get("id"), u.get("user_id"), u.get("uid")),
                        "nickname": _first_str(u.get("nickname"), u.get("name"), u.get("username")),
                        "avatar": _first_str(u.get("avatar"), u.get("avatar_url"), u.get("profile_image_url")),
                    }
            return {"id": "", "nickname": "", "avatar": ""}

        # 搜索指定页数
        for p in range(page, page + pages):
            try:
                response = await self._client.search_notes(
                    keyword=q,
                    search_type="Top",
                    cursor=next_cursor
                )

                # 解析响应（接口文档：threads、next_cursor、has_more）
                payload = _unwrap_payload(response)
                # X/Twitter: fetch_search_timeline 的列表在 data.timeline
                if isinstance(response.get("data"), dict) and isinstance(response["data"].get("timeline"), list):
                    payload = response["data"]
                items = (
                    payload.get("timeline")
                    or payload.get("threads")
                    or payload.get("items")
                    or payload.get("notes")
                    or []
                )
                next_cursor = payload.get("next_cursor")
                has_more = payload.get("has_more")

                # 观测：便于定位“200 但解析为 0”
                if p == page:
                    try:
                        first_keys = list(items[0].keys()) if isinstance(items, list) and items else []
                    except Exception:
                        first_keys = []
                    logger.info(
                        f"search_top parsed: raw_items={len(items) if isinstance(items, list) else 0}, "
                        f"next_cursor={'yes' if next_cursor else 'no'}, has_more={has_more}, "
                        f"first_item_keys={first_keys[:20]}"
                    )

                for item in items:
                    # threads 返回可能没有 note 字段，这里直接以 item 为主，辅以多路径提取
                    note_data = item.get("note", item) if isinstance(item, dict) else {}
                    if not isinstance(note_data, dict):
                        continue

                    post_id = _extract_post_id(note_data)
                    text = _extract_text(note_data)
                    user = _extract_user(note_data)
                    # X/Twitter: timeline item 是 tweet，文本在 text
                    if not text.get("desc") and isinstance(note_data.get("text"), str):
                        text["desc"] = note_data.get("text", "")
                    if not text.get("title") and isinstance(note_data.get("screen_name"), str):
                        text["title"] = note_data.get("screen_name", "")

                    # 转换为模型
                    note = XhsNoteModel(
                        note_id=post_id,
                        title=text.get("title", ""),
                        desc=text.get("desc", ""),
                        type=str(note_data.get("type", "normal") or "normal"),
                        publish_time=_to_int_ts(note_data.get("time", note_data.get("created_at", 0))),
                        # X/Twitter: favorites/bookmarks/retweets/replies
                        collected_count=int(
                            note_data.get("collected_count", note_data.get("bookmarks", note_data.get("favorites", 0))) or 0
                        ),
                        shared_count=int(
                            note_data.get("shared_count", note_data.get("retweets", note_data.get("share_count", 0))) or 0
                        ),
                        comments_count=int(
                            note_data.get("comments_count", note_data.get("replies", note_data.get("comment_count", 0))) or 0
                        ),
                        user_id=user.get("id", ""),
                        user_nickname=user.get("nickname", ""),
                        user_avatar=user.get("avatar", ""),
                        keyword_matched=q
                    )

                    # 去重
                    if note.note_id and note.note_id not in seen_ids:
                        seen_ids.add(note.note_id)
                        all_notes.append(note.model_dump())

                if has_more is False or not next_cursor:
                    break

                # 延迟避免限流
                if p < page + pages - 1:
                    await asyncio.sleep(self.request_delay)

            except Exception as e:
                logger.error(f"Search page {p} failed: {e}")
                continue

        execution_time = (datetime.now() - start_time).total_seconds()

        logger.info(f"Search complete: {len(all_notes)} notes in {execution_time:.2f}s")

        return {
            "success": True,
            "query": q,
            "keyword": q,
            "notes": all_notes,
            "total_count": len(all_notes),
            "execution_time": execution_time
        }

    async def get_note_comments(
        self,
        post_id: Optional[str] = None,
        note_id: Optional[str] = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        获取帖子评论（与 TikHub fetch_post_comments 一致：post_id、end_cursor；返回 comments、next_cursor、has_more）

        Args:
            post_id: 帖子 ID（与接口参数 post_id 同名，优先使用）
            note_id: 兼容旧参数，与 post_id 二选一（小红书语境下与帖子 ID 相同）
            limit: 最大评论数

        Returns:
            {
                "success": true,
                "post_id": "帖子ID",
                "note_id": "同上（兼容字段）",
                "comments": [评论列表],
                "total_count": 评论总数,
                "execution_time": 执行时间
            }
        """
        pid = post_id if post_id is not None else note_id
        if not pid:
            return {
                "success": False,
                "error": "get_note_comments 需要参数 post_id 或 note_id",
                "post_id": "",
                "note_id": "",
                "comments": [],
                "total_count": 0,
                "execution_time": 0.0,
            }

        start_time = datetime.now()

        try:
            comments = []
            next_cursor = None
            has_more = True

            while has_more and len(comments) < limit:
                response = await self._client.get_note_comments(
                    tweet_id=pid,
                    cursor=next_cursor
                )

                # 解析评论
                data = response.get("data", {})
                payload = data.get("data", {}) if isinstance(data.get("data"), dict) else data
                # X/Twitter: fetch_post_comments 评论在 data.thread
                comment_items = payload.get("comments", [])
                if not comment_items and isinstance(payload.get("thread"), list):
                    comment_items = payload.get("thread", [])
                next_cursor = payload.get("next_cursor") or payload.get("cursor")
                has_more = bool(payload.get("has_more", False)) or bool(next_cursor)

                if not comment_items:
                    break

                for item in comment_items:
                    if len(comments) >= limit:
                        break
                    author = item.get("author", {}) if isinstance(item.get("author"), dict) else {}
                    content = item.get("content")
                    if not isinstance(content, str) or not content:
                        content = item.get("text") if isinstance(item.get("text"), str) else ""
                    if not content and isinstance(item.get("display_text"), str):
                        content = item.get("display_text", "")
                    comment = XhsCommentModel(
                        comment_id=str(item.get("id", "")),
                        note_id=pid,
                        content=content,
                        publish_time=item.get("time", 0) or 0,
                        ip_location=item.get("ip_location", "") or "",
                        user_id=str(author.get("rest_id", "") or author.get("id", "") or ""),
                        user_nickname=str(author.get("screen_name", "") or author.get("name", "") or ""),
                        parent_comment_id=str(item.get("parent_comment", {}).get("id", "") if isinstance(item.get("parent_comment"), dict) else "")
                    )
                    comments.append(comment.model_dump())

                if has_more and len(comments) < limit and next_cursor:
                    await asyncio.sleep(self.request_delay)

            execution_time = (datetime.now() - start_time).total_seconds()

            logger.info(f"Got {len(comments)} comments in {execution_time:.2f}s")

            return {
                "success": True,
                "post_id": pid,
                "note_id": pid,
                "comments": comments,
                "total_count": len(comments),
                "execution_time": execution_time
            }

        except Exception as e:
            logger.error(f"Get comments failed: {e}")
            return {
                "success": False,
                "post_id": pid,
                "note_id": pid,
                "comments": [],
                "total_count": 0,
                "error": str(e),
                "execution_time": (datetime.now() - start_time).total_seconds()
            }

    async def batch_get_comments(
        self,
        note_ids: List[str],
        comments_per_note: int = 20,
        delay_between_requests: float = 2.0
    ) -> Dict[str, Any]:
        """
        批量获取评论（串行以避免速率限制）

        Args:
            note_ids: 笔记 ID 列表
            comments_per_note: 每个笔记的评论数
            delay_between_requests: 请求之间的延迟（秒）

        Returns:
            {
                "success": true,
                "results": {note_id: [评论列表]},
                "total_comments": 总评论数,
                "execution_time": 执行时间
            }
        """
        start_time = datetime.now()

        logger.info(f"Batch getting comments for {len(note_ids)} notes (with {delay_between_requests}s delay)")

        # 串行获取评论以避免速率限制
        results_dict = {}
        total_comments = 0

        for idx, note_id in enumerate(note_ids):
            try:
                # 添加延迟（除了第一个请求）
                if idx > 0:
                    await asyncio.sleep(delay_between_requests)

                result = await self.get_note_comments(
                    post_id=note_id,
                    limit=comments_per_note,
                )

                if isinstance(result, dict) and result.get("success"):
                    comments = result.get("comments", [])
                    results_dict[note_id] = comments
                    total_comments += len(comments)
                    logger.info(f"Got {len(comments)} comments for note {note_id} ({idx + 1}/{len(note_ids)})")
                else:
                    logger.error(f"Failed to get comments for {note_id}: {result.get('error', 'Unknown error')}")
                    results_dict[note_id] = []

            except asyncio.CancelledError:
                # 任务被取消（超时）
                logger.warning(f"Batch operation cancelled at note {idx + 1}/{len(note_ids)} (likely timeout)")
                # 返回已获取的部分结果
                execution_time = (datetime.now() - start_time).total_seconds()
                logger.info(f"Partial batch complete: {total_comments} comments from {len(results_dict)} notes in {execution_time:.2f}s")
                return {
                    "success": False,
                    "results": results_dict,
                    "total_comments": total_comments,
                    "execution_time": execution_time,
                    "error": "Operation cancelled - likely timeout. Returning partial results.",
                    "error_type": "CancelledError",
                    "completed": len(results_dict),
                    "total": len(note_ids)
                }

            except Exception as e:
                logger.error(f"Failed to get comments for {note_id}: {e}")
                results_dict[note_id] = []

        execution_time = (datetime.now() - start_time).total_seconds()

        logger.info(f"Batch complete: {total_comments} comments in {execution_time:.2f}s")

        return {
            "success": True,
            "results": results_dict,
            "total_comments": total_comments,
            "execution_time": execution_time
        }

    async def ping(self) -> bool:
        """健康检查"""
        return self._client is not None


# ============================================================================
# 服务器工厂
# ============================================================================

async def create_xhs_mcp_server(
    auth_token: str,
    request_delay: float = 1.0
) -> XHSMCPServer:
    """
    创建 XHS MCP 服务器实例

    Args:
        auth_token: TikHub API Token
        request_delay: 请求延迟

    Returns:
        XHS MCP 服务器实例
    """
    server = XHSMCPServer(auth_token, request_delay)
    await server.start()
    return server
