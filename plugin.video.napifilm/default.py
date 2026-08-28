# -*- coding: utf-8 -*-
"""NapiFilm Kodi 21.3 plugin.

The scraper reads public catalogue metadata. Playback is attempted only for
provider URLs present in the page and requires an installed ResolveURL addon.
"""
import base64
import hashlib
import html
import json
import os
import random
import re
import string
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

try:
    import resolveurl
except ImportError:
    resolveurl = None

try:
    import zidervisionurlresolver as zvr
    from zidervisionurlresolver import ResolverHTTPError
except ImportError:
    zvr = None
    ResolverHTTPError = None

HANDLE = int(sys.argv[1])
ADDON = xbmcaddon.Addon()
BASE_URL = ADDON.getSetting("base_url").strip().rstrip("/") or "https://napifilm.hu"
USER_AGENT = "Mozilla/5.0 (Kodi; NapiFilm addon)"
VK_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:154.0) Gecko/20100101 Firefox/154.0"
CACHE_TTL = 900
CACHE_DIR = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))
ADDON_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo("path"))
MEDIA_DIR = os.path.join(ADDON_PATH, "resources", "media")
PLACEHOLDER = os.path.join(MEDIA_DIR, "placeholder.png")
DEV_MODE = ADDON.getSetting("developer_mode").lower() == "true"
STATE_PATH = os.path.join(CACHE_DIR, "state.json")

def load_search_history():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as state_file:
            data = json.load(state_file)
        history = data.get("search_history", []) if isinstance(data, dict) else []
        if isinstance(history, list):
            return [value.strip() for value in history if isinstance(value, str) and value.strip()][:10]
        legacy = data.get("last_search", "") if isinstance(data, dict) else ""
        return [legacy.strip()] if isinstance(legacy, str) and legacy.strip() else []
    except Exception:
        legacy = ADDON.getSetting("last_search").strip()
        return [legacy] if legacy else []

def save_search(value):
    value = (value or "").strip()
    if not value:
        return
    history = [value] + [item for item in load_search_history() if item.casefold() != value.casefold()]
    history = history[:10]
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as state_file:
            json.dump({"search_history": history, "last_search": value}, state_file, ensure_ascii=False)
    except Exception as exc:
        xbmc.log("NapiFilm search state save skipped: %s" % exc, xbmc.LOGWARNING)
    try:
        ADDON.setSetting("last_search", value)
    except Exception:
        pass

LAST_SEARCH = load_search_history()

def media_icon(name):
    return os.path.join(MEDIA_DIR, name + ".png")
try:
    xbmcvfs.mkdirs(CACHE_DIR)
except Exception:
    pass


def get_url(path="/"):
    return urljoin(BASE_URL + "/", path.lstrip("/"))


def _cache_path(url):
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, digest + ".html")


def _listing_cache_path(url, kind):
    digest = hashlib.sha256((kind or "all").encode("utf-8") + b"|" + url.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, "listing_" + digest + ".json")


def load_listing_cache(url, kind):
    path = _listing_cache_path(url, kind)
    try:
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_TTL:
            with open(path, "r", encoding="utf-8") as cache_file:
                data = json.load(cache_file)
            if isinstance(data, list):
                xbmc.log("NapiFilm listing cache hit: %s" % url, xbmc.LOGDEBUG)
                return {"items": data, "current_page": 1, "pages": {}}
            if isinstance(data, dict) and isinstance(data.get("items"), list):
                data["pages"] = {int(page): page_url for page, page_url in (data.get("pages", {}) or {}).items()}
                xbmc.log("NapiFilm listing cache hit: %s" % url, xbmc.LOGDEBUG)
                return data
    except Exception as exc:
        xbmc.log("NapiFilm listing cache read skipped: %s" % exc, xbmc.LOGDEBUG)
    return None


def save_listing_cache(url, kind, items, current_page=1, pages=None):
    path = _listing_cache_path(url, kind)
    temporary = path + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as cache_file:
            json.dump({"items": items, "current_page": current_page, "pages": pages or {}}, cache_file, ensure_ascii=False)
        os.replace(temporary, path)
    except Exception as exc:
        xbmc.log("NapiFilm listing cache write skipped: %s" % exc, xbmc.LOGDEBUG)
        try:
            if os.path.exists(temporary):
                os.remove(temporary)
        except Exception:
            pass


