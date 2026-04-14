"""
JavBus API 客户端封装
基于 https://github.com/ovnrain/javbus-api
"""
import asyncio
import logging
import time
import aiohttp
from config import (
    JAVBUS_API_URL, JAVBUS_AUTH_TOKEN, DEFAULT_TYPE,
    MAGNET_SORT_BY, MAGNET_SORT_ORDER, MAX_CONCURRENT, MAX_PAGES,
    RATE_LIMIT
)

logger = logging.getLogger(__name__)


class _RateLimiter:
    """滑动窗口限速器：允许突发请求，保证每分钟不超过 N 次"""
    def __init__(self, max_per_minute: int):
        self._max = max_per_minute
        self._lock = asyncio.Lock()
        self._timestamps: list[float] = []

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            # 清理超过60秒的记录
            self._timestamps = [t for t in self._timestamps if now - t < 60]
            if len(self._timestamps) >= self._max:
                # 等到最早的请求过期
                wait = 60.0 - (now - self._timestamps[0]) + 0.1
                if wait > 0:
                    await asyncio.sleep(wait)
                now = time.monotonic()
                self._timestamps = [t for t in self._timestamps if now - t < 60]
            self._timestamps.append(time.monotonic())


# 全局限速器实例
_rate_limiter = _RateLimiter(RATE_LIMIT)


def _get_headers():
    """构建请求头（含可选认证 Token）"""
    headers = {}
    if JAVBUS_AUTH_TOKEN:
        headers['j-auth-token'] = JAVBUS_AUTH_TOKEN
    return headers


async def get_movie_detail(session, movie_id):
    """获取影片详情 /api/movies/{movieId}"""
    await _rate_limiter.acquire()
    url = f"{JAVBUS_API_URL}/api/movies/{movie_id}"
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                return await resp.json()
            logger.error("获取影片详情失败 %s: HTTP %s", movie_id, resp.status)
            return None
    except aiohttp.ClientError as e:
        logger.error("请求影片详情异常 %s: %s", movie_id, e)
        return None


async def get_magnets(session, movie_id, gid, uc):
    """获取影片磁力链接 /api/magnets/{movieId}"""
    await _rate_limiter.acquire()
    url = f"{JAVBUS_API_URL}/api/magnets/{movie_id}"
    params = {"gid": gid, "uc": uc}
    if MAGNET_SORT_BY:
        params["sortBy"] = MAGNET_SORT_BY
    if MAGNET_SORT_ORDER:
        params["sortOrder"] = MAGNET_SORT_ORDER
    try:
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                return await resp.json()
            logger.error("获取磁力链接失败 %s: HTTP %s", movie_id, resp.status)
            return None
    except aiohttp.ClientError as e:
        logger.error("请求磁力链接异常 %s: %s", movie_id, e)
        return None


async def get_star_info(session, star_id):
    """获取演员详情 /api/stars/{starId}"""
    await _rate_limiter.acquire()
    url = f"{JAVBUS_API_URL}/api/stars/{star_id}"
    params = {}
    if DEFAULT_TYPE:
        params["type"] = DEFAULT_TYPE
    try:
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                return await resp.json()
            logger.error("获取演员详情失败 %s: HTTP %s", star_id, resp.status)
            return None
    except aiohttp.ClientError as e:
        logger.error("请求演员详情异常 %s: %s", star_id, e)
        return None


async def _get_movie_ids_page(session, params, page):
    """获取单页影片列表，返回 (movie_ids, has_next_page)"""
    await _rate_limiter.acquire()
    params = {**params, "page": str(page)}
    url = f"{JAVBUS_API_URL}/api/movies"
    try:
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                movie_ids = [m['id'] for m in data.get('movies', [])]
                has_next = data.get('pagination', {}).get('hasNextPage', False)
                return movie_ids, has_next
            logger.error("获取影片列表失败: HTTP %s", resp.status)
            return [], False
    except aiohttp.ClientError as e:
        logger.error("请求影片列表异常: %s", e)
        return [], False


async def _search_movie_ids_page(session, keyword, page):
    """搜索影片单页，返回 (movie_ids, has_next_page)"""
    await _rate_limiter.acquire()
    url = f"{JAVBUS_API_URL}/api/movies/search"
    params = {"keyword": keyword, "page": str(page), "magnet": "exist"}
    if DEFAULT_TYPE:
        params["type"] = DEFAULT_TYPE
    try:
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                movie_ids = [m['id'] for m in data.get('movies', [])]
                has_next = data.get('pagination', {}).get('hasNextPage', False)
                return movie_ids, has_next
            logger.error("搜索影片失败: HTTP %s", resp.status)
            return [], False
    except aiohttp.ClientError as e:
        logger.error("搜索影片异常: %s", e)
        return [], False


