from __future__ import annotations

import asyncio
import copy
import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from curl_cffi.requests import Session as BrowserSession
from lxml import etree, html

from nalmai.models import NormalizedScore, WechatChartDetail, WechatPlayerProfile
from nalmai.wahlap_html import (
    parse_current_collection_item,
    parse_music_detail,
    parse_player_profile,
    parse_score_list,
)

from .local_api import NalmaiLocalApiClient


AUTHORIZE_URL = "https://tgk-wcaime.wahlap.com/wc_auth/oauth/authorize/maimai-dx"
CALLBACK_URL = "https://tgk-wcaime.wahlap.com/wc_auth/oauth/callback/maimai-dx"
CALLBACK_PATH = "/wc_auth/oauth/callback/maimai-dx"
CALLBACK_HOST = "tgk-wcaime.wahlap.com"
REQUIRED_CALLBACK_KEYS = ("r", "t", "code", "state")
SCORE_LIST_URL = (
    "https://maimai.wahlap.com/maimai-mobile/record/musicGenre/search/"
    "?genre=99&diff={difficulty}"
)
PROFILE_PAGE_URLS = (
    (
        "player",
        "https://maimai.wahlap.com/maimai-mobile/friend/userFriendCode/",
    ),
    (
        "icon-collection",
        "https://maimai.wahlap.com/maimai-mobile/collection/",
    ),
    (
        "nameplate-collection",
        "https://maimai.wahlap.com/maimai-mobile/collection/nameplate/",
    ),
    (
        "frame-collection",
        "https://maimai.wahlap.com/maimai-mobile/collection/frame/",
    ),
    (
        "partner-collection",
        "https://maimai.wahlap.com/maimai-mobile/collection/partner/",
    ),
)
SHARED_COLLECTION_PAGES = (
    ("icon-collection", "icon"),
    ("nameplate-collection", "nameplate"),
    ("frame-collection", "frame"),
    ("partner-collection", "partner"),
)
DETAIL_PATH = "/maimai-mobile/record/musicDetail/"
WECHAT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/81.0.4044.138 Safari/537.36 "
    "NetType/WIFI MicroMessenger/7.0.20.1781(0x6700143B) "
    "WindowsWechat(0x6307001e)"
)
SCORE_CARD_XPATH = (
    "//div[contains(@class, 'w_450') and contains(@class, 'm_15') "
    "and contains(@class, 'p_r') and contains(@class, 'f_0')]"
)
_LONG_NUMBER = re.compile(r"(?<!\d)\d{8,}(?!\d)")
_TOKEN_ATTRIBUTE = re.compile(r"^[A-Za-z0-9_+/=.-]{24,}$")
_DROP_ELEMENTS = ("script", "style", "iframe", "object", "embed")
_URL_ATTRIBUTES = ("action", "href", "src")
DETAIL_REQUEST_INTERVAL_SECONDS = 1.0
DETAIL_RETRY_DELAYS_SECONDS = (1.0, 2.0, 4.0)
DETAIL_RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
PROFILE_ASSET_MAX_BYTES = 5 * 1024 * 1024
PROFILE_ASSET_EXTENSIONS = {
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/svg+xml": ".svg",
    "image/webp": ".webp",
}


class CaptureError(RuntimeError):
    """Public-safe collector error with no credential values."""


@dataclass(frozen=True, slots=True)
class FormRequest:
    method: str
    url: str
    fields: tuple[tuple[str, str], ...]
    referer: str = ""


@dataclass(frozen=True, slots=True)
class CaptureBundle:
    directory: Path
    archive: Path
    score_page_count: int
    detail_page_count: int
    profile_page_count: int
    shared_asset_count: int = 0


@dataclass(frozen=True, slots=True)
class IntegratedCaptureResult:
    bundle: CaptureBundle
    score_count: int
    requested_detail_count: int
    saved_detail_count: int
    missing_detail_count: int


@dataclass(frozen=True, slots=True)
class ProfileImageReference:
    url: str
    source_path: str
    css_class: str
    parent_class: str