def fetch(url, timeout=20):
    cache_path = _cache_path(url)
    try:
        if os.path.exists(cache_path) and time.time() - os.path.getmtime(cache_path) < CACHE_TTL:
            with open(cache_path, "r", encoding="utf-8") as cached:
                xbmc.log("NapiFilm cache hit: %s" % url, xbmc.LOGDEBUG)
                return cached.read()
    except Exception as exc:
        xbmc.log("NapiFilm cache read skipped: %s" % exc, xbmc.LOGDEBUG)
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    with urlopen(req, timeout=timeout) as response:
        content = response.read().decode("utf-8", "replace")
    try:
        with open(cache_path, "w", encoding="utf-8") as cached:
            cached.write(content)
    except Exception as exc:
        xbmc.log("NapiFilm cache write skipped: %s" % exc, xbmc.LOGDEBUG)
    return content


def post_bytes(url, form_data, headers=None, timeout=15):
    request_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        request_headers.update(headers)
    data = urlencode(form_data).encode("utf-8")
    req = Request(url, data=data, headers=request_headers, method="POST")
    with urlopen(req, timeout=timeout) as response:
        return response.read(), dict(response.headers.items())


def fetch_bytes(url, headers=None, timeout=12):
    request_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        request_headers.update(headers)
    req = Request(url, headers=request_headers)
    with urlopen(req, timeout=timeout) as response:
        return response.read(), dict(response.headers.items())


def rc4_decrypt(data, key):
    data = base64.b64decode(data)
    key_bytes = key.encode("utf-8")
    state = list(range(256))
    j = 0
    for i in range(256):
        j = (j + state[i] + key_bytes[i % len(key_bytes)]) % 256
        state[i], state[j] = state[j], state[i]
    i = j = 0
    output = bytearray()
    for value in data:
        i = (i + 1) % 256
        j = (j + state[i]) % 256
        state[i], state[j] = state[j], state[i]
        output.append(value ^ state[(state[i] + state[j]) % 256])
    return bytes(output)


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def clean_title(value):
    value = clean(value)
    value = re.sub(r"\s*\(\d{4}\)\s*", " ", value)
    # Remove the site's SEO suffixes from both films and series/episodes.
    value = re.sub(r"\s+(?:teljes\s+)?(?:online\s+)?(?:film|sorozat)(?:\s+online)?\s+magyarul\b.*$", "", value, flags=re.I)
    return clean(value)


def episode_title(value):
    match = re.search(r"(\d+)\s*\.?\s*rész\b", clean(value), re.I)
    return "%s. rész" % match.group(1) if match else clean_title(value)


def series_title(value):
    value = clean_title(value)
    return clean(re.split(r"\s+\d+\s*\.?\s*évad\b", value, maxsplit=1, flags=re.I)[0]) or value


def extract_year(value):
    match = re.search(r"\b((?:19|20)\d{2})\b", value or "")
    return int(match.group(1)) if match else 0


def detect_release_tags(value):
    """Return only source/audio labels explicitly present in site text."""
    text = clean(value).lower()
    tags = []
    patterns = [
        ("SZINKRONOS", r"\b(?:szinkron(?:os|nal|izált)?|magyar\s+szinkron(?:nal|os)?)\b"),
        ("ORIGINAL/FELIRATOS", r"\b(?:feliratos|felirattal|felirat|magyar\s+felirat(?:tal|os)?)\b|\b(?:hun\s*sub|subbed)\b"),
        ("KAMERÁS", r"\b(?:kamerás|cam|hdcam|ts|telesync|telecine)\b"),
        ("DVD", r"\b(?:dvd|dvdrip|dvdscr|dvd\s*rip)\b"),
        ("WEB", r"\b(?:web[- .]?dl|web[- .]?rip|web[- .]?release)\b"),
        ("BLU-RAY", r"\b(?:blu[- .]?ray|bdrip|bluray)\b"),
        ("HD", r"\b(?:full\s*hd|1080p|720p|2160p|4k|hdrip)\b"),
    ]
    for label, pattern in patterns:
        if re.search(pattern, text, re.I):
            tags.append(label)
    return tags


def detect_provider(source):
    """Return a provider label only when a local adapter can handle it."""
    if zvr is None:
        return ""
    embed_urls = re.findall(r'<iframe[^>]+\bsrc=["\']([^"\']+)', source or "", re.I | re.S)
    for value in embed_urls:
        host = urlparse(html.unescape(value)).netloc.lower()
        if "videa.hu" in host or "videakid.hu" in host:
            return "VIDEA"
        if "indavideo.hu" in host:
            return "INDAVIDEO"
        if "vkvideo.ru" in host or "vk.com" in host:
            return "VK VIDEO"
    return ""


