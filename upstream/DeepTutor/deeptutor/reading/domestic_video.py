"""Public domestic-video source cards and official playback descriptors.

Local integration, 2026-10-14. This module fetches only bounded public HTML.
It does not download media, access account cookies or infer a transcript from
page descriptions. A source card is independent of spoken-content coverage.
"""
from __future__ import annotations

from dataclasses import dataclass
import base64
from html.parser import HTMLParser
import json
import re
import time
from typing import Any
from urllib.parse import urljoin, urlparse, unquote
import uuid

import httpx
from deeptutor.reading.models import ReadingError

MAX_PAGE_BYTES = 4 * 1024 * 1024
USER_AGENT = "DeepSteam/ImmersiveReading"
_RULES = (
    ("tencent", {"v.qq.com", "m.v.qq.com"}, r"/x/(?:page/|cover/[A-Za-z0-9]+/)([A-Za-z0-9]+)\.html"),
    ("iqiyi", {"www.iqiyi.com", "iqiyi.com", "m.iqiyi.com"}, r"/v_([A-Za-z0-9]+)\.html"),
    ("youku", {"v.youku.com"}, r"/v_show/id_([A-Za-z0-9=]+)(?:\.html)?"),
    ("mango", {"www.mgtv.com", "w.mgtv.com", "m.mgtv.com"}, r"/(?:b/\d+|s)/(\d+)\.html"),
    ("douyin", {"www.douyin.com", "douyin.com"}, r"/video/(\d{10,})"),
    ("acfun", {"www.acfun.cn", "acfun.cn"}, r"/v/(ac\d+(?:_\d+)?)"),
    ("cctv", {"tv.cctv.com"}, r"/\d{4}/\d{2}/\d{2}/(VIDE[A-Za-z0-9]+)\.shtml"),
    ("xigua", {"www.ixigua.com", "ixigua.com", "m.ixigua.com"}, r"/(?:video/)?(\d{10,})"),
    ("kuaishou", {"www.kuaishou.com", "kuaishou.com"}, r"/short-video/([A-Za-z0-9]+)"),
)


@dataclass(frozen=True, slots=True)
class DomesticVideoSource:
    platform: str
    video_id: str
    source_url: str
    embed_url: str = ""


@dataclass(frozen=True, slots=True)
class DomesticVideoMedia:
    platform: str
    title: str
    cover_url: str = ""
    duration_seconds: float = 0.0
    metadata_status: str = "available"


def domestic_video_source(value: str) -> DomesticVideoSource | None:
    try:
        parsed = urlparse(value)
        if (parsed.scheme not in {"http", "https"} or parsed.username or parsed.password
                or parsed.port not in {None, 80, 443}):
            return None
        host = (parsed.hostname or "").lower().rstrip(".")
        for platform, hosts, pattern in _RULES:
            if host not in hosts:
                continue
            match = re.fullmatch(pattern + r"/?", unquote(parsed.path))
            if not match:
                return None
            video_id = match.group(1)
            embed = ""
            if platform == "tencent":
                embed = f"https://v.qq.com/txp/iframe/player.html?vid={video_id}&auto=0"
            elif platform == "youku":
                embed = f"https://player.youku.com/embed/{video_id}"
            elif platform == "acfun" and "_" not in video_id:
                embed = f"https://www.acfun.cn/player/{video_id}"
            return DomesticVideoSource(platform, video_id, value, embed)
    except ValueError:
        return None
    return None


