from __future__ import annotations

from nalmai.wahlap_html import (
    parse_current_collection_item,
    parse_music_detail,
    parse_player_profile,
    parse_score_list,
)


def test_parse_player_profile_reads_exact_wahlap_profile_fields() -> None:
    page = """
    <html><body>
      <img src="/maimai-mobile/img/logo.png" class="logo p_5" />
      <div class="basic_block p_10 f_0">
        <img src="/maimai-mobile/img/Icon/avatar.png" class="w_112 f_l" />
        <div class="trophy_block trophy_Gold p_3 t_c f_0">
          <div class="trophy_inner_block f_13"><span>あ</span></div>
        </div>
        <div class="name_block f_l f_16">７ｗ０ｎｄｅｒｓ</div>
        <img src="/maimai-mobile/img/rating_base_rainbow.png" class="h_30 f_r" />
        <div class="rating_block">15896</div>
        <img src="/maimai-mobile/img/course/course-rank.png" class="h_35 f_l" />
        <img src="/maimai-mobile/img/class/class-rank.png" class="p_l_10 h_35 f_l" />
        <div class="p_l_10 f_l f_14">
          <img src="/maimai-mobile/img/icon_star.png" />×635
        </div>
      </div>
    </body></html>
    """

    profile = parse_player_profile(page)

    assert profile is not None
    assert profile.player_name == "７ｗ０ｎｄｅｒｓ"
    assert profile.rating == 15896
    assert profile.title_text == "あ"
    assert profile.title_rarity == "Gold"
    assert profile.star_count == 635
    assert profile.avatar_path == "/maimai-mobile/img/Icon/avatar.png"
    assert profile.course_rank_path == "/maimai-mobile/img/course/course-rank.png"
    assert profile.class_rank_path == "/maimai-mobile/img/class/class-rank.png"


def test_parse_current_nameplate_uses_setting_block_only() -> None:
    page = """
    <html><body>
      <div class="collection_setting_block">
        <div class="p_5 f_14 break">桃将</div>
        <div class="p_l_5 f_12 gray break">maimai PiNK 全曲/BASIC～MASTER/RANK SSS</div>
        <img src="/maimai-mobile/img/NamePlate/current.png" />
      </div>
      <div class="see_through_block">
        <div class="p_5 f_14 break">未装备姓名框</div>
        <div class="p_l_5 f_12 gray break">未装备</div>
        <img src="/maimai-mobile/img/NamePlate/not-current.png" />
      </div>
    </body></html>
    """

    item = parse_current_collection_item(page, "NamePlate")

    assert item is not None
    assert item.name == "桃将"
    assert item.description == "maimai PiNK 全曲/BASIC～MASTER/RANK SSS"
    assert item.image_path == "/maimai-mobile/img/NamePlate/current.png"


def test_parse_score_list_reads_real_wahlap_field_order() -> None:
    page = """
    <html><body><div class="w_450 m_15 p_r f_0">
      <div class="music_remaster_score_back pointer p_3">
        <form action="/maimai-mobile/record/musicDetail/" method="get">
          <img src="/maimai-mobile/img/diff_remaster.png" />
          <div class="music_lv_block">13</div>
          <div class="music_name_block">ビビデバ</div>
          <div class="music_score_block">100.7741%</div>
          <div class="music_score_block"><img src="/maimai-mobile/img/deluxscore.png" />2,208 / 2,475</div>
          <img src="/maimai-mobile/img/music_icon_fdx.png" />
          <img src="/maimai-mobile/img/music_icon_fcp.png" />
          <img src="/maimai-mobile/img/music_icon_sssp.png" />
        </form>
      </div>
      <img src="/maimai-mobile/img/music_dx.png" class="music_kind_icon" />
    </div></body></html>
    """

    scores = parse_score_list(page)

    assert len(scores) == 1
    assert scores[0].title == "ビビデバ"
    assert scores[0].chart_type == "DX"
    assert scores[0].level_index == 4
    assert scores[0].achievements == 100.7741
    assert scores[0].dx_score == 2208
    assert scores[0].fc == "fcp"
    assert scores[0].fs == "fsd"


def test_parse_score_list_skips_unplayed_card() -> None:
    page = """
    <html><body><div class="w_450 m_15 p_r f_0">
      <form><img src="/maimai-mobile/img/diff_master.png" />
      <div class="music_name_block">未游玩歌曲</div></form>
      <img src="/maimai-mobile/img/music_standard.png" class="music_kind_icon" />
    </div></body></html>
    """

    assert parse_score_list(page) == ()


def test_parse_score_list_accepts_absolute_wahlap_asset_urls() -> None:
    page = """
    <html><body><div class="w_450 m_15 p_r f_0">
      <form action="/maimai-mobile/record/musicDetail/" method="get">
        <img src="https://maimai.wahlap.com/maimai-mobile/img/diff_master.png" />
        <div class="music_name_block">ビビデバ</div>
        <div class="music_score_block">100.1900%</div>
        <div class="music_score_block">1,834 / 2,004</div>
        <img src="https://maimai.wahlap.com/maimai-mobile/img/music_icon_sync.png" />
        <img src="https://maimai.wahlap.com/maimai-mobile/img/music_icon_fc.png" />
        <img src="https://maimai.wahlap.com/maimai-mobile/img/music_icon_sss.png" />
      </form>
      <img src="https://maimai.wahlap.com/maimai-mobile/img/music_dx.png"
           class="music_kind_icon" />
    </div></body></html>
    """

    scores = parse_score_list(page)

    assert len(scores) == 1
    assert scores[0].level_index == 3
    assert scores[0].chart_type == "DX"
    assert scores[0].fc == "fc"
    assert scores[0].fs == "sync"


def test_parse_music_detail_reads_pc_star_and_statuses() -> None:
    page = """
    <html><body>
      <div class="basic_block"><div class="m_5 f_15 break">ビビデバ</div></div>
      <div id="remaster" class="music_remaster_score_back">
        <img src="/maimai-mobile/img/music_dx.png" class="music_kind_icon" />
        <div class="music_lv_back">13</div>
        <div class="t_r f_r">
          <img src="/maimai-mobile/img/music_icon_sssp.png" />
          <img src="/maimai-mobile/img/music_icon_fcp.png" />
          <img src="/maimai-mobile/img/music_icon_back.png" />
          <table><tr><td>游戏次数：</td><td>5</td></tr></table>
        </div>
        <div class="music_score_block">100.7741%</div>
        <div class="music_score_block">
          <img src="/maimai-mobile/img/music_icon_dxstar_detail_1.png" />
          2,208 / 2,475
        </div>
      </div>
    </body></html>
    """

    details = parse_music_detail(page)

    assert len(details) == 1
    detail = details[0]
    assert detail.title == "ビビデバ"
    assert detail.chart_type == "DX"
    assert detail.level_index == 4
    assert detail.level == "13"
    assert detail.achievements == 100.7741
    assert detail.dx_score == 2208
    assert detail.max_dx_score == 2475
    assert detail.fc == "fcp"
    assert detail.fs is None
    assert detail.rate == "sssp"
    assert detail.play_count == 5
    assert detail.dx_star == 1
