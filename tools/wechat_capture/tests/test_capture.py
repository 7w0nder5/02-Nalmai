from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace

import httpx
from curl_cffi.requests import Session as BrowserSession

from nalmai_wechat_capture.capture import (
    FormRequest,
    _browser_cookie_values,
    _capture_profile_pages,
    _copy_httpx_cookies_to_browser,
    _fetch_detail_in_browser,
    _fetch_detail_in_browser_with_retry,
    _fetch_detail_with_retry,
    _score_request_map,
    _sync_shared_collection_assets,
    authorization_url_from_location,
    collection_image_references,
    extract_score_forms,
    profile_image_references,
    sanitize_detail_page,
    sanitize_score_list,
)
from nalmai_wechat_capture.main import (
    callback_http_allow_pattern,
    plaintext_http_allow_pattern,
)


def test_authorization_url_changes_only_redirect_scheme() -> None:
    location = (
        "https://open.weixin.qq.com/connect/oauth2/authorize?appid=wx-test&"
        "redirect_uri=https%3A%2F%2Ftgk-wcaime.wahlap.com%2Fwc_auth%2Foauth%2Fcallback%2Fmaimai-dx&"
        "response_type=code&state=STATE"
    )

    result = authorization_url_from_location(location)

    assert "redirect_uri=http%3A%2F%2Ftgk-wcaime.wahlap.com" in result
    assert "appid=wx-test" in result
    assert "state=STATE" in result


def test_sanitize_score_list_keeps_score_data_but_removes_secrets() -> None:
    source = """
    <html><body>
      <div class="w_450 m_15 p_r f_0">
        <form action="/maimai-mobile/record/musicDetail/?token=SECRET" method="post">
          <input name="idx" value="SECRET-INDEX" />
          <div class="music_name_block">Example Song</div>
          <div class="music_score_block">100.1234%</div>
          <div>PC:17</div>
          <img src="https://maimai.wahlap.com/assets/music_icon_fc.png?token=SECRET" />
        </form>
      </div>
      <script>const cookie = 'SECRET';</script>
    </body></html>
    """

    result, count = sanitize_score_list(source, {"SECRET", "SECRET-INDEX"})

    assert count == 1
    assert "Example Song" in result
    assert "100.1234%" in result
    assert "PC:17" in result
    assert "music_icon_fc.png" in result
    assert "SECRET" not in result
    assert "<script" not in result
    assert "?token=" not in result


def test_extract_score_forms_uses_declared_action_method_and_fields() -> None:
    source = """
    <div class="w_450 m_15 p_r f_0">
      <form action="/maimai-mobile/record/musicDetail/" method="post">
        <input name="idx" value="42" />
        <input name="token" value="abc" />
      </form>
    </div>
    """

    result = extract_score_forms(
        source,
        "https://maimai.wahlap.com/maimai-mobile/record/musicGenre/search/?genre=99&diff=4",
    )

    assert len(result) == 1
    assert result[0].method == "POST"
    assert result[0].url == "https://maimai.wahlap.com/maimai-mobile/record/musicDetail/"
    assert result[0].fields == (("idx", "42"), ("token", "abc"))
    assert result[0].referer.endswith("?genre=99&diff=4")


def test_extract_score_forms_normalizes_detail_action_to_trusted_https_origin() -> None:
    source = """
    <div class="w_450 m_15 p_r f_0">
      <form action="http://maimai.wahlap.com:80/maimai-mobile/record/musicDetail/"
            method="get">
        <input name="idx" value="42" />
      </form>
    </div>
    """

    result = extract_score_forms(
        source,
        "https://maimai.wahlap.com/maimai-mobile/record/musicGenre/search/",
    )

    assert len(result) == 1
    assert result[0].url == (
        "https://maimai.wahlap.com/maimai-mobile/record/musicDetail/"
    )
    assert result[0].fields == (("idx", "42"),)


def test_sanitize_detail_page_redacts_long_ids_and_input_values() -> None:
    source = """
    <html><body>
      <div>PC 23</div><div>Friend 123456789012345</div>
      <input name="token" value="top-secret" />
    </body></html>
    """

    result = sanitize_detail_page(source, {"top-secret"})

    assert "PC 23" in result
    assert "123456789012345" not in result
    assert "top-secret" not in result