def validate_callback_params(params: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key in REQUIRED_CALLBACK_KEYS:
        value = params.get(key)
        if not isinstance(value, str) or not value:
            raise CaptureError("微信授权回调缺少必要参数，请重新生成链接。")
        result[key] = value
    return result


def authorization_url_from_location(location: str) -> str:
    """Change only the nested OAuth redirect URI from HTTPS to HTTP."""
    outer = urlsplit(location)
    query = parse_qsl(outer.query, keep_blank_values=True)
    updated: list[tuple[str, str]] = []
    changed = False
    for key, value in query:
        if key == "redirect_uri":
            redirect = urlsplit(value)
            if redirect.scheme != "https":
                raise CaptureError("微信授权地址中的回调协议不是预期的 HTTPS。")
            value = urlunsplit(
                ("http", redirect.netloc, redirect.path, redirect.query, redirect.fragment)
            )
            changed = True
        updated.append((key, value))
    if not changed:
        raise CaptureError("微信授权地址中没有 redirect_uri。")
    return urlunsplit(
        (outer.scheme, outer.netloc, outer.path, urlencode(updated), outer.fragment)
    )


async def build_authorization_url(client: httpx.AsyncClient) -> str:
    response = await client.get(AUTHORIZE_URL, follow_redirects=False)
    location = response.headers.get("location")
    if response.status_code not in range(300, 400) or not location:
        raise CaptureError("华立微信授权入口没有返回预期的跳转。")
    return authorization_url_from_location(location)


async def exchange_callback(
    client: httpx.AsyncClient, params: dict[str, str]
) -> httpx.Cookies:
    clean_params = validate_callback_params(params)
    headers = {
        "User-Agent": WECHAT_USER_AGENT,
        "Host": CALLBACK_HOST,
        "Upgrade-Insecure-Requests": "1",
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9"
        ),
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    response = await client.get(
        CALLBACK_URL,
        params=clean_params,
        headers=headers,
        follow_redirects=False,
    )
    location = response.headers.get("location")
    if response.status_code not in range(300, 400) or not location:
        location_state = "有" if location else "无"
        raise CaptureError(
            "微信授权参数未被华立接受"
            f"（HTTP {response.status_code}，跳转头：{location_state}）"
        )

    next_url = urljoin(str(response.url), location)
    next_response = await client.get(
        next_url,
        headers={"User-Agent": WECHAT_USER_AGENT},
        follow_redirects=True,
    )
    cookies = httpx.Cookies(response.cookies)
    cookies.update(next_response.cookies)
    if not list(cookies.jar):
        raise CaptureError(
            "微信授权完成但没有取得舞萌网页会话"
            f"（后续 HTTP {next_response.status_code}）"
        )
    return cookies


def extract_score_forms(page: str, page_url: str) -> list[FormRequest]:
    root = html.fromstring(page)
    requests: list[FormRequest] = []
    for card in root.xpath(SCORE_CARD_XPATH):
        forms = card.xpath(".//form")
        if not forms:
            continue
        form = forms[0]
        method = form.get("method", "get").upper()
        if method not in {"GET", "POST"}:
            continue
        declared_target = urljoin(page_url, form.get("action", ""))
        parsed = urlsplit(declared_target)
        if parsed.path != DETAIL_PATH:
            continue
        target = urlunsplit(
            ("https", "maimai.wahlap.com", parsed.path, parsed.query, "")
        )
        fields: list[tuple[str, str]] = []
        for element in form.xpath(".//input[@name]"):
            name = element.get("name")
            if name:
                fields.append((name, element.get("value", "")))
        requests.append(FormRequest(method, target, tuple(fields), page_url))
    return requests


def _strip_url_value(value: str) -> str:
    parsed = urlsplit(value)
    if not parsed.scheme and not parsed.netloc:
        return parsed.path
    return parsed.path or "/"


def _replace_secrets(value: str, secrets: Iterable[str]) -> str:
    cleaned = value
    for secret in secrets:
        if secret:
            cleaned = cleaned.replace(secret, "[REDACTED]")
    return _LONG_NUMBER.sub("[REDACTED_NUMBER]", cleaned)


def _sanitize_tree(root: etree._Element, secrets: set[str]) -> None:
    for tag in _DROP_ELEMENTS:
        for element in root.xpath(f".//{tag}"):
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)

    for comment in root.xpath(".//comment()"):
        parent = comment.getparent()
        if parent is not None:
            parent.remove(comment)

    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        if element.tag.lower() == "input":
            if "value" in element.attrib:
                element.set("value", "[REDACTED]")

        for name in list(element.attrib):
            value = element.attrib[name]
            lowered = name.casefold()
            if lowered.startswith("on"):
                del element.attrib[name]
                continue
            if lowered in _URL_ATTRIBUTES:
                element.attrib[name] = _strip_url_value(value)
                continue
            if lowered not in {"class", "id", "name", "type", "method"} and (
                _TOKEN_ATTRIBUTE.fullmatch(value) is not None
            ):
                secrets.add(value)
                element.attrib[name] = "[REDACTED]"

    for element in root.iter():
        if element.text:
            element.text = _replace_secrets(element.text, secrets)
        if element.tail:
            element.tail = _replace_secrets(element.tail, secrets)
        for name, value in list(element.attrib.items()):
            element.attrib[name] = _replace_secrets(value, secrets)


