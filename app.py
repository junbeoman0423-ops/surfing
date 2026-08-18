import streamlit as st
import requests
import pandas as pd
import pydeck as pdk
import time

# =====================================================================
# Ocean ICT Festival 출품작 - 서핑 환경 예측 및 추천 시스템 (웹 대시보드)
# 화면 전환(홈 -> 결과) + 큰 타이틀 + 반짝이는 제작자 크레딧
# =====================================================================

# --- 데이터 수집 함수 ---
@st.cache_data(ttl=600)
def fetch_weather_and_marine(lat, lon, retries=2):
    for attempt in range(retries + 1):
        try:
            weather_url = "https://api.open-meteo.com/v1/forecast"
            weather_params = {
                "latitude": lat, "longitude": lon,
                "current": "temperature_2m,wind_speed_10m,wind_direction_10m",
                "timezone": "Asia/Seoul"
            }
            w_res = requests.get(weather_url, params=weather_params, timeout=8).json()

            marine_url = "https://marine-api.open-meteo.com/v1/marine"
            marine_params = {
                "latitude": lat, "longitude": lon,
                "current": "wave_height,wave_period,sea_level_height_msl",
                "timezone": "Asia/Seoul"
            }
            m_res = requests.get(marine_url, params=marine_params, timeout=8).json()

            return {
                "temp": w_res['current']['temperature_2m'],
                "wind_speed": w_res['current']['wind_speed_10m'],
                "wind_direction": w_res['current']['wind_direction_10m'],
                "wave_height": m_res['current'].get('wave_height', 0.5),
                "wave_period": m_res['current'].get('wave_period', 5.0),
                "tide_level": m_res['current'].get('sea_level_height_msl', None)
            }
        except Exception:
            if attempt < retries:
                time.sleep(1)
                continue
            return {"temp": 20, "wind_speed": 3, "wind_direction": 0,
                     "wave_height": 1, "wave_period": 6, "tide_level": None}

def calculate_wave_shape_score(wave_period, wind_speed_kph, wind_direction, beach_angle, tide_level_m=None):
    score = 0
    if wave_period >= 12:
        score += 50
    elif wave_period >= 8:
        score += 20 + (wave_period - 8) * (30 / 4)
    elif wave_period >= 5:
        score += -20 + (wave_period - 5) * (40 / 3)
    else:
        score -= 50

    wind_diff = abs((wind_direction - beach_angle + 180) % 360 - 180)
    if wind_speed_kph > 5:
        if wind_diff < 45:
            score += min(30, wind_speed_kph * 1.5)
        elif wind_diff > 135:
            score -= min(30, wind_speed_kph * 1.5)

    if tide_level_m is not None:
        if tide_level_m < 0.8:
            score += 20
        elif tide_level_m > 2.2:
            score -= 20

    final_score = max(-100, min(100, round(score, 1)))
    if final_score >= 40:
        shape_type = "Pitching (가파름)"
    elif final_score <= -40:
        shape_type = "Rolling (완만함)"
    else:
        shape_type = "Spilling/Neutral (일반적)"
    return final_score, shape_type

def calculate_score(data, shape_score):
    wh, wp, temp, wind = data['wave_height'], data['wave_period'], data['temp'], data['wind_speed']
    height_score = max(0, 30 - abs(wh - 1.2) * 15)
    period_score = max(0, min(25, wp * 2.5))
    temp_score = max(0, 20 - abs(temp - 22) * 1.2)
    wind_score = max(0, 15 - min(15, wind * 0.5))
    shape_bonus = max(0, 10 - abs(shape_score - 20) * 0.1)
    breakdown = {
        "파고 점수": round(height_score, 1), "주기 점수": round(period_score, 1),
        "기온 점수": round(temp_score, 1), "바람 점수": round(wind_score, 1),
        "형태 점수": round(shape_bonus, 1),
    }
    total = round(sum(breakdown.values()), 1)
    return total, breakdown

