#!/usr/bin/env python3
"""为 PUNK PLANET 生成带有网易云音乐自动更新数据的 data/punk_data.js。

设计目标：
1. 保留原有手工策展国家/乐队/歌曲数据；
2. 使用网易云音乐 API 拉取新歌；
3. 按国家映射到不同区域的新歌池；
4. 将自动发现的内容合并成每个国家的一张动态卡片；
5. 通过 state 文件记录首次出现时间，把“站内新歌”标记出来。

依赖：仅 Python 标准库。
API Base：优先读取环境变量 NCM_API_BASE，也支持 --api-base 传参。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

DYNAMIC_BAND_NAME = "🔥 网易云新歌雷达"
DYNAMIC_BAND_ERA = "自动更新"
DYNAMIC_BAND_HOMETOWN = "数据源：网易云音乐 API"
DYNAMIC_TAG_PREFIX = "最近更新"
DEFAULT_COUNTRIES = [
    "US", "CA", "GB", "AU", "JP", "DE", "MX", "BR", "CN",
    "KR", "SE", "FR", "AR", "PH", "ID", "IT", "RU",
]
NCM_API_BASE = "http://localhost:3000"
COUNTRY_AREA_MAP = {
    "CN": "ZH",
    "JP": "JP",
    "KR": "KR",
    "US": "EA",
    "CA": "EA",
    "GB": "EA",
    "AU": "EA",
    "DE": "EA",
    "FR": "EA",
    "SE": "EA",
    "IT": "EA",
    "ES": "EA",
    "NL": "EA",
    "IE": "EA",
    "NZ": "EA",
    "FI": "EA",
    "NO": "EA",
    "DK": "EA",
    "PL": "EA",
    "BR": "ALL",
    "MX": "ALL",
    "AR": "ALL",
    "CL": "ALL",
    "PH": "ALL",
    "ID": "ALL",
    "RU": "ALL",
}
SONG_TYPE_MAP = {
    "ALL": 0,
    "ZH": 7,
    "EA": 96,
    "KR": 16,
    "JP": 8,
}


class NCMError(RuntimeError):
    pass


@dataclass
class TrackRecord:
    artist: str
    title: str
    album: str
    year: str
    rank: int
    playcount: Optional[int]
    listeners: Optional[int]
    lastfm_url: str
    image: str
    matched_tags: List[str]
    is_new: bool
    first_seen_at: str


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_text(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"\s+", " ", value)
    return value


def normalize_track_key(artist: str, title: str) -> str:
    return f"{normalize_text(artist)}|||{normalize_text(title)}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="更新 PUNK PLANET 的网易云音乐动态数据")
    parser.add_argument("--api-base", default=os.getenv("NCM_API_BASE", NCM_API_BASE), help="网易云音乐 API Base URL；默认读取环境变量 NCM_API_BASE")
    parser.add_argument("--input", default="data/punk_data.js", help="现有前端数据文件路径")
    parser.add_argument("--output", default="data/punk_data.js", help="输出 JS 文件路径")
    parser.add_argument("--state", default="data/punk_update_state.json", help="状态文件路径，用于标记站内新歌")
    parser.add_argument("--countries", default=",".join(DEFAULT_COUNTRIES), help="需要更新的国家代码，逗号分隔，例如 US,GB,JP")
    parser.add_argument("--per-country-limit", type=int, default=8, help="每个国家写入多少首动态歌曲")
    parser.add_argument("--sleep", type=float, default=0.25, help="请求之间的休眠秒数，避免过快触发限流")
    parser.add_argument("--verbose", action="store_true", help="打印更多日志")
    return parser.parse_args()


def extract_object_literal(js_text: str) -> str:
    match = re.search(r"const\s+PUNK_DATA\s*=\s*(\{.*\})\s*;?\s*$", js_text, flags=re.S)
    if not match:
        raise ValueError("未能在 data/punk_data.js 中找到 const PUNK_DATA = {...}")
    return match.group(1)


def quote_unquoted_keys(text: str) -> str:
    pattern = re.compile(r'([\{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*):')
    return pattern.sub(r'\1"\2"\3:', text)


def load_js_data(path: Path) -> Dict[str, dict]:
    raw = path.read_text(encoding="utf-8")
    object_literal = extract_object_literal(raw)
    normalized = quote_unquoted_keys(object_literal)
    return json.loads(normalized)


def dump_js_data(path: Path, data: Dict[str, dict]) -> None:
    header = (
        "// 本文件由 scripts/update_punk_data.py 自动生成 / 更新\n"
        "// 若需调整静态策展内容，可先修改当前文件，再重新运行更新脚本\n"
        "const PUNK_DATA = "
    )
    content = header + json.dumps(data, ensure_ascii=False, indent=2) + ";\n"
    path.write_text(content, encoding="utf-8")


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": 1, "countries": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def http_get_json(url: str, timeout: float = 10.0) -> dict:
    req = Request(url)
    try:
        with urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8")
    except HTTPError as exc:
        print(f"[WARN] HTTP {exc.code} 请求失败，跳过: {url}")
        return {}
    except (URLError, socket.timeout, TimeoutError) as exc:
        print(f"[WARN] 网络超时或断开，跳过: {url}")
        return {}
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        print(f"[WARN] 返回内容不是合法 JSON，跳过: {url}")
        return {}
    return data


class NCMClient:
    def __init__(self, api_base: str, sleep_seconds: float = 0.25, verbose: bool = False):
        if not api_base:
            raise NCMError("缺少 API Base。请传入 --api-base 或设置环境变量 NCM_API_BASE")
        self.api_base = api_base.rstrip("/")
        self.sleep_seconds = sleep_seconds
        self.verbose = verbose

    def _call(self, path: str, params: Dict[str, object]) -> dict:
        query = urlencode(params)
        url = f"{self.api_base}{path}?{query}" if query else f"{self.api_base}{path}"
        if self.verbose:
            print(f"[NCM] 请求: {url}")
        data = http_get_json(url, timeout=8.0)
        if self.sleep_seconds:
            time.sleep(self.sleep_seconds)
        return data

    def get_top_songs(self, song_type: int) -> List[dict]:
        data = self._call("/top/song", {"type": song_type})
        return ensure_list(data.get("data") or data.get("songs") or [])


def ensure_list(value) -> List[dict]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def parse_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def pick_image(track: dict) -> str:
    album = track.get("album", {}) if isinstance(track.get("album"), dict) else {}
    return album.get("picUrl") or ""


def parse_publish_year(track: dict) -> str:
    album = track.get("album", {}) if isinstance(track.get("album"), dict) else {}
    ts = album.get("publishTime") or track.get("publishTime")
    if isinstance(ts, (int, float)) and ts > 0:
        return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y")
    return "N/A"


def get_song_type(code: str) -> int:
    area = COUNTRY_AREA_MAP.get(code, "ALL")
    return SONG_TYPE_MAP.get(area, 0)

def get_candidate_song_types(code: str) -> List[int]:
    area = COUNTRY_AREA_MAP.get(code, "ALL")
    primary = SONG_TYPE_MAP.get(area, 0)
    fallback_order = {
        "ALL": [0, 96, 7, 8, 16],
        "EA": [96, 0],
        "ZH": [7, 0],
        "JP": [8, 0],
        "KR": [16, 0],
    }
    types = fallback_order.get(area, [primary, 0])
    if primary in types:
        return types
    return [primary] + types


def classify_country_tracks(
    client: NCMClient,
    country_code: str,
    per_country_limit: int,
    state_country: dict,
    update_timestamp: str,
) -> Tuple[List[TrackRecord], dict]:
    seen_state_tracks = state_country.setdefault("tracks", {})
    accepted: List[TrackRecord] = []
    accepted_keys = set()
    pool: List[dict] = []
    for song_type in get_candidate_song_types(country_code):
        pool = client.get_top_songs(song_type=song_type)
        if pool:
            break
    for idx, track in enumerate(pool, start=1):
        artist_list = ensure_list(track.get("artists") or track.get("ar") or [])
        artist = ""
        if artist_list:
            artist = artist_list[0].get("name") or ""
        title = track.get("name", "")
        if not artist or not title:
            continue
        key = normalize_track_key(artist, title)
        if key in accepted_keys:
            continue

        state_track = seen_state_tracks.get(key, {})
        first_seen_at = state_track.get("first_seen_at") or update_timestamp
        is_new = "first_seen_at" not in state_track
        state_track.update({
            "artist": artist,
            "title": title,
            "first_seen_at": first_seen_at,
            "last_seen_at": update_timestamp,
            "last_rank": idx,
        })
        seen_state_tracks[key] = state_track

        album = track.get("album", {}) if isinstance(track.get("album"), dict) else {}
        al = track.get("al", {}) if isinstance(track.get("al"), dict) else {}
        album_title = album.get("name") or al.get("name") or "Single / 未知专辑"
        record = TrackRecord(
            artist=artist,
            title=title,
            album=album_title,
            year=parse_publish_year(track),
            rank=idx,
            playcount=parse_int(track.get("playcount")),
            listeners=parse_int(track.get("listeners")),
            lastfm_url=f"https://music.163.com/#/song?id={track.get('id', '')}",
            image=pick_image(track),
            matched_tags=[],
            is_new=is_new,
            first_seen_at=first_seen_at,
        )
        accepted.append(record)
        accepted_keys.add(key)
        if len(accepted) >= per_country_limit:
            return accepted, state_country
    return accepted, state_country


def build_dynamic_band(records: List[TrackRecord], update_timestamp: str) -> dict:
    songs = []
    for record in records:
        freshness = "🆕 新上榜" if record.is_new else "回归热榜"
        album_text = f"{record.artist} · {record.album} · {freshness}"
        songs.append({
            "title": record.title,
            "artist": record.artist,
            "album": album_text,
            "year": record.year,
            "isNew": record.is_new,
            "lastfmUrl": record.lastfm_url,
            "firstSeenAt": record.first_seen_at,
            "tags": record.matched_tags,
            "rank": record.rank,
        })
    return {
        "name": DYNAMIC_BAND_NAME,
        "era": DYNAMIC_BAND_ERA,
        "hometown": DYNAMIC_BAND_HOMETOWN,
        "tag": f"{DYNAMIC_TAG_PREFIX}：{update_timestamp}",
        "songs": songs,
    }


def merge_dynamic_band(country_data: dict, dynamic_band: dict) -> None:
    bands = country_data.setdefault("bands", [])
    filtered = [band for band in bands if band.get("name") != DYNAMIC_BAND_NAME]
    filtered.insert(0, dynamic_band)
    country_data["bands"] = filtered


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    state_path = Path(args.state)

    countries = [c.strip().upper() for c in args.countries.split(",") if c.strip()]
    data = load_js_data(input_path)
    state = load_state(state_path)
    state_countries = state.setdefault("countries", {})
    update_timestamp = now_iso()

    client = NCMClient(api_base=args.api_base, sleep_seconds=args.sleep, verbose=args.verbose)
    summary = {}
    for code in countries:
        if code not in data:
            print(f"[WARN] 前端数据中不存在国家 {code}，已跳过", file=sys.stderr)
            continue
        state_country = state_countries.setdefault(code, {})
        try:
            records, updated_state_country = classify_country_tracks(
                client=client,
                country_code=code,
                per_country_limit=args.per_country_limit,
                state_country=state_country,
                update_timestamp=update_timestamp,
            )
        except NCMError as e:
            print(f"[ERROR] 获取国家 {code} 数据失败: {e}", file=sys.stderr)
            continue
        state_countries[code] = updated_state_country
        dynamic_band = build_dynamic_band(records, update_timestamp)
        merge_dynamic_band(data[code], dynamic_band)
        summary[code] = {
            "matched_tracks": len(records),
            "new_tracks": sum(1 for r in records if r.is_new),
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    dump_js_data(output_path, data)
    save_state(state_path, state)

    print(json.dumps({
        "updated_at": update_timestamp,
        "countries": summary,
        "output": str(output_path),
        "state": str(state_path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except NCMError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1)
