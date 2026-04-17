"""
Threads/X (TikHub) MCP 服务器

基于 TikHub API:
- /api/v1/threads/web/search_recent       (search recent content)
- /api/v1/threads/web/fetch_post_comments (get post comments)
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp

from agents.logging_config import RequestLogger
from models.business_models import XhsCommentModel, XhsNoteModel


logger = logging.getLogger("mcp.threads_server")


class TikHubThreadsClient:
    """
    TikHub Threads/X API 客户端（异步 HTTP）

    - GET /api/v1/threads/web/search_recent?query=...&end_cursor=...
    - GET /api/v1/threads/web/fetch_post_comments?post_id=...&end_cursor=...
    """

    def __init__(self, auth_token: str):
        self.auth_token = auth_token
        self.base_url = "https://api.tikhub.io"
        self.headers = {
            "Authorization": f"Bearer {auth_token}",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        self._session: Optional[aiohttp.ClientSession] = None
        self.request_logger = RequestLogger(logger)

    async def start(self):
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self):
        if self._session:
            await self._session.close()
            self._session = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            await self.start()
        return self._session

    async def search_recent(
        self,
        query: str,
        end_cursor: Optional[str] = None,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/api/v1/threads/web/search_recent"
        params: Dict[str, Any] = {"query": query}
        if end_cursor:
            params["end_cursor"] = end_cursor

        for attempt in range(max_retries):
            session = await self._get_session()
            self.request_logger.log_request(
                api_name="TikHub.Threads",
                method="GET",
                url=url,
                params=params,
            )

            start_time = time.time()
            try:
                async with session.get(url, headers=self.headers, params=params) as response:
                    duration_ms = (time.time() - start_time) * 1000

                    if response.status == 429:
                        retry_after = int(response.headers.get("Retry-After", 5))
                        wait_time = retry_after + 1
                        self.request_logger.log_response(
                            api_name="TikHub.Threads",
                            status=429,
                            body={"retry_after": retry_after, "query": query},
                            duration_ms=duration_ms,
                        )
                        logger.warning(
                            f"Rate limited (429) for search '{query}', waiting {wait_time}s before retry "
                            f"{attempt + 1}/{max_retries}"
                        )
                        await asyncio.sleep(wait_time)
                        continue

                    response.raise_for_status()
                    data = await response.json()

                    # 轻量记录：结果数
                    try:
                        d1 = data.get("data", {})
                        d2 = d1.get("data", d1) if isinstance(d1, dict) else {}
                        payload = d2.get("data", d2) if isinstance(d2, dict) and isinstance(d2.get("data"), dict) else d2
                        threads = (
                            payload.get("threads")
                            or payload.get("items")
                            or payload.get("notes")
                            or []
                        )
                        result_count = len(threads) if isinstance(threads, list) else 0
                    except Exception:
                        result_count = 0

                    self.request_logger.log_response(
                        api_name="TikHub.Threads",
                        status=response.status,
                        body={"result_count": result_count, "query": query},
                        duration_ms=duration_ms,
                    )
                    return data

            except aiohttp.ClientError as e:
                duration_ms = (time.time() - start_time) * 1000
                self.request_logger.log_response(
                    api_name="TikHub.Threads",
                    error=str(e),
                    duration_ms=duration_ms,
                )
                if attempt < max_retries - 1:
                    logger.warning(f"Search request failed for '{query}': {e}, retrying...")
                    await asyncio.sleep(2**attempt)
                    continue
                raise

        return {"success": False, "error": "search_recent retries exhausted"}

    async def fetch_post_comments(
        self,
        post_id: str,
        end_cursor: Optional[str] = None,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/api/v1/threads/web/fetch_post_comments"
        params: Dict[str, Any] = {"post_id": post_id}
        if end_cursor:
            params["end_cursor"] = end_cursor

        for attempt in range(max_retries):
            session = await self._get_session()
            self.request_logger.log_request(
                api_name="TikHub.Threads",
                method="GET",
                url=url,
                params=params,
            )

            start_time = time.time()
            try:
                async with session.get(url, headers=self.headers, params=params) as response:
                    duration_ms = (time.time() - start_time) * 1000

                    if response.status == 429:
                        retry_after = int(response.headers.get("Retry-After", 5))
                        wait_time = retry_after + 1
                        self.request_logger.log_response(
                            api_name="TikHub.Threads",
                            status=429,
                            body={"retry_after": retry_after, "post_id": post_id},
                            duration_ms=duration_ms,
                        )
                        logger.warning(
                            f"Rate limited (429) for post {post_id}, waiting {wait_time}s before retry "
                            f"{attempt + 1}/{max_retries}"
                        )
                        await asyncio.sleep(wait_time)
                        continue

                    response.raise_for_status()
                    data = await response.json()

                    try:
                        d1 = data.get("data", {})
                        d2 = d1.get("data", d1) if isinstance(d1, dict) else {}
                        payload = d2.get("data", d2) if isinstance(d2, dict) and isinstance(d2.get("data"), dict) else d2
                        comments = payload.get("comments", []) if isinstance(payload, dict) else []
                        comments_len = len(comments) if isinstance(comments, list) else 0
                        next_cursor_present = bool(payload.get("next_cursor")) if isinstance(payload, dict) else False
                        has_more_val = payload.get("has_more") if isinstance(payload, dict) else None
                    except Exception:
                        comments_len = 0
                        next_cursor_present = False
                        has_more_val = None

                    self.request_logger.log_response(
                        api_name="TikHub.Threads",
                        status=response.status,
                        body={
                            "comments_count": comments_len,
                            "next_cursor": "yes" if next_cursor_present else "no",
                            "has_more": has_more_val,
                            "post_id": post_id,
                        },
                        duration_ms=duration_ms,
                    )
                    return data

            except aiohttp.ClientError as e:
                duration_ms = (time.time() - start_time) * 1000
                self.request_logger.log_response(
                    api_name="TikHub.Threads",
                    error=str(e),
                    duration_ms=duration_ms,
                )
                if attempt < max_retries - 1:
                    logger.warning(f"Request failed for post {post_id}: {e}, retrying...")
                    await asyncio.sleep(2**attempt)
                    continue
                raise

        return {"success": False, "error": "fetch_post_comments retries exhausted"}


class ThreadsMCPServer:
    """
    Threads/X (TikHub) MCP 服务器

    提供工具:
    - search_recent: 搜索最新内容（query, end_cursor）
    - fetch_post_comments: 获取帖子评论（post_id, end_cursor）
    - batch_fetch_post_comments: 批量获取评论（串行）
    """

    def __init__(self, auth_token: str, request_delay: float = 1.0):
        self.auth_token = auth_token
        self.request_delay = request_delay
        self._client: Optional[TikHubThreadsClient] = None
        logger.info("Threads MCP Server initialized")

    async def start(self):
        self._client = TikHubThreadsClient(self.auth_token)
        await self._client.start()
        logger.info("Threads MCP Server started")

    async def stop(self):
        if self._client:
            await self._client.close()
            self._client = None
        logger.info("Threads MCP Server stopped")

    async def call_tool(self, tool_name: str, **kwargs) -> Any:
        if tool_name == "search_recent":
            return await self.search_recent(**kwargs)
        if tool_name == "fetch_post_comments":
            return await self.fetch_post_comments(**kwargs)
        if tool_name == "batch_fetch_post_comments":
            return await self.batch_fetch_post_comments(**kwargs)
        raise ValueError(f"Unknown tool: {tool_name}")

    # ----------------------------
    # tool: search_recent
    # ----------------------------
    async def search_recent(
        self,
        query: str,
        page: int = 1,
        pages: int = 1,
    ) -> Dict[str, Any]:
        """
        搜索最新内容（按 pages 做多次请求，游标用 end_cursor 串起来）

        返回形状对齐现有 scraper_skills：
        {
          success: true,
          notes: [...],
          total_count: n,
          execution_time: seconds,
          raw: {keyword, last_cursor, has_more}
        }
        """
        if not query:
            return {"success": False, "error": "search_recent requires query", "notes": [], "total_count": 0}

        start_time = datetime.now()
        all_posts: List[Dict[str, Any]] = []
        seen_ids = set()
        next_cursor: Optional[str] = None
        has_more: Optional[bool] = None

        def _unwrap_payload(resp: Dict[str, Any]) -> Dict[str, Any]:
            d1 = resp.get("data", {})
            if not isinstance(d1, dict):
                return {}
            d2 = d1.get("data", d1)
            if isinstance(d2, dict) and isinstance(d2.get("data"), dict):
                return d2.get("data", d2)
            return d2 if isinstance(d2, dict) else {}

        def _first_str(*cands: Any) -> str:
            for c in cands:
                if isinstance(c, str) and c.strip():
                    return c.strip()
            return ""

        def _extract_post_id(item: Dict[str, Any]) -> str:
            for key in ("id", "post_id", "thread_id", "tid", "note_id"):
                v = item.get(key)
                if isinstance(v, (str, int)) and str(v):
                    return str(v)
            for container_key in ("thread", "post", "note", "data"):
                obj = item.get(container_key)
                if isinstance(obj, dict):
                    for key in ("id", "post_id", "thread_id", "tid", "note_id"):
                        v = obj.get(key)
                        if isinstance(v, (str, int)) and str(v):
                            return str(v)
            return ""

        def _extract_text(item: Dict[str, Any]) -> Dict[str, str]:
            title = _first_str(item.get("title"), item.get("name"))
            desc = _first_str(item.get("desc"), item.get("content"), item.get("text"), item.get("body"), item.get("caption"))
            for container_key in ("thread", "post", "note", "data"):
                obj = item.get(container_key)
                if not isinstance(obj, dict):
                    continue
                title = title or _first_str(obj.get("title"), obj.get("name"))
                desc = desc or _first_str(obj.get("desc"), obj.get("content"), obj.get("text"), obj.get("body"), obj.get("caption"))
            return {"title": title, "desc": desc}

        def _extract_user(item: Dict[str, Any]) -> Dict[str, str]:
            def _from_user(u: Dict[str, Any]) -> Dict[str, str]:
                return {
                    "id": _first_str(u.get("id"), u.get("user_id"), u.get("uid")),
                    "nickname": _first_str(u.get("nickname"), u.get("name"), u.get("username")),
                    "avatar": _first_str(u.get("avatar"), u.get("avatar_url"), u.get("profile_image_url")),
                }

            user = item.get("user")
            if isinstance(user, dict):
                return _from_user(user)
            for container_key in ("thread", "post", "note", "data"):
                obj = item.get(container_key)
                if isinstance(obj, dict) and isinstance(obj.get("user"), dict):
                    return _from_user(obj.get("user", {}))
            return {"id": "", "nickname": "", "avatar": ""}

        if not self._client:
            return {"success": False, "error": "Threads client not started", "notes": [], "total_count": 0}

        for p in range(page, page + pages):
            resp = await self._client.search_recent(query=query, end_cursor=next_cursor)
            payload = _unwrap_payload(resp)
            items = payload.get("threads") or payload.get("items") or payload.get("notes") or []
            next_cursor = payload.get("next_cursor")
            has_more = payload.get("has_more")

            if p == page:
                try:
                    first_keys = list(items[0].keys()) if isinstance(items, list) and items else []
                except Exception:
                    first_keys = []
                logger.info(
                    f"search_recent parsed: raw_items={len(items) if isinstance(items, list) else 0}, "
                    f"next_cursor={'yes' if next_cursor else 'no'}, has_more={has_more}, "
                    f"first_item_keys={first_keys[:20]}"
                )

            if not isinstance(items, list) or not items:
                break

            for item in items:
                if not isinstance(item, dict):
                    continue
                post_id = _extract_post_id(item)
                if not post_id or post_id in seen_ids:
                    continue
                seen_ids.add(post_id)

                text = _extract_text(item)
                user = _extract_user(item)

                note = XhsNoteModel(
                    note_id=post_id,
                    title=text.get("title", "") or "",
                    desc=text.get("desc", "") or "",
                    type=str(item.get("type", "normal") or "normal"),
                    publish_time=int(item.get("time", item.get("created_at", 0)) or 0),
                    collected_count=int(item.get("collected_count", item.get("like_count", 0)) or 0),
                    shared_count=int(item.get("shared_count", item.get("share_count", 0)) or 0),
                    comments_count=int(item.get("comments_count", item.get("comment_count", 0)) or 0),
                    user_id=user.get("id", ""),
                    user_nickname=user.get("nickname", ""),
                    user_avatar=user.get("avatar", ""),
                    keyword_matched=query,
                )
                all_posts.append(note.model_dump())

            if has_more is False or not next_cursor:
                break
            if p < page + pages - 1:
                await asyncio.sleep(self.request_delay)

        execution_time = (datetime.now() - start_time).total_seconds()
        return {
            "success": True,
            "query": query,
            "notes": all_posts,
            "total_count": len(all_posts),
            "execution_time": execution_time,
            "raw": {"next_cursor": next_cursor, "has_more": has_more},
        }

    # ----------------------------
    # tool: fetch_post_comments
    # ----------------------------
    async def fetch_post_comments(
        self,
        post_id: str,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        获取帖子评论（按 end_cursor 翻页直到 limit 或 has_more=false）
        """
        if not post_id:
            return {"success": False, "error": "fetch_post_comments requires post_id", "comments": [], "total_count": 0}

        if not self._client:
            return {"success": False, "error": "Threads client not started", "comments": [], "total_count": 0}

        start_time = datetime.now()
        comments: List[Dict[str, Any]] = []
        next_cursor: Optional[str] = None
        has_more: bool = True

        def _unwrap_payload(resp: Dict[str, Any]) -> Dict[str, Any]:
            d1 = resp.get("data", {})
            if not isinstance(d1, dict):
                return {}
            d2 = d1.get("data", d1)
            if isinstance(d2, dict) and isinstance(d2.get("data"), dict):
                return d2.get("data", d2)
            return d2 if isinstance(d2, dict) else {}

        def _first_str(*cands: Any) -> str:
            for c in cands:
                if isinstance(c, str) and c.strip():
                    return c.strip()
            return ""

        while has_more and len(comments) < limit:
            resp = await self._client.fetch_post_comments(post_id=post_id, end_cursor=next_cursor)
            payload = _unwrap_payload(resp)
            items = payload.get("comments", []) if isinstance(payload, dict) else []
            next_cursor = payload.get("next_cursor") if isinstance(payload, dict) else None
            has_more = bool(payload.get("has_more", False)) if isinstance(payload, dict) else False

            if not isinstance(items, list) or not items:
                break

            for item in items:
                if len(comments) >= limit:
                    break
                if not isinstance(item, dict):
                    continue
                u = item.get("user", {}) if isinstance(item.get("user"), dict) else {}
                parent = item.get("parent_comment", {}) if isinstance(item.get("parent_comment"), dict) else {}

                comment = XhsCommentModel(
                    comment_id=str(item.get("id", "") or ""),
                    note_id=post_id,
                    content=_first_str(item.get("content"), item.get("text"), item.get("body"), item.get("desc")),
                    publish_time=int(item.get("time", item.get("created_at", 0)) or 0),
                    ip_location=_first_str(item.get("ip_location"), item.get("ipLocation")),
                    user_id=_first_str(u.get("id"), u.get("user_id"), u.get("uid")),
                    user_nickname=_first_str(u.get("nickname"), u.get("name"), u.get("username")),
                    parent_comment_id=str(parent.get("id", "") or ""),
                )
                comments.append(comment.model_dump())

            if has_more and next_cursor and len(comments) < limit:
                await asyncio.sleep(self.request_delay)

        execution_time = (datetime.now() - start_time).total_seconds()
        return {
            "success": True,
            "post_id": post_id,
            "comments": comments,
            "total_count": len(comments),
            "execution_time": execution_time,
        }

    async def batch_fetch_post_comments(
        self,
        post_ids: List[str],
        comments_per_post: int = 20,
        delay_between_requests: float = 2.0,
    ) -> Dict[str, Any]:
        start_time = datetime.now()
        results: Dict[str, List[Dict[str, Any]]] = {}
        total_comments = 0

        for idx, pid in enumerate(post_ids):
            if idx > 0:
                await asyncio.sleep(delay_between_requests)
            r = await self.fetch_post_comments(post_id=pid, limit=comments_per_post)
            if isinstance(r, dict) and r.get("success"):
                cs = r.get("comments", [])
                results[pid] = cs
                total_comments += len(cs)
            else:
                results[pid] = []

        execution_time = (datetime.now() - start_time).total_seconds()
        return {"success": True, "results": results, "total_comments": total_comments, "execution_time": execution_time}

    async def ping(self) -> bool:
        return self._client is not None


async def create_threads_mcp_server(auth_token: str, request_delay: float = 1.0) -> ThreadsMCPServer:
    server = ThreadsMCPServer(auth_token=auth_token, request_delay=request_delay)
    await server.start()
    return server