def sanitize_score_list(page: str, secrets: Iterable[str]) -> tuple[str, int]:
    source = html.fromstring(page)
    cards = source.xpath(SCORE_CARD_XPATH)
    output = html.Element("html")
    body = etree.SubElement(output, "body")
    for card in cards:
        body.append(copy.deepcopy(card))
    secret_set = {value for value in secrets if value}
    _sanitize_tree(output, secret_set)
    return html.tostring(output, encoding="unicode", pretty_print=True), len(cards)


def sanitize_detail_page(page: str, secrets: Iterable[str]) -> str:
    root = html.fromstring(page)
    secret_set = {value for value in secrets if value}
    _sanitize_tree(root, secret_set)
    return html.tostring(root, encoding="unicode", pretty_print=True)


def profile_image_references(page: str, page_url: str) -> tuple[ProfileImageReference, ...]:
    root = html.fromstring(page)
    result: list[ProfileImageReference] = []
    seen: set[str] = set()
    for element in root.xpath("//img[@src]"):
        raw_src = element.get("src", "")
        if not raw_src:
            continue
        url = urljoin(page_url, raw_src)
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "maimai.wahlap.com":
            continue
        normalized = urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, ""))
        if normalized in seen:
            continue
        seen.add(normalized)
        parent = element.getparent()
        result.append(
            ProfileImageReference(
                url=normalized,
                source_path=parsed.path,
                css_class=element.get("class", ""),
                parent_class=(parent.get("class", "") if parent is not None else ""),
            )
        )
    return tuple(result)


def collection_image_references(
    page: str,
    page_url: str,
) -> tuple[ProfileImageReference, ...]:
    """Read collection artwork from the page's exact lazy-loaded image nodes."""
    root = html.fromstring(page)
    result: list[ProfileImageReference] = []
    seen: set[str] = set()
    for element in root.xpath("//img[@loading='lazy' and @src]"):
        raw_src = element.get("src", "")
        if not raw_src:
            continue
        url = urljoin(page_url, raw_src)
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "maimai.wahlap.com":
            continue
        if not parsed.path.startswith("/maimai-mobile/img/"):
            continue
        filename = Path(parsed.path).name
        if (
            not filename
            or filename != Path(filename).name
            or not re.fullmatch(r"[A-Za-z0-9._-]+", filename)
        ):
            continue
        normalized = urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, ""))
        if normalized in seen:
            continue
        seen.add(normalized)
        parent = element.getparent()
        result.append(
            ProfileImageReference(
                url=normalized,
                source_path=parsed.path,
                css_class=element.get("class", ""),
                parent_class=(parent.get("class", "") if parent is not None else ""),
            )
        )
    return tuple(result)