def format_release_tags(tags):
    colors = {
        "SZINKRONOS": "lime",
        "ORIGINAL/FELIRATOS": "deepskyblue",
        "KAMERÁS": "tomato",
        "DVD": "gold",
        "WEB": "violet",
        "BLU-RAY": "orange",
        "HD": "white",
        "VIDEA": "#55aaff",
        "INDAVIDEO": "#ff9f43",
        "VK VIDEO": "#b58cff",
    }
    return " ".join("[COLOR %s][%s][/COLOR]" % (colors.get(tag, "lightgrey"), tag) for tag in tags)


def html_fragment_to_text(fragment):
    fragment = re.sub(r"<h[1-6][^>]*>.*?</h[1-6]>", " ", fragment, flags=re.I | re.S)
    fragment = re.sub(r"<br\s*/?>", " ", fragment, flags=re.I)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    return clean(fragment)


def extract_description(source):
    # Primary location: the site's schema.org description container.
    match = re.search(
        r"<div\b[^>]*\bitemprop=[\"']description[\"'][^>]*>(.*?)</div\s*>",
        source, re.I | re.S,
    )
    if match:
        text = html_fragment_to_text(match.group(1))
        if text:
            return text
    # Fallback for pages where the description container is not schema-marked.
    match = re.search(r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"']([^\"']+)", source, re.I | re.S)
    return clean(match.group(1)) if match else ""


def extract_metadata(source):
    description = extract_description(source)
    title_match = re.search(r"<h1[^>]*>(.*?)</h1>", source, re.I | re.S)
    page_title = html_fragment_to_text(title_match.group(1)) if title_match else ""
    h1_attr_match = re.search(r"<h1[^>]*\btitle=[\"']([^\"']+)[\"']", source, re.I | re.S)
    h1_title = clean(h1_attr_match.group(1)) if h1_attr_match else ""
    image_alt_match = re.search(r"<img[^>]*\bitemprop=[\"']image[\"'][^>]*\balt=[\"']([^\"']+)[\"']", source, re.I | re.S)
    image_alt = clean(image_alt_match.group(1)) if image_alt_match else ""
    release_tags = detect_release_tags(" ".join((page_title, h1_title, image_alt, description)))
    provider = detect_provider(source)
    genres = [clean(x) for x in re.findall(r'<span[^>]+itemprop=["\']genre["\'][^>]*>(.*?)</span>', source, re.I | re.S)]
    cast = [clean(x) for x in re.findall(r'<[^>]+itemprop=["\']name["\'][^>]*>(.*?)</[^>]+>', source, re.I | re.S)]
    poster_match = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', source, re.I)
    if not poster_match:
        poster_match = re.search(r'<img[^>]+itemprop=["\']image["\'][^>]+src=["\']([^"\']+)', source, re.I)
    return {
        "plot": description,
        "genre": genres,
        "cast": cast,
        "thumb": poster_match.group(1) if poster_match else "",
        "year": extract_year(source),
        "release_tags": release_tags,
        "provider": provider,
    }


def enrich_item(item):
    try:
        metadata = extract_metadata(fetch(item["url"], timeout=8))
        item.update({k: v for k, v in metadata.items() if v})
    except Exception as exc:
        xbmc.log("NapiFilm metadata skipped for %s: %s" % (item["url"], exc), xbmc.LOGDEBUG)
    return item


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.images = {}
        self.iframes = []
        self._a = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self._a = {"href": attrs["href"], "title": attrs.get("title", ""), "text": ""}
        elif tag == "img" and attrs.get("src"):
            self.images[attrs.get("src")] = attrs.get("alt", "")
        elif tag == "iframe" and attrs.get("src"):
            self.iframes.append(attrs["src"])

    def handle_data(self, data):
        if self._a is not None:
            self._a["text"] += " " + data

    def handle_endtag(self, tag):
        if tag == "a" and self._a is not None:
            item = self._a
            item["text"] = clean(item["text"])
            self.links.append(item)
            self._a = None


def parse_page(source):
    parser = PageParser()
    parser.feed(source)
    return parser


def add_folder(label, path, icon="DefaultFolder.png", action="browse"):
    li = xbmcgui.ListItem(label=label)
    li.setArt({"icon": icon, "thumb": icon})
    target = path if path.startswith("__") else get_url(path)
    xbmcplugin.addDirectoryItem(HANDLE, build_plugin_url(action, target), li, True)