def calculate_spot_difficulty(bottom_type, wave_height_m, wave_period, wave_shape_score, has_rip_current=False):
    score = 0
    if bottom_type == 'reef':
        score += 35
    elif bottom_type == 'pebble':
        score += 20
    else:
        score += 10

    if wave_height_m >= 2.5:
        score += 30
    elif wave_height_m >= 1.5:
        score += 20
    elif wave_height_m >= 0.8:
        score += 10
    else:
        score += 5

    if wave_period >= 9 or wave_shape_score >= 40:
        score += 20
    elif wave_period >= 6 or wave_shape_score >= 0:
        score += 10
    else:
        score += 5

    if has_rip_current:
        score += 15

    final_score = max(0, min(100, score))
    if final_score < 25:
        level_num, level, target = 1, "Level 1 (초급)", "입문자 & 롱보더 (안전하고 완만함)"
    elif final_score < 45:
        level_num, level, target = 2, "Level 2 (중초급)", "초중급자 (라이딩 및 테이크오프 연습 적합)"
    elif final_score < 65:
        level_num, level, target = 3, "Level 3 (중급)", "중급자 (빠른 파도 대응 필요)"
    elif final_score < 85:
        level_num, level, target = 4, "Level 4 (중상급)", "상급자 (강한 파워와 속도 제어 필요)"
    else:
        level_num, level, target = 5, "Level 5 (최상급)", "전문 서퍼 전용 (부상 위험 높음)"
    return final_score, level, target, level_num

BOARD_CHART = [
    ("에어리얼 보드 (Aerial Board)", 2.0, 75, "작고 강하게 부서지는 파도에서 공중 트릭에 최적화된 숙련자용 보드"),
    ("토우 보드 (Tow Board)", 11.0, 75, "초대형 파도를 제트스키로 견인해서 타는 전문가 전용 보드"),
    ("숏보드 (Shortboard)", 7.0, 45, "가파르고 파워풀한 파도에서 빠른 턴에 적합. 중~상급자 추천"),
    ("스텝업 (Step Up)", 9.5, 40, "숏보드보다 크고 두꺼워 크고 강한 파도에서도 안정적인 보드"),
    ("그로벨러/하이브리드 (Groveler)", 0.5, 10, "작고 힘없는 파도에서도 기동성을 살리는 숏보드 계열 변형 보드"),
    ("건 보드 (Gun)", 11.5, -10, "크고 파워풀한 파도를 빠르게 가르는 길고 뾰족한 보드. 숙련자 전용"),
    ("피쉬보드 (Fish)", 2.5, -30, "짧고 통통 튀는 파도에 강함. 부력이 좋아 초·중급자도 무난"),
    ("롱보드 (Longboard)", 2.5, -60, "느리고 완만한 파도에 최적. 초보자 입문 및 크루징 추천"),
    ("퍼포먼스 롱보드 (Performance Longboard)", 7.5, -55, "롱보드의 안정성과 숏보드의 기동성을 겸비한 올라운드 보드"),
    ("플랫워터 SUP (Flatwater SUP)", 0.5, -85, "파도가 거의 없는 잔잔한 수면에서 패들보딩 연습에 적합"),
]

def get_board_from_chart(height_ft, shape_score):
    best_board, best_desc, best_dist = None, None, float('inf')
    for name, bx, by, desc in BOARD_CHART:
        dx = (height_ft - bx) / 12.0
        dy = (shape_score - by) / 100.0
        dist = dx ** 2 + dy ** 2
        if dist < best_dist:
            best_dist = dist
            best_board, best_desc = name, desc
    return best_board, best_desc

def get_recommendations(data, beach_angle):
    height_ft = data['wave_height'] * 3.28084
    shape_score, shape_type = calculate_wave_shape_score(
        data['wave_period'], data['wind_speed'], data['wind_direction'],
        beach_angle, data.get('tide_level')
    )
    board, board_desc = get_board_from_chart(height_ft, shape_score)
    temp = data['temp']
    gear = "래쉬가드/스프링슈트" if temp >= 24 else "3/2mm 풀슈트" if temp >= 18 else "겨울용 풀슈트/부츠"
    return board, board_desc, gear, height_ft, shape_score, shape_type