async def get_all_movie_ids_by_filter(filter_type, filter_value):
    """按筛选条件获取所有影片 ID（自动翻页）"""
    params = {
        "filterType": filter_type,
        "filterValue": filter_value,
        "magnet": "exist"
    }
    if DEFAULT_TYPE:
        params["type"] = DEFAULT_TYPE

    all_ids = []
    headers = _get_headers()
    async with aiohttp.ClientSession(headers=headers) as session:
        page = 1
        while page <= MAX_PAGES:
            ids, has_next = await _get_movie_ids_page(session, params, page)
            all_ids.extend(ids)
            if not has_next or not ids:
                break
            page += 1
    return all_ids


async def search_all_movie_ids(keyword):
    """搜索获取所有影片 ID（自动翻页）"""
    all_ids = []
    headers = _get_headers()
    async with aiohttp.ClientSession(headers=headers) as session:
        page = 1
        while page <= MAX_PAGES:
            ids, has_next = await _search_movie_ids_page(session, keyword, page)
            all_ids.extend(ids)
            if not has_next or not ids:
                break
            page += 1
    return all_ids


async def _fetch_magnet_for_movie(session, movie_id, semaphore):
    """获取单个影片的最大磁力链接"""
    async with semaphore:
        detail = await get_movie_detail(session, movie_id)
        if not detail:
            return None
        gid = detail.get("gid", "")
        uc = detail.get("uc", "")
        if not gid:
            return None
        magnets = await get_magnets(session, movie_id, gid, uc)
        if not magnets:
            return None
        # 取最大的磁力链接
        max_magnet = max(magnets, key=lambda x: x.get('numberSize', 0) or 0)
        return {
            "id": movie_id,
            "title": detail.get("title", ""),
            "link": max_magnet.get("link", ""),
            "size": max_magnet.get("size", ""),
            "isHD": max_magnet.get("isHD", False),
            "hasSubtitle": max_magnet.get("hasSubtitle", False),
        }


class _Cancelled(Exception):
    """任务被取消"""
    pass


async def get_magnets_for_movie_list(movie_ids, progress_callback=None, cancel_event=None):
    """批量获取影片的最大磁力链接，支持进度回调和取消"""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    headers = _get_headers()
    total = len(movie_ids)
    results = []
    completed_count = 0

    async def _fetch_with_progress(session, movie_id):
        nonlocal completed_count
        if cancel_event and cancel_event.is_set():
            return None
        result = await _fetch_magnet_for_movie(session, movie_id, semaphore)
        completed_count += 1
        if cancel_event and cancel_event.is_set():
            return None
        if progress_callback and completed_count % max(1, total // 10) == 0:
            try:
                await progress_callback(completed_count, total)
            except Exception:
                pass
        return result

    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = [_fetch_with_progress(session, mid) for mid in movie_ids]
        completed = await asyncio.gather(*tasks)
        # 如果被取消，返回空列表
        if cancel_event and cancel_event.is_set():
            return []
        results = [r for r in completed if r is not None]
    return results


async def get_star_movie_list(star_id):
    """获取女优的影片列表（番号+基本信息，不获取磁力）"""
    params = {
        "filterType": "star",
        "filterValue": star_id,
        "magnet": "exist"
    }
    if DEFAULT_TYPE:
        params["type"] = DEFAULT_TYPE

    all_movies = []
    headers = _get_headers()
    async with aiohttp.ClientSession(headers=headers) as session:
        page = 1
        while page <= MAX_PAGES:
            await _rate_limiter.acquire()
            req_params = {**params, "page": str(page)}
            url = f"{JAVBUS_API_URL}/api/movies"
            try:
                async with session.get(url, params=req_params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        movies = data.get('movies', [])
                        has_next = data.get('pagination', {}).get('hasNextPage', False)
                        for m in movies:
                            all_movies.append({
                                "id": m.get("id", ""),
                                "title": m.get("title", ""),
                                "date": m.get("date", ""),
                                "img": m.get("img", ""),
                            })
                        if not has_next or not movies:
                            break
                    else:
                        logger.error("获取女优影片列表失败: HTTP %s", resp.status)
                        break
            except aiohttp.ClientError as e:
                logger.error("请求女优影片列表异常: %s", e)
                break
            page += 1
    return all_movies


async def get_single_movie_magnet(movie_id):
    """获取单个影片的详情和磁力链接"""
    headers = _get_headers()
    async with aiohttp.ClientSession(headers=headers) as session:
        detail = await get_movie_detail(session, movie_id)
        if not detail:
            return None
        gid = detail.get("gid", "")
        uc = detail.get("uc", "")
        if not gid:
            return {"detail": detail, "magnets": []}
        magnets = await get_magnets(session, movie_id, gid, uc)
        return {"detail": detail, "magnets": magnets or []}