def add_video(item):
    base_label = item["label"]
    release_tags = item.get("release_tags") or detect_release_tags(" ".join((item.get("label", ""), item.get("plot", ""))))
    provider = item.get("provider", "")
    tags = list(release_tags)
    if provider and provider not in tags:
        tags.append(provider)
    tag_text = format_release_tags(tags)
    label = item.get("display_label", base_label)
    if tag_text and tag_text not in label:
        label = "%s  %s" % (label, tag_text)
    li = xbmcgui.ListItem(label=label)
    artwork = item.get("thumb", "") or PLACEHOLDER
    li.setArt({"thumb": artwork, "icon": artwork})
    info = {"title": item["label"], "plot": item.get("plot", "")}
    if item.get("year"):
        info["year"] = item["year"]
    if item.get("genre"):
        info["genre"] = ", ".join(item["genre"])
    if item.get("cast"):
        info["cast"] = item["cast"]
    li.setInfo("video", info)
    li.setProperty("IsPlayable", "true")
    xbmcplugin.addDirectoryItem(HANDLE, build_plugin_url("play", item["url"]), li, False)


def add_series(item):
    release_tags = item.get("release_tags") or detect_release_tags(" ".join((item.get("label", ""), item.get("plot", ""))))
    provider = item.get("provider", "")
    tags = list(release_tags)
    if provider and provider not in tags:
        tags.append(provider)
    tag_text = format_release_tags(tags)
    label = item["label"] + ("  " + tag_text if tag_text else "")
    li = xbmcgui.ListItem(label=label)
    artwork = item.get("thumb", "") or PLACEHOLDER
    li.setArt({"thumb": artwork, "icon": artwork})
    info = {"title": item["label"], "plot": item.get("plot", "")}
    if item.get("year"):
        info["year"] = item["year"]
    if item.get("genre"):
        info["genre"] = ", ".join(item["genre"])
    li.setInfo("video", info)
    xbmcplugin.addDirectoryItem(HANDLE, build_plugin_url("series", item["url"]), li, True)


def build_plugin_url(action, value=""):
    # Kodi requires an absolute plugin:// URL for directory items.
    plugin_base = sys.argv[0].rstrip("/")
    return plugin_base + "/?" + urlencode({"action": action, "value": value})


def listing_items(source, current_url, kind=None):
    parser = parse_page(source)
    results = []
    seen = set()
    for link in parser.links:
        href = link["href"]
        raw_title = clean(link["title"] or link["text"])
        if not href or href.startswith("#") or not raw_title:
            continue
        if href.rstrip("/") == "/sorozatok":
            continue
        absolute = urljoin(current_url, href)
        item_path = urlparse(absolute).path.rstrip("/")
        is_series = item_path.startswith("/video/") or "/sorozat" in item_path
        is_movie = "-teljes-film" in item_path and not is_series
        if kind == "series" and not is_series:
            continue
        if kind == "movie" and not is_movie:
            continue
        if kind is None and not (is_series or is_movie):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        title = clean_title(raw_title)
        year = extract_year(raw_title)
        release_tags = detect_release_tags(raw_title)
        thumb = ""
        slug = href.lower().rstrip("/")
        for src, alt in parser.images.items():
            alt_clean = clean(alt).lower()
            src_lower = src.lower()
            if title.lower() in alt_clean or slug.split("/")[-1].replace("-teljes-film-magyarul", "") in src_lower:
                thumb = urljoin(current_url, src)
                break
        display_label = title
        if is_movie:
            display_label = "[COLOR gold]●[/COLOR] [COLOR white]%s[/COLOR]" % title
        results.append({"label": title, "display_label": display_label, "url": absolute, "thumb": thumb, "plot": "", "year": year, "release_tags": release_tags, "is_series": is_series})
    if kind == "series":
        grouped = {}
        for item in results:
            key = series_title(item["label"]) or item["label"]
            item["label"] = key
            grouped.setdefault(key, item)
        results = list(grouped.values())
    # Fetch detail pages concurrently while showing visible progress in Kodi.
    if results:
        progress = xbmcgui.DialogProgressBG()
        progress.create("NapiFilm", "Részletes adatok betöltése…")
        enriched = list(results)
        with ThreadPoolExecutor(max_workers=min(6, len(results))) as executor:
            futures = {executor.submit(enrich_item, item): index for index, item in enumerate(results)}
            completed = 0
            for future in as_completed(futures):
                index = futures[future]
                enriched[index] = future.result()
                completed += 1
                progress.update(int(completed * 100 / len(results)), "Adatok: %d / %d" % (completed, len(results)))
        progress.close()
        results = enriched
    return results


