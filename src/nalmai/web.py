from __future__ import annotations

import hmac
from base64 import b64decode
from binascii import Error as Base64Error
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict

from nalmai.bootstrap import Container, build_container
from nalmai.config import Settings
from nalmai.errors import NalmaiError
from nalmai.models import (
    ApplicationResponse,
    InboundMessage,
    NormalizedScore,
    WechatChartDetail,
    WechatPlayerProfile,
)


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform_user_id: str


class SubmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


class InternalMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform_user_id: str
    session_id: str
    text: str
    is_private: bool
    message_reference: str | None = None


class WechatScoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    achievements: float
    dx_score: int
    fc: str | None
    fs: str | None
    level_index: int
    title: str
    chart_type: str


class WechatScoresRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scores: list[WechatScoreRequest]


class WechatDetailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    chart_type: str
    level_index: int
    play_count: int
    dx_star: int | None


class WechatDetailsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    details: list[WechatDetailRequest]


class WechatProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    player_name: str
    rating: int
    title_text: str
    title_rarity: str
    star_count: int
    avatar_name: str
    nameplate_name: str
    nameplate_description: str
    frame_name: str
    frame_description: str
    version_logo_base64: str
    avatar_base64: str
    rating_base_base64: str
    course_rank_base64: str
    class_rank_base64: str
    nameplate_base64: str
    frame_base64: str