async def _sync_shared_collection_assets(
    client: httpx.AsyncClient,
    raw_pages: dict[str, str],
    shared_asset_root: Path,
    manifest: dict[str, object],
) -> int:
    shared_asset_root.mkdir(parents=True, exist_ok=True)
    requests: list[tuple[str, ProfileImageReference]] = []
    for page_name, category in SHARED_COLLECTION_PAGES:
        page = raw_pages[page_name]
        page_url = dict(PROFILE_PAGE_URLS)[page_name]
        requests.extend(
            (category, reference)
            for reference in collection_image_references(page, page_url)
        )

    semaphore = asyncio.Semaphore(1)

    async def download(
        category: str,
        reference: ProfileImageReference,
    ) -> tuple[dict[str, str] | None, dict[str, str] | None]:
        category_root = shared_asset_root / category
        category_root.mkdir(parents=True, exist_ok=True)
        filename = Path(urlsplit(reference.url).path).name
        target = category_root / filename
        if target.is_file() and target.stat().st_size > 0:
            return (
                {
                    "category": category,
                    "file": f"{category}/{filename}",
                    "source_path": reference.source_path,
                },
                None,
            )
        try:
            async with semaphore:
                try:
                    response = await client.get(reference.url, follow_redirects=True)
                finally:
                    await asyncio.sleep(0.5)
        except httpx.HTTPError:
            return (
                None,
                {
                    "category": category,
                    "file": f"{category}/{filename}",
                    "source_path": reference.source_path,
                    "reason": "request_failed",
                },
            )
        content_type = response.headers.get("content-type", "").split(";", 1)[0].casefold()
        expected_extension = PROFILE_ASSET_EXTENSIONS.get(content_type)
        if (
            response.status_code != 200
            or expected_extension is None
            or Path(filename).suffix.casefold() != expected_extension
            or not response.content
            or len(response.content) > PROFILE_ASSET_MAX_BYTES
        ):
            return (
                None,
                {
                    "category": category,
                    "file": f"{category}/{filename}",
                    "source_path": reference.source_path,
                    "reason": "invalid_response",
                },
            )
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(response.content)
        temporary.replace(target)
        return (
            {
                "category": category,
                "file": f"{category}/{filename}",
                "source_path": reference.source_path,
            },
            None,
        )

    results = await asyncio.gather(
        *(download(category, reference) for category, reference in requests)
    )
    downloaded = [item for item, _ in results if item is not None]
    skipped = [item for _, item in results if item is not None]
    downloaded.sort(key=lambda item: (item["category"], item["file"]))
    skipped.sort(key=lambda item: (item["category"], item["file"]))
    manifest["shared_profile_assets"] = downloaded
    manifest["shared_profile_assets_skipped"] = skipped
    shared_manifest = {
        "format": "nalmai-shared-profile-assets-v1",
        "source": "maimai.wahlap.com authorized collection pages",
        "redistribution_granted": False,
        "assets": downloaded,
        "skipped": skipped,
    }
    (shared_asset_root / "manifest.json").write_text(
        json.dumps(shared_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return len(downloaded)


async def _capture_profile_pages(
    client: httpx.AsyncClient,
    directory: Path,
    manifest: dict[str, object],
    secrets: set[str],
    shared_asset_root: Path | None = None,
) -> tuple[int, WechatPlayerProfile]:
    profile_pages: list[dict[str, object]] = []
    profile_assets: list[dict[str, str]] = []
    raw_pages: dict[str, str] = {}
    for page_name, url in PROFILE_PAGE_URLS:
        response = await client.get(url, follow_redirects=False)
        if response.status_code == 302:
            raise CaptureError("舞萌网页会话在读取玩家资料时失效。")
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type.casefold():
            raise CaptureError(f"玩家资料页面 {page_name} 没有返回 HTML。")
        secrets.update(cookie.value for cookie in client.cookies.jar)
        sanitized = sanitize_detail_page(response.text, secrets)
        filename = f"profile-{page_name}.sanitized.html"
        (directory / filename).write_text(
            sanitized,
            encoding="utf-8",
            newline="\n",
        )
        profile_pages.append({"name": page_name, "file": filename})
        raw_pages[page_name] = response.text

    player = parse_player_profile(raw_pages["player"])
    avatar_item = parse_current_collection_item(
        raw_pages["icon-collection"], "Icon"
    )
    nameplate_item = parse_current_collection_item(
        raw_pages["nameplate-collection"], "NamePlate"
    )
    frame_item = parse_current_collection_item(
        raw_pages["frame-collection"], "Frame"
    )
    if (
        player is None
        or avatar_item is None
        or nameplate_item is None
        or frame_item is None
    ):
        raise CaptureError("舞萌玩家资料页缺少当前装备资料。")

    if shared_asset_root is not None:
        await _sync_shared_collection_assets(
            client,
            raw_pages,
            shared_asset_root,
            manifest,
        )

    requested_assets = (
        ("version-logo", player.version_logo_path),
        ("avatar", player.avatar_path),
        ("rating-base", player.rating_base_path),
        ("course-rank", player.course_rank_path),
        ("class-rank", player.class_rank_path),
        ("nameplate", nameplate_item.image_path),
        ("frame", frame_item.image_path),
    )

    async def download(role: str, source_path: str) -> tuple[str, bytes, dict[str, str]]:
        url = urljoin("https://maimai.wahlap.com/", source_path)
        response = await client.get(url, follow_redirects=True)
        content_type = response.headers.get("content-type", "").split(";", 1)[0].casefold()
        extension = PROFILE_ASSET_EXTENSIONS.get(content_type)
        if (
            response.status_code != 200
            or extension is None
            or not response.content
            or len(response.content) > PROFILE_ASSET_MAX_BYTES
        ):
            raise CaptureError(f"舞萌玩家资料图片读取失败：{role}。")
        filename = f"profile-{role}{extension}"
        (directory / filename).write_bytes(response.content)
        return (
            role,
            response.content,
            {"role": role, "file": filename, "source_path": source_path},
        )

    downloaded = await asyncio.gather(
        *(download(role, source_path) for role, source_path in requested_assets)
    )
    assets = {role: content for role, content, _ in downloaded}
    profile_assets.extend(item for _, _, item in downloaded)
    manifest["profile_pages"] = profile_pages
    manifest["profile_assets"] = profile_assets
    return (
        len(profile_pages),
        WechatPlayerProfile(
            player_name=player.player_name,
            rating=player.rating,
            title_text=player.title_text,
            title_rarity=player.title_rarity,
            star_count=player.star_count,
            avatar_name=avatar_item.name,
            nameplate_name=nameplate_item.name,
            nameplate_description=nameplate_item.description,
            frame_name=frame_item.name,
            frame_description=frame_item.description,
            version_logo=assets["version-logo"],
            avatar=assets["avatar"],
            rating_base=assets["rating-base"],
            course_rank=assets["course-rank"],
            class_rank=assets["class-rank"],
            nameplate=assets["nameplate"],
            frame=assets["frame"],
        ),
    )


async def _fetch_detail(
    client: httpx.AsyncClient,
    request: FormRequest,
) -> httpx.Response:
    headers = {
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/webp,image/apng,*/*;q=0.8"
        ),
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
    }
    if request.referer:
        headers["Referer"] = request.referer
    if request.method == "POST":
        return await client.post(
            request.url,
            data=list(request.fields),
            headers=headers,
            follow_redirects=True,
        )
    return await client.get(
        request.url,
        params=list(request.fields),
        headers=headers,
        follow_redirects=True,
    )


async def _fetch_detail_with_retry(
    client: httpx.AsyncClient,
    request: FormRequest,
) -> httpx.Response:
    for attempt in range(len(DETAIL_RETRY_DELAYS_SECONDS) + 1):
        response = await _fetch_detail(client, request)
        if (
            response.status_code not in DETAIL_RETRY_STATUS_CODES
            or attempt == len(DETAIL_RETRY_DELAYS_SECONDS)
        ):
            return response
        await asyncio.sleep(DETAIL_RETRY_DELAYS_SECONDS[attempt])
    raise AssertionError("detail retry loop must return a response")


def _copy_httpx_cookies_to_browser(
    source: httpx.Cookies,
    target: BrowserSession,
) -> None:
    for cookie in source.jar:
        target.cookies.set(
            cookie.name,
            cookie.value,
            domain=cookie.domain,
            path=cookie.path or "/",
        )


def _browser_cookie_values(session: BrowserSession) -> list[str]:
    return [cookie.value for cookie in session.cookies.jar]


def _fetch_detail_in_browser(
    session: BrowserSession,
    request: FormRequest,
):
    headers = {"Referer": request.referer} if request.referer else None
    if request.method == "POST":
        return session.post(
            request.url,
            data=list(request.fields),
            headers=headers,
            allow_redirects=True,
            timeout=30,
        )
    return session.get(
        request.url,
        params=list(request.fields),
        headers=headers,
        allow_redirects=True,
        timeout=30,
    )


async def _fetch_detail_in_browser_with_retry(
    session: BrowserSession,
    request: FormRequest,
):
    for attempt in range(len(DETAIL_RETRY_DELAYS_SECONDS) + 1):
        response = await asyncio.to_thread(
            _fetch_detail_in_browser,
            session,
            request,
        )
        if (
            response.status_code not in DETAIL_RETRY_STATUS_CODES
            or attempt == len(DETAIL_RETRY_DELAYS_SECONDS)
        ):
            return response
        await asyncio.sleep(DETAIL_RETRY_DELAYS_SECONDS[attempt])
    raise AssertionError("browser detail retry loop must return a response")


async def collect_bundle(
    params: dict[str, str],
    output_root: Path,
    *,
    detail_limit: int = 5,
    shared_asset_root: Path | None = None,
) -> CaptureBundle:
    clean_params = validate_callback_params(params)
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": WECHAT_USER_AGENT},
    ) as client:
        cookies = await exchange_callback(client, clean_params)
        cookie_values = [cookie.value for cookie in cookies.jar]
        secrets = set(clean_params.values()) | set(cookie_values)

        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        directory = output_root / timestamp
        directory.mkdir(parents=True, exist_ok=False)

        manifest: dict[str, object] = {
            "format": "nalmai-wechat-capture-v1",
            "created_at_utc": timestamp,
            "raw_credentials_stored": False,
            "score_pages": [],
            "detail_pages": [],
            "profile_pages": [],
            "profile_assets": [],
        }
        profile_page_count, _player_profile = await _capture_profile_pages(
            client,
            directory,
            manifest,
            secrets,
            shared_asset_root,
        )
        detail_requests: list[FormRequest] = []
        score_page_count = 0

        for difficulty in range(5):
            url = SCORE_LIST_URL.format(difficulty=difficulty)
            response = await client.get(url, follow_redirects=False)
            if response.status_code == 302:
                raise CaptureError("舞萌网页会话在采集过程中失效。")
            response.raise_for_status()
            secrets.update(cookie.value for cookie in client.cookies.jar)
            sanitized, card_count = sanitize_score_list(response.text, secrets)
            filename = f"score-list-diff-{difficulty}.sanitized.html"
            (directory / filename).write_text(sanitized, encoding="utf-8", newline="\n")
            score_page_count += 1
            manifest["score_pages"].append(
                {"difficulty": difficulty, "file": filename, "score_cards": card_count}
            )
            detail_requests.extend(extract_score_forms(response.text, str(response.url)))

        seen: set[tuple[str, str, tuple[tuple[str, str], ...]]] = set()
        detail_page_count = 0
        for request in detail_requests:
            identity = (request.method, request.url, request.fields)
            if identity in seen:
                continue
            seen.add(identity)
            if detail_page_count >= detail_limit:
                break
            response = await _fetch_detail(client, request)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "html" not in content_type.casefold():
                continue
            request_secrets = secrets | {value for _, value in request.fields if value}
            request_secrets.update(
                cookie.value for cookie in client.cookies.jar
            )
            sanitized = sanitize_detail_page(response.text, request_secrets)
            filename = f"music-detail-{detail_page_count + 1}.sanitized.html"
            (directory / filename).write_text(sanitized, encoding="utf-8", newline="\n")
            manifest["detail_pages"].append(
                {"file": filename, "http_method": request.method}
            )
            detail_page_count += 1

        manifest_path = directory / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        archive = output_root / f"nalmai-wechat-capture-{timestamp}.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(directory.iterdir()):
                bundle.write(path, arcname=path.name)
        return CaptureBundle(
            directory=directory,
            archive=archive,
            score_page_count=score_page_count,
            detail_page_count=detail_page_count,
            profile_page_count=profile_page_count,
            shared_asset_count=len(manifest.get("shared_profile_assets", [])),
        )


def _score_request_map(
    page: str, page_url: str
) -> dict[tuple[str, str, int], FormRequest]:
    root = html.fromstring(page)
    result: dict[tuple[str, str, int], FormRequest] = {}
    for card in root.xpath(SCORE_CARD_XPATH):
        card_page = "<html><body>" + html.tostring(
            card, encoding="unicode"
        ) + "</body></html>"
        scores = parse_score_list(card_page)
        requests = extract_score_forms(card_page, page_url)
        if len(scores) != 1 or len(requests) != 1:
            continue
        score = scores[0]
        result[(score.title, score.chart_type, score.level_index)] = requests[0]
    return result


async def collect_and_sync(
    params: dict[str, str],
    output_root: Path,
    local_api: NalmaiLocalApiClient,
    shared_asset_root: Path | None = None,
) -> IntegratedCaptureResult:
    clean_params = validate_callback_params(params)
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": WECHAT_USER_AGENT},
    ) as client:
        cookies = await exchange_callback(client, clean_params)
        cookie_values = [cookie.value for cookie in cookies.jar]
        secrets = set(clean_params.values()) | set(cookie_values)

        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        directory = output_root / timestamp
        directory.mkdir(parents=True, exist_ok=False)
        manifest: dict[str, object] = {
            "format": "nalmai-wechat-capture-v2",
            "created_at_utc": timestamp,
            "raw_credentials_stored": False,
            "integrated_local_sync": True,
            "score_pages": [],
            "detail_pages": [],
            "profile_pages": [],
            "profile_assets": [],
        }
        profile_page_count, player_profile = await _capture_profile_pages(
            client,
            directory,
            manifest,
            secrets,
            shared_asset_root,
        )
        scores: list[NormalizedScore] = []
        detail_requests: dict[tuple[str, str, int], FormRequest] = {}

        for difficulty in range(5):
            url = SCORE_LIST_URL.format(difficulty=difficulty)
            response = await client.get(url, follow_redirects=False)
            if response.status_code == 302:
                raise CaptureError("舞萌网页会话在采集过程中失效。")
            response.raise_for_status()
            page_scores = parse_score_list(response.text)
            scores.extend(page_scores)
            detail_requests.update(
                _score_request_map(response.text, str(response.url))
            )
            secrets.update(cookie.value for cookie in client.cookies.jar)
            sanitized, card_count = sanitize_score_list(response.text, secrets)
            filename = f"score-list-diff-{difficulty}.sanitized.html"
            (directory / filename).write_text(
                sanitized, encoding="utf-8", newline="\n"
            )
            manifest["score_pages"].append(
                {
                    "difficulty": difficulty,
                    "file": filename,
                    "score_cards": card_count,
                    "played_scores": len(page_scores),
                }
            )

        requested_keys = await local_api.upload_scores(tuple(scores))
        await local_api.upload_player_profile(player_profile)
        grouped: dict[
            FormRequest, set[tuple[str, str, int]]
        ] = {}
        for item in requested_keys:
            key = (item.title, item.chart_type, item.level_index)
            request = detail_requests.get(key)
            if request is not None:
                grouped.setdefault(request, set()).add(key)

        if not grouped:
            raise CaptureError(
                "成绩已上传，但当前 B50 的谱面没有匹配到华立详情入口"
                f"（B50：{len(requested_keys)}，详情入口：{len(detail_requests)}）。"
            )

        found: dict[tuple[str, str, int], WechatChartDetail] = {}
        detail_page_count = 0
        detail_request_failures: list[int] = []
        non_html_detail_count = 0
        empty_detail_count = 0
        error_page_count = 0
        browser_client = BrowserSession(impersonate="chrome")
        _copy_httpx_cookies_to_browser(client.cookies, browser_client)
        try:
            for request, keys in grouped.items():
                await asyncio.sleep(DETAIL_REQUEST_INTERVAL_SECONDS)
                response = await _fetch_detail_in_browser_with_retry(
                    browser_client,
                    request,
                )
                if response.status_code >= 400:
                    detail_request_failures.append(response.status_code)
                    if error_page_count == 0:
                        request_secrets = secrets | {
                            value for _, value in request.fields if value
                        }
                        request_secrets.update(
                            _browser_cookie_values(browser_client)
                        )
                        sanitized_error = (
                            sanitize_detail_page(response.text, request_secrets)
                            if response.text.strip()
                            else (
                                "<html><body><p>Empty response body.</p>"
                                "</body></html>"
                            )
                        )
                        (
                            directory / "music-detail-error-1.sanitized.html"
                        ).write_text(
                            sanitized_error,
                            encoding="utf-8",
                            newline="\n",
                        )
                        error_page_count += 1
                    if response.status_code == 567:
                        break
                    continue
                content_type = response.headers.get("content-type", "")
                if "html" not in content_type.casefold():
                    non_html_detail_count += 1
                    continue
                parsed_details = parse_music_detail(response.text)
                matched_detail = False
                for item in parsed_details:
                    key = (item.title, item.chart_type, item.level_index)
                    if key in keys:
                        matched_detail = True
                        found[key] = WechatChartDetail(
                            title=item.title,
                            chart_type=item.chart_type,
                            level_index=item.level_index,
                            play_count=item.play_count,
                            dx_star=item.dx_star,
                        )
                if not matched_detail:
                    empty_detail_count += 1
                request_secrets = secrets | {
                    value for _, value in request.fields if value
                }
                request_secrets.update(
                    _browser_cookie_values(browser_client)
                )
                sanitized = sanitize_detail_page(response.text, request_secrets)
                filename = f"music-detail-{detail_page_count + 1}.sanitized.html"
                (directory / filename).write_text(
                    sanitized, encoding="utf-8", newline="\n"
                )
                manifest["detail_pages"].append(
                    {"file": filename, "http_method": request.method}
                )
                detail_page_count += 1
        finally:
            browser_client.close()

        if not found:
            status_summary = ", ".join(
                f"HTTP {status} × {count}"
                for status, count in sorted(Counter(detail_request_failures).items())
            )
            reasons = [status_summary] if status_summary else []
            if non_html_detail_count:
                reasons.append(f"非 HTML × {non_html_detail_count}")
            if empty_detail_count:
                reasons.append(f"页面未匹配 × {empty_detail_count}")
            reason_text = "；".join(reasons) or "没有发出详情请求"
            raise CaptureError(
                "成绩已上传，但没有取得当前 B50 的谱面详情：" + reason_text
            )

        saved_detail_count = await local_api.upload_details(tuple(found.values()))
        requested_set = {
            (item.title, item.chart_type, item.level_index)
            for item in requested_keys
        }
        missing_detail_count = len(requested_set - set(found))
        manifest["sync_summary"] = {
            "score_count": len(scores),
            "requested_b50_charts": len(requested_set),
            "saved_b50_details": saved_detail_count,
            "missing_b50_details": missing_detail_count,
            "detail_http_failures": detail_request_failures,
            "non_html_details": non_html_detail_count,
            "unmatched_detail_pages": empty_detail_count,
        }
        manifest_path = directory / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        archive = output_root / f"nalmai-wechat-capture-{timestamp}.zip"
        with zipfile.ZipFile(
            archive, "w", compression=zipfile.ZIP_DEFLATED
        ) as bundle:
            for path in sorted(directory.iterdir()):
                bundle.write(path, arcname=path.name)
        return IntegratedCaptureResult(
            bundle=CaptureBundle(
                directory=directory,
                archive=archive,
                score_page_count=5,
                detail_page_count=detail_page_count,
                profile_page_count=profile_page_count,
                shared_asset_count=len(manifest.get("shared_profile_assets", [])),
            ),
            score_count=len(scores),
            requested_detail_count=len(requested_set),
            saved_detail_count=saved_detail_count,
            missing_detail_count=missing_detail_count,
        )