def apply_skill_board_override(board, board_desc, user_level_num, diff_level_num):
    if user_level_num <= 2 and diff_level_num >= 4:
        return ("롱보드 (Longboard) - 안전 우선 추천", "이 스팟은 실력 대비 파도가 강합니다. 입문자는 롱보드로 안전한 구역에서만 연습하거나 다른 스팟을 고려하세요.")
    return board, board_desc

def pick_best_for_level(df, level_num):
    subset = df[df["난이도 숫자"] == level_num]
    if subset.empty:
        return None
    return subset.sort_values(by="종합 점수", ascending=False).iloc[0]

SPOTS = {
    "양양 (죽도해수욕장)":       {"lat": 38.011, "lon": 128.761, "angle": 70,  "bottom": "sand",   "rip": False},
    "양양 (기사문해변)":         {"lat": 38.030, "lon": 128.665, "angle": 75,  "bottom": "sand",   "rip": False},
    "양양 (인구해변)":           {"lat": 38.046, "lon": 128.658, "angle": 75,  "bottom": "sand",   "rip": False},
    "강릉 (금진해변)":           {"lat": 37.639, "lon": 129.196, "angle": 80,  "bottom": "sand",   "rip": False},
    "강릉 (경포해변)":           {"lat": 37.805, "lon": 128.908, "angle": 75,  "bottom": "sand",   "rip": False},
    "태안 (만리포해수욕장)":     {"lat": 36.782, "lon": 126.138, "angle": 260, "bottom": "sand",   "rip": False},
    "부산 (송정해수욕장)":       {"lat": 35.178, "lon": 129.199, "angle": 140, "bottom": "sand",   "rip": False},
    "부산 (다대포해수욕장)":     {"lat": 35.049, "lon": 128.966, "angle": 190, "bottom": "sand",   "rip": True},
    "제주 (중문해수욕장)":       {"lat": 33.244, "lon": 126.412, "angle": 180, "bottom": "reef",   "rip": False},
    "제주 (월정리해변)":         {"lat": 33.556, "lon": 126.796, "angle": 10,  "bottom": "sand",   "rip": False},
    "제주 (이호테우해변)":       {"lat": 33.499, "lon": 126.463, "angle": 340, "bottom": "sand",   "rip": False},
    "제주 (삼양검은모래해변)":   {"lat": 33.520, "lon": 126.586, "angle": 5,   "bottom": "sand",   "rip": False},
    "제주 (사계해변)":           {"lat": 33.225, "lon": 126.307, "angle": 190, "bottom": "reef",   "rip": False},
    "제주 (함덕해수욕장)":       {"lat": 33.543, "lon": 126.670, "angle": 15,  "bottom": "sand",   "rip": False},
    "제주 (곽지해수욕장)":       {"lat": 33.450, "lon": 126.310, "angle": 320, "bottom": "sand",   "rip": False},
    "고성 (봉수대해수욕장)":     {"lat": 38.350, "lon": 128.470, "angle": 85,  "bottom": "sand",   "rip": False},
    "포항 (신항만)":             {"lat": 36.070, "lon": 129.390, "angle": 95,  "bottom": "reef",   "rip": False},
    "경주 (남열해돋이해수욕장)": {"lat": 35.767, "lon": 129.487, "angle": 95,  "bottom": "pebble", "rip": False},
    "삼척 (용화해변)":           {"lat": 37.219, "lon": 129.313, "angle": 85,  "bottom": "sand",   "rip": False},
    "삼척 (맹방해변)":           {"lat": 37.315, "lon": 129.198, "angle": 85,  "bottom": "sand",   "rip": False},
}