def test_sanitize_detail_page_keeps_score_numbers_matching_form_values() -> None:
    source = """
    <html><body>
      <div>游戏次数：17</div>
      <input name="diff" value="1" />
    </body></html>
    """

    result = sanitize_detail_page(source, set())

    assert "游戏次数：17" in result
    assert 'value="[REDACTED]"' in result


def test_profile_image_references_keep_only_official_https_assets() -> None:
    source = """
    <html><body>
      <div class="player_box">
        <img class="picon" src="/maimai-mobile/img/Icon/012345.png" />
      </div>
      <img src="https://maimai.wahlap.com/maimai-mobile/img/logo.png?v=2" />
      <img src="https://example.com/tracker.png" />
      <img src="http://maimai.wahlap.com/insecure.png" />
    </body></html>
    """

    result = profile_image_references(
        source,
        "https://maimai.wahlap.com/maimai-mobile/friend/userFriendCode/",
    )

    assert [item.source_path for item in result] == [
        "/maimai-mobile/img/Icon/012345.png",
        "/maimai-mobile/img/logo.png",
    ]
    assert result[0].css_class == "picon"
    assert result[0].parent_class == "player_box"


def test_collection_image_references_keep_only_lazy_official_artwork() -> None:
    source = """
    <html><body>
      <img loading="lazy" src="/maimai-mobile/img/Partner/partner.png" />
      <img src="/maimai-mobile/img/menu_collection.png" />
      <img loading="lazy" src="https://example.com/tracker.png" />
      <img loading="lazy" src="/outside/art.png" />
    </body></html>
    """

    result = collection_image_references(
        source,
        "https://maimai.wahlap.com/maimai-mobile/collection/partner/",
    )

    assert [item.source_path for item in result] == [
        "/maimai-mobile/img/Partner/partner.png"
    ]


def test_capture_profile_pages_downloads_only_exact_equipped_assets(tmp_path) -> None:
    player_page = """
    <html><body>
      <img src="/maimai-mobile/img/logo.png" />
      <img src="/maimai-mobile/img/Icon/avatar.png" />
      <div class="trophy_block trophy_Gold">
        <div class="trophy_inner_block">あ</div>
      </div>
      <div class="name_block">７ｗ０ｎｄｅｒｓ</div>
      <img src="/maimai-mobile/img/rating_base_rainbow.png" />
      <div class="rating_block">15896</div>
      <img src="/maimai-mobile/img/course/course.png" />
      <img src="/maimai-mobile/img/class/class.png" />
      <div><img src="/maimai-mobile/img/icon_star.png" />×635</div>
    </body></html>
    """

    def collection_page(directory: str, name: str, description: str) -> str:
        name_class = "p_t_10 p_b_5 f_14 break" if directory == "Icon" else "p_5 f_14 break"
        return f"""
        <html><body><div class="collection_setting_block">
          <div class="{name_class}">{name}</div>
          <div class="p_l_5 f_12 gray break">{description}</div>
          <img loading="lazy" src="/maimai-mobile/img/{directory}/equipped.png" />
        </div></body></html>
        """

    pages = {
        "/maimai-mobile/friend/userFriendCode/": player_page,
        "/maimai-mobile/collection/": collection_page("Icon", "当前头像", "头像说明"),
        "/maimai-mobile/collection/nameplate/": collection_page("NamePlate", "桃将", "牌子说明"),
        "/maimai-mobile/collection/frame/": collection_page("Frame", "当前背景", "背景说明"),
        "/maimai-mobile/collection/partner/": collection_page("Partner", "当前搭档", "搭档说明"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in pages:
            return httpx.Response(
                200,
                request=request,
                headers={"content-type": "text/html; charset=utf-8"},
                text=pages[request.url.path],
            )
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "image/png"},
            content=b"png-image",
        )

    async def run():
        manifest = {}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await _capture_profile_pages(
                client,
                tmp_path,
                manifest,
                set(),
                tmp_path / "shared-assets",
            ), manifest

    (page_count, profile), manifest = asyncio.run(run())

    assert page_count == 5
    assert profile.player_name == "７ｗ０ｎｄｅｒｓ"
    assert profile.nameplate_name == "桃将"
    assert {item["role"] for item in manifest["profile_assets"]} == {
        "version-logo",
        "avatar",
        "rating-base",
        "course-rank",
        "class-rank",
        "nameplate",
        "frame",
    }
    assert {item["category"] for item in manifest["shared_profile_assets"]} == {
        "icon",
        "nameplate",
        "frame",
        "partner",
    }
    assert manifest["shared_profile_assets_skipped"] == []