def pagination_pages(source, current_url):
    parser = parse_page(source)
    pages = {}
    for link in parser.links:
        href = link.get("href", "")
        match = re.search(r"(?:[?&])p=(\d+)", href)
        if not match:
            continue
        page = int(match.group(1))
        pages[page] = urljoin(current_url, href)
    current_page = int(dict(parse_qsl(urlparse(current_url).query)).get("p", "1") or "1")
    return current_page, pages


def open_listing(url, label="NapiFilm"):
    xbmcplugin.setPluginCategory(HANDLE, label)
    parsed_url = urlparse(url)
    path = parsed_url.path
    query_params = dict(parse_qsl(parsed_url.query))
    # Search may legitimately return both films and series.
    kind = None if "search" in query_params else ("series" if path.startswith("/sorozatok") else "movie")
    xbmcplugin.setContent(HANDLE, "tvshows" if kind == "series" else "movies")
    cached_listing = load_listing_cache(url, kind)
    if cached_listing is not None:
        results = cached_listing.get("items", [])
        current_page = int(cached_listing.get("current_page", 1) or 1)
        pages = cached_listing.get("pages", {}) or {}
        xbmc.log("NapiFilm using cached listing items: %d" % len(results), xbmc.LOGDEBUG)
    else:
        try:
            source = fetch(url)
        except Exception as exc:
            xbmcgui.Dialog().notification("NapiFilm", "Az oldal nem érhető el", xbmcgui.NOTIFICATION_ERROR)
            xbmc.log("NapiFilm fetch error: %s" % exc, xbmc.LOGERROR)
            return
        results = listing_items(source, url, kind)
        current_page, pages = pagination_pages(source, url)
        save_listing_cache(url, kind, results, current_page, pages)
    for item in results:
        add_series(item) if (kind == "series" or item.get("is_series")) else add_video(item)
    total_pages = max([int(page) for page in pages] or [current_page])
    if (current_page + 1) in pages:
        next_label = "[B][COLOR gold]▶  KÖVETKEZŐ OLDAL[/COLOR][/B]  [COLOR deepskyblue]— %d / %d —[/COLOR]" % (current_page + 1, total_pages)
        add_folder(next_label, pages[current_page + 1], "DefaultAddonVideo.png")
    xbmcplugin.endOfDirectory(HANDLE)


def series_detail(url):
    cached = load_listing_cache(url, "series_detail")
    if cached is not None:
        seasons = {
            int(item["number"]): item["url"]
            for item in cached.get("items", [])
            if isinstance(item, dict) and item.get("number") is not None and item.get("url")
        }
    else:
        try:
            source = fetch(url)
        except Exception as exc:
            xbmcgui.Dialog().notification("NapiFilm", "A sorozatoldal nem érhető el", xbmcgui.NOTIFICATION_ERROR)
            xbmc.log("NapiFilm series error: %s" % exc, xbmc.LOGERROR)
            return
        parser = parse_page(source)
        seasons = {}
        for link in parser.links:
            href = link.get("href", "")
            raw = clean(link.get("title", "") or link.get("text", ""))
            if not href or "/video/" not in href or not raw:
                continue
            if re.search(r"\brész\b", raw, re.I):
                continue
            season_match = re.search(r"(\d+)\s*\.?\s*évad", raw, re.I)
            if season_match:
                seasons.setdefault(int(season_match.group(1)), urljoin(url, href))
        if not seasons:
            season_match = re.search(r"(\d+)\s*\.?\s*évad", source, re.I)
            if season_match:
                seasons[int(season_match.group(1))] = url
        if not seasons:
            seasons[1] = url
        save_listing_cache(url, "series_detail", [{"number": number, "url": season_url} for number, season_url in seasons.items()])
    xbmcplugin.setPluginCategory(HANDLE, "Évadok")
    for number, season_url in sorted(seasons.items()):
        add_folder("%d. évad" % number, season_url, "DefaultTVShows.png", "season")
    xbmcplugin.endOfDirectory(HANDLE)