# 스팟별 지역 그룹 (추천 스팟이 속한 지역만 지도에서 확대해서 보여주기 위함)
REGION_OF = {
    "양양 (죽도해수욕장)": "강원", "양양 (기사문해변)": "강원", "양양 (인구해변)": "강원",
    "강릉 (금진해변)": "강원", "강릉 (경포해변)": "강원",
    "고성 (봉수대해수욕장)": "강원", "삼척 (용화해변)": "강원", "삼척 (맹방해변)": "강원",
    "태안 (만리포해수욕장)": "충남",
    "부산 (송정해수욕장)": "부산", "부산 (다대포해수욕장)": "부산",
    "제주 (중문해수욕장)": "제주", "제주 (월정리해변)": "제주", "제주 (이호테우해변)": "제주",
    "제주 (삼양검은모래해변)": "제주", "제주 (사계해변)": "제주",
    "제주 (함덕해수욕장)": "제주", "제주 (곽지해수욕장)": "제주",
    "포항 (신항만)": "경북", "경주 (남열해돋이해수욕장)": "경북",
}

# --- 지도 색상 정의 ---
COLOR_BEST = [255, 59, 48, 255]      # 빨강 - 오늘의 최적 추천
COLOR_ADJACENT = [52, 199, 89, 255]  # 초록 - ±1단계 추천
COLOR_OTHER = [30, 136, 229, 190]    # 파랑 - 그 외 스팟

def build_map_df(coords_map, highlight_map, region_filter=None):
    """
    highlight_map: {스팟명: 'best' | 'lower' | 'upper'}
    region_filter가 주어지면 해당 지역 스팟 + 하이라이트된 스팟만 포함한다
    (다른 지역이라도 ±1단계 추천 스팟은 지도에서 빠지지 않도록 예외 처리).
    """
    rows = []
    for name, (lat, lon) in coords_map.items():
        is_highlighted = name in highlight_map
        in_region = (region_filter is None) or (REGION_OF.get(name) == region_filter)
        if not in_region and not is_highlighted:
            continue

        kind = highlight_map.get(name)
        if kind == "best":
            color, radius = COLOR_BEST, 260
        elif kind in ("lower", "upper"):
            color, radius = COLOR_ADJACENT, 210
        else:
            color, radius = COLOR_OTHER, 140

        rows.append({"스팟": name, "lat": lat, "lon": lon, "color": color, "radius": radius})
    return pd.DataFrame(rows)

def render_pydeck_map(map_df, zoom):
    if map_df.empty:
        st.caption("표시할 스팟이 없습니다.")
        return

    center_lat = map_df["lat"].mean()
    center_lon = map_df["lon"].mean()

    scatter_layer = pdk.Layer(
        "ScatterplotLayer",
        data=map_df,
        get_position="[lon, lat]",
        get_fill_color="color",
        get_radius="radius",
        pickable=True,
        stroked=True,
        get_line_color=[255, 255, 255, 220],
        line_width_min_pixels=1,
    )
    # 한글 라벨이 보이려면 character_set을 지정해야 함 (기본값은 영문/숫자만 렌더링).
    # size_units="meters" + size_min_pixels=0 으로 두면 지도를 축소(줌아웃)할수록
    # 글자가 실제 크기 기준으로 작아지다가 자연스럽게 사라짐.
    text_layer = pdk.Layer(
        "TextLayer",
        data=map_df,
        get_position="[lon, lat]",
        get_text="스팟",
        get_size=900,
        size_units="meters",
        size_min_pixels=0,
        size_max_pixels=15,
        get_color=[20, 20, 20, 255],
        get_alignment_baseline="bottom",
        get_pixel_offset=[0, -14],
        character_set="auto",
        font_family="'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif",
        billboard=True,
    )
    view_state = pdk.ViewState(
        latitude=center_lat,
        longitude=center_lon,
        zoom=zoom,
        pitch=0,
    )
    st.pydeck_chart(
        pdk.Deck(
            layers=[scatter_layer, text_layer],
            initial_view_state=view_state,
            map_style=None,
            tooltip={"text": "{스팟}"},
        ),
        use_container_width=True,
    )