def test_shared_collection_sync_keeps_valid_assets_when_one_is_missing(tmp_path) -> None:
    raw_pages = {
        "icon-collection": """
        <html><body>
          <img loading="lazy" src="/maimai-mobile/img/Icon/valid.png" />
          <img loading="lazy" src="/maimai-mobile/img/Icon/missing.png" />
        </body></html>
        """,
        "nameplate-collection": "<html></html>",
        "frame-collection": "<html></html>",
        "partner-collection": "<html></html>",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/valid.png"):
            return httpx.Response(
                200,
                request=request,
                headers={"content-type": "image/png"},
                content=b"png-image",
            )
        return httpx.Response(404, request=request)

    async def run():
        manifest = {}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            count = await _sync_shared_collection_assets(
                client,
                raw_pages,
                tmp_path / "shared-assets",
                manifest,
            )
            return count, manifest

    count, manifest = asyncio.run(run())

    assert count == 1
    assert [item["file"] for item in manifest["shared_profile_assets"]] == [
        "icon/valid.png"
    ]
    assert manifest["shared_profile_assets_skipped"] == [
        {
            "category": "icon",
            "file": "icon/missing.png",
            "source_path": "/maimai-mobile/img/Icon/missing.png",
            "reason": "invalid_response",
        }
    ]


def test_plaintext_http_allow_pattern_excludes_https() -> None:
    pattern = plaintext_http_allow_pattern()

    assert re.fullmatch(pattern, "tgk-wcaime.wahlap.com:80")
    assert re.fullmatch(pattern, "114.117.135.47:80")
    assert re.fullmatch(pattern, "203.0.113.7:80")
    assert not re.fullmatch(pattern, "114.117.135.47:443")


def test_callback_http_allow_pattern_accepts_only_wahlap_callback_host() -> None:
    pattern = callback_http_allow_pattern()

    assert re.fullmatch(pattern, "tgk-wcaime.wahlap.com:80")
    assert not re.fullmatch(pattern, "114.117.135.47:80")
    assert not re.fullmatch(pattern, "tgk-wcaime.wahlap.com:443")
    assert not re.fullmatch(pattern, "example.com:80")


def test_score_request_map_links_exact_chart_to_declared_detail_form() -> None:
    source = """
    <html><body><div class="w_450 m_15 p_r f_0">
      <form action="/maimai-mobile/record/musicDetail/" method="post">
        <input name="idx" value="42" />
        <img src="/maimai-mobile/img/diff_master.png" />
        <div class="music_name_block">Test Song</div>
        <div class="music_score_block">100.5000%</div>
        <div class="music_score_block">1,234 / 1,500</div>
        <img src="/maimai-mobile/img/music_icon_sync.png" />
        <img src="/maimai-mobile/img/music_icon_fc.png" />
        <img src="/maimai-mobile/img/music_icon_sss.png" />
      </form>
      <img src="/maimai-mobile/img/music_standard.png" class="music_kind_icon" />
    </div></body></html>
    """

    result = _score_request_map(
        source,
        "https://maimai.wahlap.com/maimai-mobile/record/musicGenre/search/",
    )

    request = result[("Test Song", "SD", 3)]
    assert request.method == "POST"
    assert request.fields == (("idx", "42"),)


def test_fetch_detail_retries_temporary_http_failure(monkeypatch) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        status = 429 if calls == 1 else 200
        return httpx.Response(status, request=request, text="<html></html>")

    async def no_delay(_: float) -> None:
        return None

    monkeypatch.setattr(
        "nalmai_wechat_capture.capture.asyncio.sleep",
        no_delay,
    )

    async def run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await _fetch_detail_with_retry(
                client,
                FormRequest(
                    "GET",
                    "https://maimai.wahlap.com/maimai-mobile/record/musicDetail/",
                    (("idx", "42"),),
                ),
            )

    response = asyncio.run(run())

    assert response.status_code == 200
    assert calls == 2


def test_fetch_detail_uses_rotated_cookie_from_same_client_session() -> None:
    seen_cookies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_cookies.append(request.headers.get("cookie", ""))
        headers = {"set-cookie": "_t=rotated-token; Path=/"}
        return httpx.Response(200, request=request, headers=headers, text="ok")

    async def run() -> None:
        cookies = httpx.Cookies()
        cookies.set(
            "_t",
            "initial-token",
            domain="maimai.wahlap.com",
            path="/",
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            cookies=cookies,
        ) as client:
            request = FormRequest(
                "GET",
                "https://maimai.wahlap.com/maimai-mobile/record/musicDetail/",
                (("idx", "42"),),
            )
            await _fetch_detail_with_retry(client, request)
            await _fetch_detail_with_retry(client, request)

    asyncio.run(run())

    assert seen_cookies == ["_t=initial-token", "_t=rotated-token"]


def test_fetch_detail_sends_browser_navigation_headers() -> None:
    seen_headers: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(request.headers)
        return httpx.Response(200, request=request, text="ok")

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            await _fetch_detail_with_retry(
                client,
                FormRequest(
                    "GET",
                    "https://maimai.wahlap.com/maimai-mobile/record/musicDetail/",
                    (("idx", "42"),),
                    (
                        "https://maimai.wahlap.com/maimai-mobile/record/"
                        "musicGenre/search/?genre=99&diff=3"
                    ),
                ),
            )

    asyncio.run(run())

    headers = seen_headers[0]
    assert headers["referer"].endswith("?genre=99&diff=3")
    assert headers["sec-fetch-site"] == "same-origin"
    assert headers["sec-fetch-mode"] == "navigate"
    assert headers["sec-fetch-dest"] == "document"


def test_copy_httpx_cookies_to_browser_keeps_domain_and_path() -> None:
    source = httpx.Cookies()
    source.set(
        "_t",
        "authorization-token",
        domain=".maimai.wahlap.com",
        path="/maimai-mobile/",
    )
    browser = BrowserSession(impersonate="chrome")
    try:
        _copy_httpx_cookies_to_browser(source, browser)

        cookies = [
            (cookie.name, cookie.value, cookie.domain, cookie.path)
            for cookie in browser.cookies.jar
        ]
        assert cookies == [
            (
                "_t",
                "authorization-token",
                ".maimai.wahlap.com",
                "/maimai-mobile/",
            )
        ]
        assert _browser_cookie_values(browser) == ["authorization-token"]
    finally:
        browser.close()


def test_fetch_detail_in_browser_preserves_post_form_and_referer() -> None:
    class RecordingSession:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, object, object]] = []

        def post(self, url: str, **kwargs: object) -> SimpleNamespace:
            self.calls.append(("POST", url, kwargs["data"], kwargs["headers"]))
            return SimpleNamespace(status_code=200)

    session = RecordingSession()
    request = FormRequest(
        "POST",
        "https://maimai.wahlap.com/maimai-mobile/record/musicDetail/",
        (("idx", "42"), ("diff", "3")),
        (
            "https://maimai.wahlap.com/maimai-mobile/record/"
            "musicGenre/search/?genre=99&diff=3"
        ),
    )

    response = _fetch_detail_in_browser(session, request)  # type: ignore[arg-type]

    assert response.status_code == 200
    assert session.calls == [
        (
            "POST",
            "https://maimai.wahlap.com/maimai-mobile/record/musicDetail/",
            [("idx", "42"), ("diff", "3")],
            {"Referer": request.referer},
        )
    ]


def test_browser_detail_retries_temporary_http_failure(monkeypatch) -> None:
    statuses = iter((503, 200))
    calls = 0

    class RecordingSession:
        def get(self, _url: str, **_kwargs: object) -> SimpleNamespace:
            nonlocal calls
            calls += 1
            return SimpleNamespace(status_code=next(statuses))

    async def no_delay(_: float) -> None:
        return None

    monkeypatch.setattr(
        "nalmai_wechat_capture.capture.asyncio.sleep",
        no_delay,
    )

    response = asyncio.run(
        _fetch_detail_in_browser_with_retry(
            RecordingSession(),  # type: ignore[arg-type]
            FormRequest(
                "GET",
                "https://maimai.wahlap.com/maimai-mobile/record/musicDetail/",
                (("idx", "42"),),
            ),
        )
    )

    assert response.status_code == 200
    assert calls == 2