def season_detail(url):
    cached = load_listing_cache(url, "season_detail")
    if cached is not None:
        episodes = cached.get("items", [])
    else:
        try:
            source = fetch(url)
        except Exception as exc:
            xbmcgui.Dialog().notification("NapiFilm", "Az évadoldal nem érhető el", xbmcgui.NOTIFICATION_ERROR)
            xbmc.log("NapiFilm season error: %s" % exc, xbmc.LOGERROR)
            return
        parser = parse_page(source)
        seen = set()
        episodes = []
        for link in parser.links:
            href = link.get("href", "")
            raw = clean(link.get("title", "") or link.get("text", ""))
            if not href or "/video/" not in href or not re.search(r"\brész\b", raw, re.I):
                continue
            absolute = urljoin(url, href)
            if absolute in seen:
                continue
            seen.add(absolute)
            thumb = next((urljoin(url, src) for src, alt in parser.images.items() if src.startswith("/public/uploads/videos/")), "")
            label = episode_title(raw)
            episodes.append({"label": label, "display_label": "[COLOR lightskyblue]▶[/COLOR] [COLOR white]%s[/COLOR]" % label, "url": absolute, "thumb": thumb, "year": extract_year(raw), "plot": ""})
        save_listing_cache(url, "season_detail", episodes)
    xbmcplugin.setPluginCategory(HANDLE, "Epizódok")
    xbmcplugin.setContent(HANDLE, "episodes")
    for episode in episodes:
        add_video(episode)
    xbmcplugin.endOfDirectory(HANDLE)


def detail(url):
    try:
        source = fetch(url)
    except Exception as exc:
        xbmcgui.Dialog().notification("NapiFilm", "A filmoldal nem érhető el", xbmcgui.NOTIFICATION_ERROR)
        xbmc.log("NapiFilm detail error: %s" % exc, xbmc.LOGERROR)
        return
    parser = parse_page(source)
    title_match = re.search(r"<h1[^>]*>(.*?)</h1>", source, re.I | re.S)
    title = clean(re.sub(r"<[^>]+>", " ", title_match.group(1))) if title_match else "NapiFilm"
    embeds = [urljoin(url, x) for x in parser.iframes if "twitter.com" not in x]
    xbmc.log("NapiFilm detected player embeds: %s" % embeds, xbmc.LOGINFO)
    if not embeds:
        xbmcgui.Dialog().ok("NapiFilm", "Ehhez a bejegyzéshez nem található lejátszóforrás.")
        return
    play_resolved(embeds, title)