# --- 스타일 (바다 배경, 큰 타이틀, 반짝이는 크레딧) ---
def apply_styles():
    st.markdown(
        """
        <style>
        .stApp {
            background: linear-gradient(180deg, #E3F6FD 0%, #A6E1FA 25%, #4FC3E8 55%, #0E7FB0 80%, #075E85 100%);
            background-attachment: fixed;
        }
        [data-testid="stHeader"] { background: rgba(255, 255, 255, 0); }
        .block-container {
            background: rgba(255, 255, 255, 0.80);
            border-radius: 18px;
            padding: 2rem 2.5rem;
            margin-top: 1rem;
        }
        .surf-main-title {
            text-align: center;
            font-size: 4.2rem;
            font-weight: 900;
            margin-bottom: 0;
            background: linear-gradient(90deg, #0077B6, #00B4D8, #48CAE4, #0077B6);
            background-size: 200% auto;
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
            animation: wave-shine 4s linear infinite;
        }
        @keyframes wave-shine {
            to { background-position: 200% center; }
        }
        .surf-sub-title {
            text-align: center;
            font-size: 1.1rem;
            color: #333;
            margin-top: 0.2rem;
            margin-bottom: 1.5rem;
        }
        .sparkle-credit {
            text-align: center;
            font-size: 1.05rem;
            font-weight: 700;
            background: linear-gradient(90deg, #ffffff, #FFD166, #ffffff, #90E0EF, #ffffff);
            background-size: 250% auto;
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
            animation: sparkle-move 2.5s linear infinite;
            padding: 0.8rem 0 0.3rem 0;
        }
        @keyframes sparkle-move {
            to { background-position: 250% center; }
        }
        </style>
        """,
        unsafe_allow_html=True
    )

def render_title():
    st.markdown('<div class="surf-main-title">🏄 서핑 가자~! 🌊</div>', unsafe_allow_html=True)
    st.markdown('<div class="surf-sub-title">해양 기상 기반 서핑 환경 예측 시스템 · Ocean ICT Festival 출품작</div>', unsafe_allow_html=True)

def render_credit():
    st.markdown(
        '<div class="sparkle-credit">✨ 제작자: 마현우 · 안준범 · 이상윤 · 한지호 ✨</div>',
        unsafe_allow_html=True
    )

# --- 데이터 분석 실행 ---
def run_analysis(user_level_num):
    progress_bar = st.progress(0, text="데이터를 불러오는 중입니다...")
    results = []
    coords_map = {}
    total = len(SPOTS)

    for i, (name, coords) in enumerate(SPOTS.items()):
        data = fetch_weather_and_marine(coords['lat'], coords['lon'])
        board, board_desc, gear, height_ft, shape_score, shape_type = get_recommendations(data, coords['angle'])
        score_total, score_breakdown = calculate_score(data, shape_score)
        diff_score, diff_level, diff_target, diff_level_num = calculate_spot_difficulty(
            coords['bottom'], data['wave_height'], data['wave_period'], shape_score, coords['rip']
        )
        board, board_desc = apply_skill_board_override(board, board_desc, user_level_num, diff_level_num)

        if diff_level_num == user_level_num:
            fit = "\u2705 딱 맞음"
        elif diff_level_num > user_level_num:
            fit = f"\u26A0\uFE0F 도전적 (+{diff_level_num - user_level_num})"
        else:
            fit = f"\U0001F343 여유로움 (-{user_level_num - diff_level_num})"

        results.append({
            "스팟": name, "종합 점수": score_total,
            "파고점수": score_breakdown["파고 점수"], "주기점수": score_breakdown["주기 점수"],
            "기온점수": score_breakdown["기온 점수"], "바람점수": score_breakdown["바람 점수"],
            "형태점수": score_breakdown["형태 점수"],
            "파고 (ft)": round(height_ft, 1), "파도 주기 (초)": data['wave_period'],
            "파도 형태": shape_type, "기온 (°C)": data['temp'],
            "추천 보드": board, "보드 설명": board_desc, "추천 준비물": gear,
            "난이도 점수": diff_score, "난이도 등급": diff_level, "난이도 숫자": diff_level_num,
            "권장 대상": diff_target, "내 실력 적합도": fit,
        })
        coords_map[name] = (coords['lat'], coords['lon'])
        progress_bar.progress((i + 1) / total, text=f"{name} 데이터 분석 완료 ({i+1}/{total})")
        time.sleep(0.1)

    progress_bar.empty()
    df = pd.DataFrame(results).sort_values(by="종합 점수", ascending=False).reset_index(drop=True)
    return df, coords_map

