#!/usr/bin/env python3
"""为 PUNK PLANET 生成带有 Last.fm 自动更新数据的 data/punk_data.js。

设计目标：
1. 保留原有手工策展国家/乐队/歌曲数据；
2. 使用 Last.fm API 拉取各国热门曲目；
3. 通过 tag.getTopTracks + track.getTopTags 做“pop punk / 相近流派”过滤；
4. 将自动发现的内容合并成每个国家的一张动态卡片；
5. 通过 state 文件记录首次出现时间，把“站内新歌”标记出来。

依赖：仅 Python 标准库。
API Key：优先读取环境变量 LASTFM_API_KEY，也支持 --api-key 传参。
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
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

API_ROOT = "https://ws.audioscrobbler.com/2.0/"
USER_AGENT = "PunkPlanetAutoUpdater/1.0 (+https://www.last.fm/api)"
DYNAMIC_BAND_NAME = "🔥 Last.fm 热门 / 新歌雷达"
DYNAMIC_BAND_ERA = "自动更新"
DYNAMIC_BAND_HOMETOWN = "数据源：Last.fm API"
DYNAMIC_TAG_PREFIX = "最近更新"
DEFAULT_COUNTRIES = [
    "US", "CA", "GB", "AU", "JP", "DE", "MX", "BR", "CN",
    "KR", "SE", "FR", "AR", "PH", "ID", "IT", "RU",
]
COUNTRY_NAME_MAP = {
    "US": "United States",
    "GB": "United Kingdom",
    "JP": "Japan",
    "CA": "Canada",
    "AU": "Australia",
    "DE": "Germany",
    "BR": "Brazil",
    "FR": "France",
    "MX": "Mexico",
    "SE": "Sweden",
    "IT": "Italy",
    "ES": "Spain",
    "AR": "Argentina",
    "PH": "Philippines",
    "ID": "Indonesia",
    "RU": "Russian Federation",
    "KR": "Korea, Republic of",
    "FI": "Finland",
    "NL": "Netherlands",
    "NZ": "New Zealand",
    "IE": "Ireland",
    "NO": "Norway",
    "DK": "Denmark",
    "PL": "Poland",
    "CL": "Chile"
}
TAG_CANDIDATES = [
    "pop punk",
    "pop-punk",
    "punk pop",
    "skate punk",
    "easycore",
    "emo pop",
]
PUNK_KEYWORDS = {
    "pop punk",
    "pop-punk",
    "punk pop",
    "skate punk",
    "easycore",
    "emo pop",
    "emo",           # 用户要求保留 emo
    "midwest emo",   # 附赠一个经典的 midwest emo
    "neon pop punk",
}

BLACKLIST_KEYWORDS = {
    "k-pop",
    "hip hop",
    "rap",
    "indie",
    "kpop",
    "hip-hop",
    "j-pop",
}


class LastFMError(RuntimeError):
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
    parser = argparse.ArgumentParser(description="更新 PUNK PLANET 的 Last.fm 动态数据")
    parser.add_argument("--api-key", default=os.getenv("LASTFM_API_KEY", ""), help="Last.fm API Key；默认读取环境变量 LASTFM_API_KEY")
    parser.add_argument("--input", default="data/punk_data.js", help="现有前端数据文件路径")
    parser.add_argument("--output", default="data/punk_data.js", help="输出 JS 文件路径")
    parser.add_argument("--state", default="data/punk_update_state.json", help="状态文件路径，用于标记站内新歌")
    parser.add_argument("--countries", default=",".join(DEFAULT_COUNTRIES), help="需要更新的国家代码，逗号分隔，例如 US,GB,JP")
    parser.add_argument("--per-country-limit", type=int, default=8, help="每个国家写入多少首动态歌曲")
    parser.add_argument("--geo-pages", type=int, default=2, help="每个国家抓取多少页 geo.getTopTracks")
    parser.add_argument("--geo-page-size", type=int, default=50, help="geo.getTopTracks 每页条数")
    parser.add_argument("--tag-pages", type=int, default=2, help="每个候选 tag 抓取多少页 tag.getTopTracks")
    parser.add_argument("--tag-page-size", type=int, default=50, help="tag.getTopTracks 每页条数")
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


def http_get_json(params: Dict[str, object], timeout: float = 10.0) -> dict:
    url = f"{API_ROOT}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": USER_AGENT})
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
    if isinstance(data, dict) and "error" in data:
        raise LastFMError(f"Last.fm API error {data.get('error')}: {data.get('message')}")
    return data


class LastFMClient:
    def __init__(self, api_key: str, sleep_seconds: float = 0.25, verbose: bool = False):
        if not api_key:
            raise LastFMError("缺少 API Key。请传入 --api-key 或设置环境变量 LASTFM_API_KEY")
        self.api_key = api_key
        self.sleep_seconds = sleep_seconds
        self.verbose = verbose
        self._track_tags_cache: Dict[str, List[str]] = {}

    def _call(self, method: str, **kwargs) -> dict:
        params = {"method": method, "api_key": self.api_key, "format": "json"}
        params.update(kwargs)
        print(f"[Last.fm] 请求: {method} {kwargs}")
        data = http_get_json(params, timeout=5.0)
        if self.sleep_seconds:
            time.sleep(self.sleep_seconds)
        return data

    def get_geo_top_tracks(self, country: str, page: int, limit: int) -> List[dict]:
        data = self._call("geo.gettoptracks", country=country, page=page, limit=limit)
        return ensure_list(data.get("tracks", {}).get("track", []))

    def get_tag_top_tracks(self, tag: str, page: int, limit: int) -> List[dict]:
        data = self._call("tag.gettoptracks", tag=tag, page=page, limit=limit)
        return ensure_list(data.get("tracks", {}).get("track", []))

    def get_track_top_tags(self, artist: str, track: str) -> List[str]:
        cache_key = normalize_track_key(artist, track)
        if cache_key in self._track_tags_cache:
            return self._track_tags_cache[cache_key]
        data = self._call("track.gettoptags", artist=artist, track=track, autocorrect=1)
        tags = ensure_list(data.get("toptags", {}).get("tag", []))
        names = [normalize_text(t.get("name", "")) for t in tags if t.get("name")]
        self._track_tags_cache[cache_key] = names
        return names


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
    images = ensure_list(track.get("image", []))
    for candidate in reversed(images):
        url = candidate.get("#text") or candidate.get("text") or ""
        if url:
            return url
    return ""


def tag_matches_punk(tags: Iterable[str]) -> List[str]:
    matched = []
    
    # 第一步：先检查黑名单，如果包含了黑名单标签，直接一票否决
    for tag in tags:
        n = normalize_text(tag)
        if n in BLACKLIST_KEYWORDS:
            return []  # 直接返回空，这首歌不要了

    # 第二步：检查白名单，收集匹配的朋克/Emo标签
    for tag in tags:
        n = normalize_text(tag)
        if n in PUNK_KEYWORDS:
            matched.append(n)
            continue
        # 如果标签词里同时包含 punk 和 (pop/skate/emo/easycore) 也算
        if "punk" in n and ("pop" in n or "skate" in n or "emo" in n or "easycore" in n):
            matched.append(n)
            continue

    deduped = []
    seen = set()
    for item in matched:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped


def build_tag_pool(client: LastFMClient, pages: int, limit: int) -> Dict[str, List[str]]:
    pool: Dict[str, List[str]] = {}
    for tag in TAG_CANDIDATES:
        for page in range(1, pages + 1):
            tracks = client.get_tag_top_tracks(tag=tag, page=page, limit=limit)
            if not tracks:
                break
            for track in tracks:
                artist_name = track.get("artist", {}).get("name") if isinstance(track.get("artist"), dict) else None
                artist_name = artist_name or track.get("artist", "")
                title = track.get("name", "")
                key = normalize_track_key(artist_name, title)
                pool.setdefault(key, [])
                pool[key].append(tag)
    for key, values in pool.items():
        unique_values = []
        seen = set()
        for item in values:
            norm_item = normalize_text(item)
            if norm_item not in seen:
                unique_values.append(norm_item)
                seen.add(norm_item)
        pool[key] = unique_values
    return pool


def classify_country_tracks(
    client: LastFMClient,
    country_name: str,
    tag_pool: Dict[str, List[str]],
    per_country_limit: int,
    geo_pages: int,
    geo_page_size: int,
    state_country: dict,
    update_timestamp: str,
) -> Tuple[List[TrackRecord], dict]:
    seen_state_tracks = state_country.setdefault("tracks", {})
    accepted: List[TrackRecord] = []
    accepted_keys = set()

    for page in range(1, geo_pages + 1):
        geo_tracks = client.get_geo_top_tracks(country=country_name, page=page, limit=geo_page_size)
        if not geo_tracks:
            break
        for idx, track in enumerate(geo_tracks, start=1 + (page - 1) * geo_page_size):
            artist = ""
            if isinstance(track.get("artist"), dict):
                artist = track.get("artist", {}).get("name", "")
            else:
                artist = track.get("artist", "")
            title = track.get("name", "")
            if not artist or not title:
                continue
            key = normalize_track_key(artist, title)
            if key in accepted_keys:
                continue

            matched_tags = list(tag_pool.get(key, []))
            if not matched_tags:
                try:
                    matched_tags = tag_matches_punk(client.get_track_top_tags(artist=artist, track=title))
                except LastFMError:
                    matched_tags = []
            if not matched_tags:
                continue

            state_track = seen_state_tracks.get(key, {})
            first_seen_at = state_track.get("first_seen_at") or update_timestamp
            is_new = "first_seen_at" not in state_track
            state_track.update({
                "artist": artist,
                "title": title,
                "first_seen_at": first_seen_at,
                "last_seen_at": update_timestamp,
                "matched_tags": matched_tags,
                "last_rank": idx,
            })
            seen_state_tracks[key] = state_track

            album = track.get("album", {}) if isinstance(track.get("album"), dict) else {}
            album_title = album.get("title") or track.get("album", "") or "Single / 未知专辑"
            record = TrackRecord(
                artist=artist,
                title=title,
                album=album_title,
                year="N/A",
                rank=idx,
                playcount=parse_int(track.get("playcount")),
                listeners=parse_int(track.get("listeners")),
                lastfm_url=track.get("url", ""),
                image=pick_image(track),
                matched_tags=matched_tags,
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
        tag_text = ", ".join(record.matched_tags[:3]) if record.matched_tags else "punk"
        album_text = f"{record.artist} · {record.album} · {freshness} · {tag_text}"
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
    unknown = [c for c in countries if c not in COUNTRY_NAME_MAP]
    if unknown:
        raise SystemExit(f"未知国家代码：{', '.join(unknown)}")

    data = load_js_data(input_path)
    state = load_state(state_path)
    state_countries = state.setdefault("countries", {})
    update_timestamp = now_iso()

    client = LastFMClient(api_key=args.api_key, sleep_seconds=args.sleep, verbose=args.verbose)
    tag_pool = build_tag_pool(client, pages=args.tag_pages, limit=args.tag_page_size)

    summary = {}
    for code in countries:
        if code not in data:
            print(f"[WARN] 前端数据中不存在国家 {code}，已跳过", file=sys.stderr)
            continue
        country_name = COUNTRY_NAME_MAP[code]
        state_country = state_countries.setdefault(code, {})
        try:
            records, updated_state_country = classify_country_tracks(
                client=client,
                country_name=country_name,
                tag_pool=tag_pool,
                per_country_limit=args.per_country_limit,
                geo_pages=args.geo_pages,
                geo_page_size=args.geo_page_size,
                state_country=state_country,
                update_timestamp=update_timestamp,
            )
        except LastFMError as e:
            print(f"[ERROR] 获取国家 {country_name} 数据失败: {e}", file=sys.stderr)
            continue
        state_countries[code] = updated_state_country
        dynamic_band = build_dynamic_band(records, update_timestamp)
        merge_dynamic_band(data[code], dynamic_band)
        summary[code] = {
            "country": country_name,
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
    except LastFMError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1)