def play_resolved(provider_urls, title):
    errors = []
    for provider_url in provider_urls:
        host = urlparse(provider_url).netloc.lower()
        try:
            xbmc.log("NapiFilm resolving host=%s url=%s" % (host, provider_url), xbmc.LOGINFO)
            if DEV_MODE:
                xbmc.log("ZiderVision debug: provider=%s input=%s" % (host, provider_url), xbmc.LOGINFO)
            if "videa.hu" in host or "videakid.hu" in host:
                resolved_videa = zvr.resolve(provider_url) if zvr else ""
                stream = resolved_videa.get("url", "") if isinstance(resolved_videa, dict) else resolved_videa
                mimetype = resolved_videa.get("content-type", "") if isinstance(resolved_videa, dict) else ""
                if stream:
                    li = xbmcgui.ListItem(label=title)
                    li.setPath(stream)
                    if mimetype:
                        li.setMimeType(mimetype)
                    li.setInfo("video", {"title": title})
                    xbmcplugin.setResolvedUrl(HANDLE, True, li)
                    xbmcgui.Dialog().notification("NapiFilm", "Lejátszás innen: Videa", xbmcgui.NOTIFICATION_INFO, 3000)
                    xbmc.log("NapiFilm playback source=Videa host=%s quality=%s" % (host, mimetype or "auto"), xbmc.LOGINFO)
                    return
                errors.append("Videa adapter nem adott streamet: " + provider_url)
                continue
            if "vkvideo.ru" in host or "vk.com" in host:
                try:
                    resolved_vk = zvr.resolve(provider_url) if zvr else ""
                except Exception as new_exc:
                    xbmc.log("NapiFilm VK new API error: %s" % new_exc, xbmc.LOGWARNING)
                    resolved_vk = ""
                stream = resolved_vk.get("url", "") if isinstance(resolved_vk, dict) else resolved_vk
                mimetype = resolved_vk.get("content-type", "") if isinstance(resolved_vk, dict) else ""
                if stream:
                    li = xbmcgui.ListItem(label=title)
                    li.setPath(stream)
                    if mimetype:
                        li.setMimeType(mimetype)
                    li.setInfo("video", {"title": title})
                    xbmcplugin.setResolvedUrl(HANDLE, True, li)
                    xbmcgui.Dialog().notification("NapiFilm", "Lejátszás innen: VK Video", xbmcgui.NOTIFICATION_INFO, 3000)
                    xbmc.log("NapiFilm playback source=VK Video host=%s" % host, xbmc.LOGINFO)
                    return
                errors.append("VK Video adapter nem adott streamet: " + provider_url)
                continue
            if "indavideo.hu" in host or "videakid.hu" in host:
                resolved_inda = zvr.resolve(provider_url) if zvr else ""
                stream = resolved_inda.get("url", "") if isinstance(resolved_inda, dict) else resolved_inda
                if stream:
                    li = xbmcgui.ListItem(label=title)
                    li.setPath(stream)
                    li.setInfo("video", {"title": title})
                    xbmcplugin.setResolvedUrl(HANDLE, True, li)
                    xbmcgui.Dialog().notification("NapiFilm", "Lejátszás innen: IndaVideo", xbmcgui.NOTIFICATION_INFO, 3000)
                    xbmc.log("NapiFilm playback source=IndaVideo host=%s" % host, xbmc.LOGINFO)
                    if DEV_MODE:
                        xbmc.log("ZiderVision debug: IndaVideo resolved mime=video/mp4", xbmc.LOGINFO)
                    return
                errors.append("IndaVideo adapter nem adott streamet: " + provider_url)
                continue
            if resolveurl is None:
                errors.append("ResolveURL nincs telepítve: " + provider_url)
                continue
            media = resolveurl.HostedMediaFile(provider_url, content_type=True)
            if not media or not media.valid_url():
                errors.append("nem támogatott: " + provider_url)
                continue
            resolved = media.resolve()
            # ResolveURL can return either a URL string or a response dict.
            mimetype = ""
            if isinstance(resolved, dict):
                stream = resolved.get("url", "")
                subtitles = resolved.get("subs", {})
                mimetype = resolved.get("content-type", "")
            elif isinstance(resolved, (tuple, list)):
                stream = resolved[0] if resolved else ""
                subtitles = resolved[1] if len(resolved) > 1 and isinstance(resolved[1], dict) else {}
            else:
                stream = resolved or ""
                subtitles = {}
            if not isinstance(stream, str) or not stream:
                errors.append("nincs lejátszási URL: " + provider_url)
                continue
            xbmc.log("NapiFilm resolved stream type=%s url=%s" % (type(stream).__name__, stream), xbmc.LOGINFO)
            li = xbmcgui.ListItem(label=title)
            li.setPath(stream)
            li.setInfo("video", {"title": title})
            if mimetype:
                li.setMimeType(mimetype)
            if subtitles:
                li.setSubtitles(list(subtitles.values()))
            xbmcplugin.setResolvedUrl(HANDLE, True, li)
            xbmcgui.Dialog().notification("NapiFilm", "Lejátszás innen: %s" % host, xbmcgui.NOTIFICATION_INFO, 3000)
            xbmc.log("NapiFilm playback source=ResolveURL host=%s" % host, xbmc.LOGINFO)
            return
        except ResolverHTTPError as exc:
            errors.append("%s: HTTP %s" % (provider_url, exc.status))
            xbmc.log("NapiFilm %s HTTP %s: %s" % (exc.provider, exc.status, exc.url), xbmc.LOGWARNING)
            if exc.status == 404:
                xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
                xbmcgui.Dialog().ok("NapiFilm", "A videó oldal nem elérhető vagy a hivatkozás hibás.\n\nSzolgáltató: %s\n\nLehet, hogy a videót törölték vagy áthelyezték." % exc.provider)
                return
        except Exception as exc:
            errors.append("%s: %s" % (provider_url, exc))
            xbmc.log("NapiFilm resolver error for %s: %s" % (provider_url, exc), xbmc.LOGWARNING)
    xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
    hosts = ", ".join(sorted(set(urlparse(x).netloc for x in provider_urls)))
    if any("HTTP 404" in error for error in errors):
        message = "A videó oldal nem elérhető vagy a hivatkozás hibás."
    else:
        message = "A videóforrás nem oldható fel."
    xbmcgui.Dialog().ok("NapiFilm", "%s\n\nÉszlelt forrás: %s\n\nLehetséges, hogy a videó törölt, áthelyezett, korlátozott, vagy az aktuális resolver-verzió nem támogatja ezt a hostot." % (message, hosts or "ismeretlen"))


def root():
    xbmcplugin.setPluginCategory(HANDLE, "NapiFilm")
    add_folder("[B][COLOR gold]FILMEK[/COLOR][/B]", "__movies__", media_icon("movies"))
    add_folder("[B][COLOR violet]SOROZATOK[/COLOR][/B]", "/sorozatok", media_icon("series"))
    add_folder("[B][COLOR deepskyblue]KERESÉS[/COLOR][/B]", "__search__", media_icon("search"))
    xbmcplugin.endOfDirectory(HANDLE)