# --- 화면 1: 홈 (실력 선택) ---
def render_home():
    render_title()
    render_credit()
    st.divider()

    st.markdown("#### \u2B50 먼저, 당신의 서핑 실력을 선택해주세요")
    level_labels = {0: "Level 1 - 입문자 (파도를 처음 타봐요)",
                     1: "Level 2 - 초중급 (테이크오프는 가능해요)",
                     2: "Level 3 - 중급 (라이딩과 턴을 시도해요)",
                     3: "Level 4 - 중상급 (파워풀한 파도도 즐겨요)",
                     4: "Level 5 - 최상급 (어떤 파도든 도전해요)"}
    star_value = st.feedback("stars")
    user_level_num = (star_value + 1) if star_value is not None else 3
    st.caption(f"선택하신 실력: **{level_labels[star_value if star_value is not None else 2]}**"
               + ("" if star_value is not None else " (기본값 · 별을 눌러 선택하세요)"))
    st.divider()

    st.caption("⚠️ 해저 지형과 이안류 정보는 참고용 정적 데이터입니다. 실제 방문 전 현지 안전 정보를 반드시 확인하세요.")

    if st.button("\U0001F30A 실시간 서핑 환경 데이터 분석 시작", type="primary", use_container_width=True):
        with st.spinner("바다로 나갈 준비를 하는 중... \U0001F30A"):
            df, coords_map = run_analysis(user_level_num)
        st.session_state.df = df
        st.session_state.coords_map = coords_map
        st.session_state.user_level_num = user_level_num
        st.session_state.page = "results"
        st.rerun()