def create_app(
    settings: Settings | None = None,
    container: Container | None = None,
    *,
    manage_resources: bool = True,
) -> FastAPI:
    active_settings = settings or Settings.from_env()
    active_container = container or build_container(active_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if manage_resources:
            await active_container.divingfish.close()
            active_container.repository.close()

    app = FastAPI(
        title="Nalmai",
        version="0.1.5",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.container = active_container

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/internal/submission-sessions")
    async def create_submission_session(
        request: SessionRequest,
        x_nalmai_internal_token: str = Header(default=""),
    ) -> dict[str, str]:
        _require_internal_token(
            x_nalmai_internal_token, active_settings.internal_api_token
        )
        nonce = active_container.submissions.create(request.platform_user_id)
        return {"nonce": nonce, "expires_in": "300"}

    @app.post("/v1/submissions")
    async def submit(
        request: SubmissionRequest,
        x_nalmai_submission_token: str = Header(default=""),
    ) -> Response:
        try:
            platform_user_id = active_container.submissions.consume(
                x_nalmai_submission_token
            )
            result = await active_container.application.handle(
                InboundMessage(
                    platform_user_id=platform_user_id,
                    session_id="secure-submission",
                    text=request.text,
                    is_private=True,
                )
            )
            return _response(result)
        except NalmaiError as exc:
            return JSONResponse(
                {"text": exc.public_message, "error_code": exc.code}, status_code=400
            )

    @app.post("/internal/messages")
    async def internal_message(
        request: InternalMessageRequest,
        x_nalmai_internal_token: str = Header(default=""),
    ) -> Response:
        _require_internal_token(
            x_nalmai_internal_token, active_settings.internal_api_token
        )
        result = await active_container.application.handle(
            InboundMessage(**request.model_dump())
        )
        return _response(result)

    @app.post("/internal/wechat/claim")
    async def claim_wechat_session(
        x_nalmai_internal_token: str = Header(default=""),
    ) -> Response:
        _require_internal_token(
            x_nalmai_internal_token, active_settings.internal_api_token
        )
        try:
            session, token = await active_container.wechat.claim()
            return JSONResponse(
                {
                    "session_id": session.id,
                    "upload_token": token,
                    "expires_in": "900",
                }
            )
        except NalmaiError as exc:
            return JSONResponse(
                {"text": exc.public_message, "error_code": exc.code},
                status_code=400,
            )

    @app.post("/v1/wechat/scores")
    async def upload_wechat_scores(
        request: WechatScoresRequest,
        x_nalmai_wechat_token: str = Header(default=""),
    ) -> Response:
        try:
            scores = tuple(
                NormalizedScore(**item.model_dump()) for item in request.scores
            )
            result, charts = await active_container.wechat.upload_scores(
                x_nalmai_wechat_token, scores
            )
            return JSONResponse(
                {
                    "text": (
                        f"上传成功：{result.uploaded_count} 条，"
                        f"跳过 {result.skipped_count} 条。"
                    ),
                    "job_id": result.job_id,
                    "charts": [
                        {
                            "title": item.title,
                            "chart_type": item.chart_type,
                            "level_index": item.level_index,
                        }
                        for item in charts
                    ],
                }
            )
        except NalmaiError as exc:
            return JSONResponse(
                {"text": exc.public_message, "error_code": exc.code},
                status_code=400,
            )

    @app.post("/v1/wechat/details")
    async def upload_wechat_details(
        request: WechatDetailsRequest,
        x_nalmai_wechat_token: str = Header(default=""),
    ) -> Response:
        try:
            details = tuple(
                WechatChartDetail(**item.model_dump()) for item in request.details
            )
            saved = await active_container.wechat.upload_details(
                x_nalmai_wechat_token, details
            )
            return JSONResponse(
                {
                    "text": f"微信授权更新完成，已保存 {saved} 个 B50 谱面详情。",
                    "saved_details": saved,
                }
            )
        except NalmaiError as exc:
            return JSONResponse(
                {"text": exc.public_message, "error_code": exc.code},
                status_code=400,
            )

    @app.post("/v1/wechat/profile")
    async def upload_wechat_profile(
        request: WechatProfileRequest,
        x_nalmai_wechat_token: str = Header(default=""),
    ) -> Response:
        try:
            profile = WechatPlayerProfile(
                player_name=request.player_name,
                rating=request.rating,
                title_text=request.title_text,
                title_rarity=request.title_rarity,
                star_count=request.star_count,
                avatar_name=request.avatar_name,
                nameplate_name=request.nameplate_name,
                nameplate_description=request.nameplate_description,
                frame_name=request.frame_name,
                frame_description=request.frame_description,
                version_logo=_decode_profile_asset(request.version_logo_base64),
                avatar=_decode_profile_asset(request.avatar_base64),
                rating_base=_decode_profile_asset(request.rating_base_base64),
                course_rank=_decode_profile_asset(request.course_rank_base64),
                class_rank=_decode_profile_asset(request.class_rank_base64),
                nameplate=_decode_profile_asset(request.nameplate_base64),
                frame=_decode_profile_asset(request.frame_base64),
            )
            await active_container.wechat.upload_player_profile(
                x_nalmai_wechat_token,
                profile,
            )
            return JSONResponse({"text": "微信玩家资料已保存。"})
        except (Base64Error, ValueError):
            return JSONResponse(
                {
                    "text": "微信玩家资料图片编码无效。",
                    "error_code": "WECHAT_PROFILE_ASSET_INVALID",
                },
                status_code=400,
            )
        except NalmaiError as exc:
            return JSONResponse(
                {"text": exc.public_message, "error_code": exc.code},
                status_code=400,
            )

    return app


def _require_internal_token(provided: str, expected: str) -> None:
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="invalid internal token")


def _decode_profile_asset(value: str) -> bytes:
    if not value or len(value) > 8 * 1024 * 1024:
        raise ValueError("invalid profile asset size")
    content = b64decode(value, validate=True)
    if not content or len(content) > 5 * 1024 * 1024:
        raise ValueError("invalid profile asset size")
    return content


def _response(result: ApplicationResponse) -> Response:
    if result.image is not None:
        return Response(
            content=result.image.content,
            media_type=result.image.media_type,
            headers={"Content-Disposition": f'inline; filename="{result.image.filename}"'},
        )
    status_code = 400 if result.error_code else 200
    return JSONResponse(
        {"text": result.text, "error_code": result.error_code}, status_code=status_code
    )