def movies_menu():
    xbmcplugin.setPluginCategory(HANDLE, "Filmek")
    add_folder("[B][COLOR gold]LEGÚJABB FILMEK[/COLOR][/B]", "/", media_icon("latest"))
    add_folder("[B][COLOR lightgreen]FILMEK ÉV SZERINT[/COLOR][/B]", "__years__", media_icon("years"))
    add_folder("[B][COLOR tomato]FILMEK KATEGÓRIA SZERINT[/COLOR][/B]", "__categories__", media_icon("categories"))
    xbmcplugin.endOfDirectory(HANDLE)


def years_menu():
    xbmcplugin.setPluginCategory(HANDLE, "Filmek év szerint")
    for year in range(2025, 2015, -1):
        add_folder("[COLOR lightgreen]%d[/COLOR]" % year, "/videos/%d" % year, media_icon("years"))
    xbmcplugin.endOfDirectory(HANDLE)


def categories_menu():
    categories = [
        ("Animációs", "/category/39"), ("Akció", "/category/28"),
        ("Horror", "/category/32"), ("Kaland", "/category/29"),
        ("Romantikus", "/category/31"), ("Sci-Fi", "/category/33"),
        ("Vígjáték", "/category/27"), ("Western", "/category/46"),
        ("Török", "/category/57"), ("Dráma", "/category/36"),
    ]
    xbmcplugin.setPluginCategory(HANDLE, "Filmek kategória szerint")
    for label, path in categories:
        add_folder("[COLOR tomato]%s[/COLOR]" % label, path, media_icon("categories"))
    xbmcplugin.endOfDirectory(HANDLE)


def open_search_results(query):
    query = (query or "").strip()
    if not query:
        return
    # Render the result directory directly in the current plugin invocation.
    # Android Kodi can silently ignore Container.Update() when it is called
    # immediately after Dialog.input(), leaving an empty/flickering container.
    search_url = get_url("?" + urlencode({"search": query}))
    open_listing(search_url, "Keresés: " + query)


def search():
    keyboard = xbmcgui.Dialog().input("Keresés", type=xbmcgui.INPUT_ALPHANUM)
    if not keyboard:
        xbmcgui.Dialog().notification("NapiFilm", "A keresés üres maradt", xbmcgui.NOTIFICATION_INFO, 2500)
        return
    keyboard = keyboard.strip()
    if not keyboard:
        return
    save_search(keyboard)
    # Keep search results in their own Kodi container so Android returns to
    # the result list after playback instead of reopening the input dialog.
    open_search_results(keyboard)


def previous_search(query):
    query = (query or "").strip()
    if not query:
        xbmcgui.Dialog().notification("NapiFilm", "Még nincs korábbi keresés", xbmcgui.NOTIFICATION_INFO, 2500)
        return
    open_search_results(query)


def search_menu():
    xbmcplugin.setPluginCategory(HANDLE, "Keresés")
    add_folder("[B][COLOR deepskyblue]ÚJ KERESÉS[/COLOR][/B]", "__new_search__", media_icon("search"))
    history = load_search_history()
    if history:
        for query in history:
            li = xbmcgui.ListItem(label="[COLOR lightblue]%s[/COLOR]" % query)
            li.setArt({"thumb": media_icon("search"), "icon": media_icon("search")})
            xbmcplugin.addDirectoryItem(HANDLE, build_plugin_url("previous", query), li, True)
    else:
        add_folder("[COLOR grey]NINCS KORÁBBI KERESÉS[/COLOR]", "", media_icon("search"), "previous")
    xbmcplugin.endOfDirectory(HANDLE)


params = dict(parse_qsl(urlparse(sys.argv[2]).query))
action = params.get("action", "")
if action == "play":
    detail(params.get("value", ""))
elif action == "search_results":
    query = params.get("value", "").strip()
    if query:
        open_search_results(query)
elif action == "series":
    series_detail(params.get("value", ""))
elif action == "season":
    season_detail(params.get("value", ""))
elif action == "noop":
    xbmcplugin.endOfDirectory(HANDLE)
elif params.get("value") == "__search__":
    search_menu()
elif params.get("value") == "__new_search__":
    search()
elif action == "previous":
    previous_search(params.get("value", ""))
elif params.get("value") == "__movies__":
    movies_menu()
elif params.get("value") == "__years__":
    years_menu()
elif params.get("value") == "__categories__":
    categories_menu()
elif action == "browse" and params.get("value"):
    open_listing(params["value"])
elif params.get("value"):
    open_listing(params["value"])
else:
    root()