# --- 화면 2: 결과 ---
def render_results():
    render_title()
    render_credit()

    if st.button("\u2190 다시 선택하기"):
        st.session_state.page = "home"
        st.rerun()

    st.divider()

    df = st.session_state.df
    coords_map = st.session_state.coords_map
    user_level_num = st.session_state.user_level_num

    matched_df = df[df["난이도 숫자"] == user_level_num]
    if matched_df.empty:
        df["_diff_gap"] = (df["난이도 숫자"] - user_level_num).abs()
        min_gap = df["_diff_gap"].min()
        matched_df = df[df["_diff_gap"] == min_gap]
    best_spot = matched_df.sort_values(by="종합 점수", ascending=False).iloc[0]

    st.success("데이터 분석 완료!")
    st.subheader(f"\U0001F3C6 [Level {user_level_num}] 당신에게 딱 맞는 서핑 스팟: **{best_spot['스팟']}** ({best_spot['종합 점수']}점)")

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("\U0001F30A 파고", f"{best_spot['파고 (ft)']} ft")
    col2.metric("\u23F1\uFE0F 파도 주기", f"{best_spot['파도 주기 (초)']} 초")
    col3.metric("\U0001F30A 파도 형태", best_spot['파도 형태'])
    col4.metric("\U0001F3C4 추천 보드", best_spot['추천 보드'])
    col5.metric("\u26A0\uFE0F 난이도", best_spot['난이도 등급'])

    st.info(f"\U0001F4A1 **보드 선정 이유:** {best_spot['보드 설명']}")
    st.info(f"\U0001F457 **필수 준비물:** {best_spot['추천 준비물']}")
    st.warning(f"\U0001F3C3 **권장 대상:** {best_spot['권장 대상']} (난이도 점수 {best_spot['난이도 점수']}/100, 내 실력 적합도: {best_spot['내 실력 적합도']})")

    st.markdown("### \U0001F504 내 실력 ±1단계 추천 스팟")
    lower_level, upper_level = user_level_num - 1, user_level_num + 1
    lower_pick = pick_best_for_level(df, lower_level) if lower_level >= 1 else None
    upper_pick = pick_best_for_level(df, upper_level) if upper_level <= 5 else None

    adj_col1, adj_col2 = st.columns(2)

    with adj_col1:
        st.markdown(f"**\U0001F343 한 단계 쉬운 스팟 (Level {lower_level})**")
        if lower_level < 1:
            st.caption("이미 가장 쉬운 Level 1을 선택하셨습니다.")
        elif lower_pick is None:
            st.caption(f"Level {lower_level}에 해당하는 스팟이 오늘은 없습니다.")
        else:
            st.markdown(f"**{lower_pick['스팟']}** ({lower_pick['종합 점수']}점)")
            st.caption(f"{lower_pick['추천 보드']} · 파고 {lower_pick['파고 (ft)']}ft · {lower_pick['파도 형태']}")

    with adj_col2:
        st.markdown(f"**\u26A0\uFE0F 한 단계 도전적인 스팟 (Level {upper_level})**")
        if upper_level > 5:
            st.caption("이미 가장 어려운 Level 5를 선택하셨습니다.")
        elif upper_pick is None:
            st.caption(f"Level {upper_level}에 해당하는 스팟이 오늘은 없습니다.")
        else:
            st.markdown(f"**{upper_pick['스팟']}** ({upper_pick['종합 점수']}점)")
            st.caption(f"{upper_pick['추천 보드']} · 파고 {upper_pick['파고 (ft)']}ft · {upper_pick['파도 형태']}")

    with st.expander(f"\U0001F4CA {best_spot['스팟']} 점수 상세 내역 (총 {best_spot['종합 점수']}점 / 100점)"):
        bc1, bc2, bc3, bc4, bc5 = st.columns(5)
        bc1.metric("파고 기여", f"{best_spot['파고점수']} / 30")
        bc2.metric("주기 기여", f"{best_spot['주기점수']} / 25")
        bc3.metric("기온 기여", f"{best_spot['기온점수']} / 20")
        bc4.metric("바람 기여", f"{best_spot['바람점수']} / 15")
        bc5.metric("형태 기여", f"{best_spot['형태점수']} / 10")
        breakdown_df = pd.DataFrame({
            "항목": ["파고", "주기", "기온", "바람", "파도형태"],
            "점수": [best_spot['파고점수'], best_spot['주기점수'], best_spot['기온점수'],
                    best_spot['바람점수'], best_spot['형태점수']]
        }).set_index("항목")
        st.bar_chart(breakdown_df)

    st.divider()

    col_table, col_map = st.columns([2, 1])
    with col_table:
        st.markdown(f"### \u200B지역별 상세 분석 결과 (Level {user_level_num} 기준 적합도 포함)")
        display_df = df.drop(columns=["_diff_gap"], errors="ignore")
        st.dataframe(display_df, use_container_width=True, hide_index=True)

    with col_map:
        best_region = REGION_OF.get(best_spot['스팟'], None)
        st.markdown(f"### \u200B{best_region or ''} 지역 확대")
        st.caption("\U0001F534 오늘의 추천 스팟 · \U0001F7E2 ±1단계 추천 스팟 · \U0001F535 그 외 스팟")

        highlight_map = {best_spot['스팟']: "best"}
        if lower_pick is not None:
            highlight_map[lower_pick['스팟']] = "lower"
        if upper_pick is not None:
            highlight_map[upper_pick['스팟']] = "upper"

        region_map_df = build_map_df(coords_map, highlight_map, region_filter=best_region)
        render_pydeck_map(region_map_df, zoom=8.6)

        with st.expander("\U0001F30D 전체 20개 스팟 지도 보기"):
            full_map_df = build_map_df(coords_map, highlight_map, region_filter=None)
            render_pydeck_map(full_map_df, zoom=6.0)

# --- 메인 앱 로직 ---
def main():
    st.set_page_config(page_title="서핑 가자~!", page_icon="\U0001F3C4", layout="wide")
    apply_styles()

    if "page" not in st.session_state:
        st.session_state.page = "home"

    if st.session_state.page == "home":
        render_home()
    else:
        render_results()

if __name__ == '__main__':
    main()