class _PageMetadata(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self.json_ld: list[Any] = []
        self._in_title = False
        self._in_json = False
        self._json = ""

    def handle_starttag(self, tag, attrs):
        row = dict(attrs)
        if tag == "meta":
            key = str(row.get("property") or row.get("name") or "").lower()
            if key and row.get("content"):
                self.meta[key] = str(row["content"])[:4000]
        elif tag == "title":
            self._in_title = True
        elif tag == "script" and row.get("type") == "application/ld+json":
            self._in_json = True
            self._json = ""

    def handle_data(self, data):
        if self._in_title:
            self.title += data[:2000]
        if self._in_json and len(self._json) < 512_000:
            self._json += data

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "script" and self._in_json:
            self._in_json = False
            try:
                self.json_ld.append(json.loads(self._json))
            except ValueError:
                pass


def _video_object(values):
    for item in values:
        if isinstance(item, list):
            found = _video_object(item)
            if found:
                return found
        elif isinstance(item, dict):
            if item.get("@type") == "VideoObject":
                return item
            found = _video_object(item.get("@graph") or [])
            if found:
                return found
    return {}


def parse_domestic_metadata(html: str, source: DomesticVideoSource) -> DomesticVideoMedia:
    parser = _PageMetadata()
    parser.feed(html)
    video = _video_object(parser.json_ld)
    title = str(video.get("name") or parser.meta.get("og:title") or parser.title).strip()
    title = re.sub(r"\s+", " ", title)[:1000]
    generic = {
        "抖音-记录美好生活", "抖音", "快手", "快手，拥抱每一种生活", "西瓜视频", "爱奇艺",
        "腾讯视频", "优酷", "芒果TV", "403 Forbidden", "Access Denied", "Just a moment...",
    }
    compact_title = re.sub(r"[\s\-–—，,。.]", "", title).lower()
    generic_response = (
        compact_title.startswith(("爱奇艺在线视频网站", "腾讯视频矩形备份")) or
        compact_title in {"抖音记录美好生活", "快手拥抱每一种生活", "西瓜视频"}
    )
    challenge = any(text.lower() in title.lower() for text in
                    ("captcha", "验证", "access denied", "security check", "404", "登录", "sign in"))
    if not title or title in generic or challenge or generic_response:
        raise ReadingError(f"{source.platform} public video metadata is not available in this response")
    cover = video.get("thumbnailUrl") or parser.meta.get("og:image") or ""
    if isinstance(cover, list):
        cover = next((value for value in cover if isinstance(value, str)), "")
    cover = urljoin(source.source_url, str(cover)) if cover else ""
    cover_parsed = urlparse(cover)
    if cover and (cover_parsed.scheme not in {"http", "https"} or cover_parsed.username):
        cover = ""
    raw_duration = video.get("duration") or parser.meta.get("video:duration") or 0
    duration = 0.0
    try:
        duration = max(0.0, float(raw_duration))
    except (ValueError, TypeError):
        match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", str(raw_duration))
        if match:
            hours, minutes, seconds = (float(value or 0) for value in match.groups())
            duration = hours * 3600 + minutes * 60 + seconds
    return DomesticVideoMedia(source.platform, title, cover, duration)


async def load_domestic_video(url: str) -> DomesticVideoMedia:
    """A dynamic site may still play when its initial HTML has no metadata.

    Keep a source-only card so the desktop's official browser can load it.
    This is not playback or transcript evidence.
    """
    source = domestic_video_source(url)
    if source is None:
        raise ReadingError("Unsupported domestic video URL")
    try:
        return await _load_domestic_video(url)
    except (ReadingError, httpx.HTTPError):
        if source.platform not in {"youku", "iqiyi", "douyin", "xigua", "kuaishou"}:
            raise
        labels = {"youku": "Youku", "iqiyi": "iQIYI", "douyin": "Douyin", "xigua": "Xigua Video", "kuaishou": "Kuaishou"}
        return DomesticVideoMedia(source.platform, f"{labels[source.platform]} · {source.video_id}", metadata_status="awaiting_official_player")


async def _load_domestic_video(url: str) -> DomesticVideoMedia:
    source = domestic_video_source(url)
    if source is None:
        raise ReadingError("Unsupported domestic video URL")
    # Use original public pages and same-family redirects only. No media
    # extraction, proxy rotation, browser cookies or authentication workaround.
    async with httpx.AsyncClient(timeout=8, follow_redirects=False,
                                 headers={"User-Agent": USER_AGENT, "Accept": "text/html"}) as client:
        if source.platform in {"tencent", "mango"}:
            return await _public_api_metadata(client, source)
        target = source.source_url
        for _ in range(4):
            async with client.stream("GET", target) as response:
                if response.is_redirect:
                    next_url = urljoin(target, response.headers.get("location", ""))
                    parsed = urlparse(next_url)
                    next_source = domestic_video_source(next_url)
                    if (next_source is None or next_source.platform != source.platform
                            or parsed.username or parsed.port not in {None, 80, 443}):
                        raise ReadingError("Video page redirected outside its approved public source")
                    target = next_url
                    continue
                response.raise_for_status()
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_PAGE_BYTES:
                        raise ReadingError("Video metadata page exceeded the size limit")
                encoding = response.encoding or "utf-8"
                return parse_domestic_metadata(bytes(content).decode(encoding, errors="replace"), source)
        raise ReadingError("Too many video page redirects")


async def _public_api_metadata(client, source):
    """Read public title/duration only, never the response's stream URLs.

    The MGTV public-client request convention follows the maintained yt-dlp
    MGTV extractor (Unlicense): github.com/yt-dlp/yt-dlp, mgtv.py. Its generated
    request identifier is ephemeral and does not contain an account cookie.
    """
    if source.platform == "tencent":
        endpoint = "https://vv.video.qq.com/getinfo"
        params = {"vids": source.video_id, "otype": "json", "platform": "101001"}
    else:
        ticket = base64.urlsafe_b64encode(
            f"did={uuid.uuid4()}|pno=1030|ver=0.3.0301|clit={int(time.time())}".encode()
        )[::-1].decode()
        endpoint = "https://pcweb.api.mgtv.com/player/video"
        params = {"tk2": ticket, "video_id": source.video_id, "type": "pch5"}
    async with client.stream("GET", endpoint, params=params, headers={"Accept": "*/*"}) as response:
        response.raise_for_status()
        content = bytearray()
        async for chunk in response.aiter_bytes():
            content.extend(chunk)
            if len(content) > MAX_PAGE_BYTES:
                raise ReadingError("Video metadata response exceeded the size limit")
        text = bytes(content).decode("utf-8", errors="replace").strip()
    if text.startswith("QZOutputJson="):
        text = text.removeprefix("QZOutputJson=").rstrip("; \r\n")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ReadingError("Video metadata response is not an object")
    if source.platform == "tencent":
        rows = (payload.get("vl") or {}).get("vi") or []
        info = next((row for row in rows if isinstance(row, dict)
                     and row.get("vid") == source.video_id), {})
        title = str(info.get("ti") or "").strip()
        raw_duration = info.get("td") or 0
        cover = ""
    else:
        if payload.get("code") != 200:
            raise ReadingError("MGTV public video metadata is not available")
        info = (payload.get("data") or {}).get("info") or {}
        title = str(info.get("title") or "").strip()
        raw_duration = info.get("duration") or 0
        cover = str(info.get("thumb") or "")
        if cover.startswith("http://"):
            cover = "https://" + cover.removeprefix("http://")
    if not title:
        raise ReadingError(f"{source.platform} returned no matching video title")
    try:
        duration = max(0.0, float(raw_duration))
    except (ValueError, TypeError):
        duration = 0.0
    if cover and urlparse(cover).scheme != "https":
        cover = ""
    return DomesticVideoMedia(source.platform, title[:1000], cover, duration)
