# -*- coding: utf-8 -*-
"""Filminvazio.cc katalogus plugin Kodi 21 (Omega) alatt.

A plugin csak a webhely nyilvanos HTML/AJAX valaszait hasznalja.
Nem kerul meg DRM-et, CAPTCHA-t, bejelentkezest vagy mas hozzaferes-vedelmet.
"""
from __future__ import absolute_import

import hashlib
import json
import os
import re
import sys
import time
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlparse, parse_qs, quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import json

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
    import zidervisionurlresolver
except ImportError:
    zidervisionurlresolver = None

BASE = "https://filminvazio.cc/"
SUBMITTED_BASE = "https://moziverzum.club/"
HANDLE = int(sys.argv[1])
ACCENT = "FF66D9EF"
GOLD = "FFFFC857"
MUTED = "FFB8C4D6"

ADDON = xbmcaddon.Addon()
ICON_DIR = os.path.join(ADDON.getAddonInfo("path"), "resources", "media")
GENRE_CATEGORIES = [
    ("Akció és kaland", "action-adventure"), ("Akció", "akcio-filmek-online"),
    ("Animáció", "animacio"), ("Animációs", "animacios"), ("Bűnügyi", "bunugyi"),
    ("Családi", "csaladi"), ("Dokumentum", "dokumentum"), ("Dokumentumfilm", "dokumentumfilm"),
    ("Dráma", "drama"), ("Életrajz", "eletrajz"), ("Életrajzi", "eletrajzi"),
    ("Fantasy", "fantasy"), ("Háborús", "haborus"), ("Harcművészeti", "harcmuveszeti"),
    ("Horror", "horror"), ("Kaland", "kaland"), ("Karácsonyi", "karacsonyi"),
    ("Katasztrófa", "katasztrofa"), ("Gyerek", "kids"), ("Külföldi", "kulfoldi"),
    ("Mesefilmek", "animacio-filmek-online"), ("Misztikus", "misztikus"),
    ("Musical", "musical"), ("Premier filmek", "premier-filmek"), ("Reality", "reality"),
    ("Rejtély", "rejtely"), ("Romantikus", "romantikus"), ("Rövidfilm", "rovidfilm"),
    ("Sci-Fi", "sci-fi"), ("Sci-Fi és fantasy", "sci-fi-fantasy"), ("Szappanopera", "soap"),
    ("Sport", "sport"), ("Talk-show", "talk"), ("Thriller", "thriller"),
    ("Történelmi", "tortenelmi"), ("Tévéfilm", "tv-film"), ("Vígjáték", "vigjatek"),
    ("Háború és politika", "war-politics"), ("Western", "western"), ("Zene", "zene"),
    ("Zenei", "zenei"),
]
YEAR_CATEGORIES = list(range(2026, 1976, -1))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
FETCH_STATS = {"cache": 0, "network": 0, "errors": 0, "cf": 0}
LOADING_DIALOG = None
SPINNER_INDEX = 0


def cache_enabled():
    return ADDON.getSetting("cache_enable").lower() != "false"


def cache_ttl():
    try:
        return max(60, int(ADDON.getSetting("cache_ttl") or "1800"))
    except ValueError:
        return 1800


def cache_dir():
    path = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))
    if not os.path.isdir(path):
        os.makedirs(path)
    path = os.path.join(path, "cache")
    if not os.path.isdir(path):
        os.makedirs(path)
    return path


def cache_path(url):
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return os.path.join(cache_dir(), key + ".html")


def cache_read(url):
    if not cache_enabled():
        return None
    path = cache_path(url)
    try:
        if time.time() - os.path.getmtime(path) > cache_ttl():
            return None
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except (OSError, IOError):
        return None


def cache_forget(url):
    try:
        os.remove(cache_path(url))
    except OSError:
        pass


def cache_write(url, body):
    if not cache_enabled():
        return
    try:
        with open(cache_path(url), "w", encoding="utf-8") as handle:
            handle.write(body)
    except (OSError, IOError) as exc:
        xbmc.log("Filminvaziocc cache write error: %s" % exc, xbmc.LOGDEBUG)


def cache_clear():
    removed = 0
    try:
        for name in os.listdir(cache_dir()):
            if name.endswith(".html"):
                try:
                    os.remove(os.path.join(cache_dir(), name))
                    removed += 1
                except OSError:
                    pass
    except OSError:
        pass
    xbmcgui.Dialog().notification("Filminvaziocc", "Cache törölve: %d oldal" % removed, xbmcgui.NOTIFICATION_INFO)


def flaresolverr_enabled():
    return ADDON.getSetting("fs_enable").lower() == "true"


def flaresolverr_request(url):
    endpoint = ADDON.getSetting("fs_host").strip() or "http://localhost:8191/v1"
    payload = json.dumps({"cmd": "request.get", "url": url, "maxTimeout": 60000}).encode("utf-8")
    req = Request(endpoint, data=payload, headers={"Content-Type": "application/json", "User-Agent": UA})
    with urlopen(req, timeout=70) as response:
        data = json.loads(response.read().decode("utf-8", "replace"))
    solution = data.get("solution", {})
    if data.get("status") != "ok" or solution.get("status") != 200:
        raise RuntimeError("FlareSolverr nem adott 200-as választ")
    return solution


def fetch(url, data=None):
    if data is None:
        cached = cache_read(url)
        if cached is not None:
            if is_cloudflare_challenge(cached):
                cache_forget(url)
                FETCH_STATS["cf"] += 1
                xbmc.log("Filminvaziocc CF checker rejected cached response: %s" % url, xbmc.LOGWARNING)
                return ""
            FETCH_STATS["cache"] += 1
            xbmc.log("Filminvaziocc cache hit: %s" % url, xbmc.LOGDEBUG)
            return cached
        FETCH_STATS["network"] += 1
    referer = SUBMITTED_BASE if "moziverzum.club" in url.lower() else BASE
    req = Request(url, data=data, headers={"User-Agent": UA, "Referer": referer, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "hu-HU,hu;q=0.9,en-US;q=0.8,en;q=0.7"})
    try:
        with urlopen(req, timeout=20) as response:
            body = response.read().decode("utf-8", "replace")
    except HTTPError as exc:
        FETCH_STATS["errors"] += 1
        if exc.code == 403:
            FETCH_STATS["cf"] += 1
            xbmc.log("Filminvaziocc CF checker rejected HTTP %s: %s" % (exc.code, url), xbmc.LOGWARNING)
            if data is None and flaresolverr_enabled():
                body = flaresolverr_request(url).get("response", "")
            else:
                return ""
        elif data is None and flaresolverr_enabled():
            body = flaresolverr_request(url).get("response", "")
        else:
            raise
    except Exception:
        FETCH_STATS["errors"] += 1
        if data is None and flaresolverr_enabled():
            body = flaresolverr_request(url).get("response", "")
        else:
            raise
    if data is None and is_cloudflare_challenge(body) and flaresolverr_enabled():
        body = flaresolverr_request(url).get("response", "")
    if is_cloudflare_challenge(body):
        FETCH_STATS["cf"] += 1
        xbmc.log("Filminvaziocc CF checker rejected response: %s" % url, xbmc.LOGWARNING)
        return ""
    if data is None:
        cache_write(url, body)
    return body


def fetch_final_url(url):
    """Follow a normal public redirect and return its final URL."""
    req = Request(url, headers={"User-Agent": UA, "Referer": SUBMITTED_BASE})
    try:
        with urlopen(req, timeout=20) as response:
            return response.geturl()
    except Exception:
        if flaresolverr_enabled():
            solution = flaresolverr_request(url)
            return solution.get("url", url)
        raise


def is_cloudflare_challenge(html):
    # A normál oldalak Cloudflare-szkriptjei is tartalmazhatják a
    # challenge-platform szót; csak tényleges challenge-oldal jeleit figyeljük.
    markers = (
        "Enable JavaScript and cookies to continue",
        "cf-chl-captcha-container",
        "cf-chl-widget",
        "Just a moment...",
        "Attention Required! | Cloudflare",
    )
    lower = html.lower()
    marked_as_challenge = any(marker.lower() in lower for marker in markers)
    if not marked_as_challenge:
        return False
    # Cloudflare-szkriptek megmaradhatnak egy már feloldott oldalon is.
    # Valódi Linkek-tábla esetén a tartalmat megtartjuk és feldolgozzuk.
    has_real_source_rows = bool(re.search(
        r'<tr\b[^>]*(?:id=[\'\"]link-|class=[\'\"][^\'\"]*(?:link|source))|class=[\'\"][^\'\"]*quality[\'\"]',
        html, re.I
    ))
    return not has_real_source_rows


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.current = None
        self.text = []
        self.images = {}
        self.meta = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and a.get("property") and a.get("content"):
            self.meta[a["property"]] = a["content"]
        if tag == "a" and a.get("href"):
            self.current = {"href": urljoin(BASE, a["href"]), "text": [], "img": ""}
            self.text = self.current["text"]
        elif tag == "img" and self.current is not None:
            self.current["img"] = a.get("data-wpfc-original-src") or a.get("src", "")

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            self.current["title"] = re.sub(r"\s+", " ", " ".join(self.current["text"])).strip()
            self.links.append(self.current)
            self.current = None
            self.text = []


def parse_page(html):
    p = PageParser()
    p.feed(html)
    return p


def set_video_info(item, info):
    if not info:
        return
    # Kodi 21 alatt az InfoTagVideo az ajánlott metaadat-API.
    tag = item.getVideoInfoTag() if hasattr(item, "getVideoInfoTag") else None
    if tag:
        if info.get("title"):
            tag.setTitle(info["title"])
        if info.get("plot"):
            tag.setPlot(info["plot"])
        if info.get("trailer") and hasattr(tag, "setTrailer"):
            tag.setTrailer(info["trailer"])
        tag.setMediaType(info.get("mediatype", "movie"))
    else:
        item.setInfo("video", info)


def notify(message, duration=1800):
    xbmcgui.Dialog().notification("Filminvaziocc", message, xbmcgui.NOTIFICATION_INFO, duration)


def loading_start(text="Könyvtár betöltése"):
    global LOADING_DIALOG, SPINNER_INDEX
    SPINNER_INDEX = 0
    try:
        LOADING_DIALOG = xbmcgui.DialogProgressBG()
        LOADING_DIALOG.create("Filminvaziocc", "◐ " + text)
    except Exception as exc:
        LOADING_DIALOG = None
        xbmc.log("Filminvaziocc progress start error: %s" % exc, xbmc.LOGDEBUG)


def loading_tick(text="Könyvtár betöltése", current=None, total=None):
    global SPINNER_INDEX
    if LOADING_DIALOG is None:
        return
    frames = ("◐", "◓", "◑", "◒")
    frame = frames[SPINNER_INDEX % len(frames)]
    SPINNER_INDEX += 1
    if current is not None and total:
        text = "%s %d/%d" % (text, current, total)
    try:
        # 0: a Kodi ne jelenítsen meg százalékos előrehaladást; a sorszám a szövegben látszik.
        LOADING_DIALOG.update(0, "Filminvaziocc", frame + " " + text)
    except Exception:
        pass


def loading_stop():
    global LOADING_DIALOG
    if LOADING_DIALOG is not None:
        try:
            LOADING_DIALOG.close()
        except Exception:
            pass
        LOADING_DIALOG = None


def add_item(label, path, folder=True, art=None, info=None, icon=None):
    li = xbmcgui.ListItem(label=label)
    if art:
        li.setArt({"thumb": art, "poster": art})
    if icon:
        li.setArt({"icon": icon})
    set_video_info(li, info)
    if not folder:
        li.setProperty("IsPlayable", "true")
    xbmcplugin.addDirectoryItem(HANDLE, path, li, folder)


def plugin_url(**kwargs):
    return sys.argv[0] + "?" + urlencode(kwargs)


def colorize(text, color=ACCENT):
    return "[COLOR %s]%s[/COLOR]" % (color, text)


def clean_links(parser, html="", include_featured=True):
    seen, out = set(), []
    featured_hrefs = set()
    if not include_featured:
        for featured_block in re.findall(r"<article\b[^>]*id=[\'\"]post-featured-\d+[\'\"][^>]*>.*?</article>", html, re.I | re.S):
            for featured_href in re.findall(r"href=[\'\"](https?://filminvazio\.cc)?(/film/[^\'\"?#]+)", featured_block, re.I):
                featured_hrefs.add(urljoin(BASE, featured_href[1]))
    # A filmkártyán a poster és a cím gyakran külön <a> elemben van.
    # Először a teljes article-blokkból párosítjuk őket.
    for block in re.findall(r"<article\b.*?</article>", html, re.I | re.S):
        if not include_featured and "post-featured-" in block.lower():
            continue
        href_match = re.search(r"href=[\'\"](https?://filminvazio\.cc)?(/film/[^\'\"?#]+)", block, re.I)
        if not href_match:
            continue
        href = urljoin(BASE, href_match.group(2))
        title_match = re.search(r"<(?:h1|h2|h3|h4)[^>]*>.*?<a[^>]*>(.*?)</a>", block, re.I | re.S)
        alt_match = re.search(r"alt=[\'\"]([^\'\"]+)[\'\"]", block, re.I)
        title = title_match.group(1) if title_match else (alt_match.group(1) if alt_match else "")
        title = re.sub(r"<[^>]+>", "", unescape(title)).strip()
        image_match = re.search(r"data-wpfc-original-src=[\'\"]([^\'\"]+)[\'\"]", block, re.I)
        if not image_match:
            image_match = re.search(r"<img[^>]+src=[\'\"]([^\'\"]+)[\'\"]", block, re.I)
        image = image_match.group(1) if image_match else ""
        if title and href not in seen:
            seen.add(href)
            out.append((title, href, image))
    # Tartalék a nem article formátumú oldalakhoz, például keresési kártyákhoz.
    if not out:
        for match in re.finditer(r'<a[^>]+href=[\'\"](https?://filminvazio\.cc)?(/film/[^\'\"?#]+)[^>]*>(.*?)</a>', html, re.I | re.S):
            href = urljoin(BASE, match.group(2))
            if href in featured_hrefs:
                continue
            if re.search(r"/page/\d+$", urlparse(href).path.rstrip("/"), re.I):
                continue
            title = re.sub(r'<[^>]+>', '', unescape(match.group(3))).strip()
            if not title:
                continue
            if href not in seen and title.lower() not in ("online filmek", "film info", "linkek"):
                seen.add(href)
                out.append((title, href, ''))
    for link in parser.links:
        href = link["href"]
        path = urlparse(href).path.rstrip("/")
        if re.search(r"/page/\d+$", path, re.I):
            continue
        if href in featured_hrefs:
            continue
        if "/film/" not in path or href.rstrip("/") == BASE.rstrip("/"):
            continue
        title = link.get("title", "").strip()
        if not title or title.lower() in ("online filmek", "film info", "linkek") or href in seen:
            continue
        seen.add(href)
        out.append((title, href, link.get("img", "")))
    return out


def featured_links(html):
    # Csak a kezdőoldal #featured-titles carousel post-featured cikkeit olvassuk.
    blocks = re.findall(r'<article\b[^>]*id=[\'\"]post-featured-\d+[\'\"][^>]*>.*?</article>', html, re.I | re.S)
    featured_html = "\n".join(blocks)
    return clean_links(parse_page(featured_html), featured_html)


def source_entries(html):
    entries = []
    pattern = r"<li\b[^>]*data-nume=[\'\"](\d+)[\'\"][^>]*>.*?</li>"
    for match in re.finditer(pattern, html, re.I | re.S):
        block = match.group(0)
        nume = match.group(1)
        host_match = re.search(r"class=[\'\"][^\'\"]*server[^\'\"]*[\'\"][^>]*>(.*?)</span>", block, re.I | re.S)
        host = re.sub(r"<[^>]+>", "", host_match.group(1)).strip() if host_match else "ismeretlen host"
        entries.append((nume, unescape(host)))
    return entries


def clean_plot(text):
    """Remove the site's trailing author/source marker from the plot."""
    text = re.sub(r'<[^>]+>', ' ', unescape(text))
    text = re.sub(r'\s+', ' ', text).strip()
    # The site appends markers such as '(Hieronymus Bosch)' or '(Csillag Lajos)R3'.
    text = re.sub(r'\s*\([^()]{2,100}\)\s*R?\d*\s*$', '', text, flags=re.I).strip()
    text = re.sub(r'\s+R\d+\s*$', '', text, flags=re.I).strip()
    return text


def submitted_entries(html):
    """Read public submitted-link rows from the moziverzum links table."""
    entries = []
    rows = re.findall(r'<tr\b[^>]*>.*?</tr>', html, re.I | re.S)
    for raw_row in rows:
        row = unescape(raw_row)
        redirect = re.search(r'window\.open\([\'\"](https?://moziverzum\.club/links/[^\'\"]+)', row, re.I)
        if not redirect:
            redirect = re.search(r'href=[\'\"](https?://moziverzum\.club/links/[^\'\"]+)', row, re.I)
        provider = re.search(r'<td[^>]*>.*?<a[^>]*>(.*?)</a>', row, re.I | re.S)
        quality = re.search(r'class=[\'\"][^\'\"]*quality[^\'\"]*[\'\"]>(.*?)</', row, re.I | re.S)
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.I | re.S)
        if not redirect or not provider:
            continue
        host = re.sub(r'<[^>]+>', '', unescape(provider.group(1))).strip()
        level = re.sub(r'<[^>]+>', '', unescape(quality.group(1))).strip() if quality else ''
        language = re.sub(r'<[^>]+>', ' ', unescape(cells[2])).strip() if len(cells) > 2 else ''
        language = re.sub(r'\s+', ' ', language)
        entries.append({"host": host, "quality": level, "language": language, "redirect": redirect.group(1)})
    return entries


def extract_youtube_id(value):
    """Extract a YouTube ID from a watch/embed/template URL or HTML fragment."""
    if not value:
        return ""
    patterns = (
        r'youtube\.html#([A-Za-z0-9_-]{6,})',
        r'youtube\.com/(?:embed/|watch\?[^\"\' ]*v=)([A-Za-z0-9_-]{6,})',
        r'youtu\.be/([A-Za-z0-9_-]{6,})',
    )
    for pattern in patterns:
        match = re.search(pattern, value, re.I)
        if match:
            return match.group(1)
    return ""


def extract_movie_meta(html, title=""):
    """Extract plot and YouTube trailer from a public movie detail page."""
    plot = ""
    paragraph = re.search(
        r'<div[^>]+class=[\'\"][^\'\"]*wp-content[^\'\"]*[\'\"][^>]*>.*?<p[^>]*>(.*?)</p>',
        html, re.I | re.S
    )
    if paragraph:
        plot = clean_plot(paragraph.group(1))
    trailer = ""
    trailer_block = re.search(r'<div[^>]+id=[\'\"]trailer[\'\"][^>]*>.*?</div>\s*</div>\s*</div>', html, re.I | re.S)
    trailer_source = trailer_block.group(0) if trailer_block else html
    video_id = extract_youtube_id(trailer_source)
    if video_id:
        trailer = "https://www.youtube.com/watch?v=" + video_id
    return {"title": title, "plot": plot, "trailer": trailer, "mediatype": "movie"}


def category_menu():
    items = [
        (colorize("Műfajok", ACCENT), plugin_url(action="category_group", group="genres"), True, os.path.join(ICON_DIR, "popular.png")),
        (colorize("Évek", ACCENT), plugin_url(action="category_group", group="years"), True, os.path.join(ICON_DIR, "movies.png")),
    ]
    for title, path, is_folder, icon in items:
        add_item(title, path, is_folder, icon=icon)
    xbmcplugin.endOfDirectory(HANDLE)


def category_group(group):
    if group == "genres":
        items = [(label, BASE + "filmek/" + slug) for label, slug in GENRE_CATEGORIES]
    else:
        items = [(str(year), BASE + "online-filmek/%d/" % year) for year in YEAR_CATEGORIES]
    for label, url in items:
        add_item(colorize(label, ACCENT), plugin_url(action="listing", url=url), True, icon=os.path.join(ICON_DIR, "movies.png"))
    xbmcplugin.endOfDirectory(HANDLE)


def home():
    items = [
        (colorize("Online filmek", ACCENT), plugin_url(action="listing", url=BASE + "film"), True, os.path.join(ICON_DIR, "movies.png")),
        (colorize("2026-os filmek", ACCENT), plugin_url(action="listing", url=BASE + "online-filmek/2026/"), True, os.path.join(ICON_DIR, "movies.png")),
        (colorize("2025-os filmek", ACCENT), plugin_url(action="listing", url=BASE + "online-filmek/2025/"), True, os.path.join(ICON_DIR, "movies.png")),
        (colorize("Legújabb premierek", GOLD), plugin_url(action="featured"), True, os.path.join(ICON_DIR, "premieres.png")),
        (colorize("Premier filmek", GOLD), plugin_url(action="listing", url=BASE + "filmek/premier-filmek/"), True, os.path.join(ICON_DIR, "premieres.png")),
        (colorize("Legnézettebb", GOLD), plugin_url(action="listing", url=BASE + "trending"), True, os.path.join(ICON_DIR, "popular.png")),
        (colorize("Kategóriák", ACCENT), plugin_url(action="category_menu"), True, os.path.join(ICON_DIR, "popular.png")),
        (colorize("Cache törlése", MUTED), plugin_url(action="cache_clear"), False, os.path.join(ICON_DIR, "cache.png")),
    ]
    xbmc.log("Filminvaziocc home: menu_items=%d" % len(items), xbmc.LOGDEBUG)
    for title, path, is_folder, icon in items:
        add_item(title, path, is_folder, icon=icon)
    xbmcplugin.endOfDirectory(HANDLE)


def featured():
    loading_start("Premierlista betöltése")
    try:
        html = fetch(BASE)
        xbmc.log("Filminvaziocc featured: fetched html_bytes=%d challenge=%s" % (len(html), is_cloudflare_challenge(html)), xbmc.LOGDEBUG)
        if is_cloudflare_challenge(html):
            xbmc.log("Filminvaziocc featured page returned a Cloudflare challenge", xbmc.LOGWARNING)
            xbmcplugin.endOfDirectory(HANDLE)
            return
        films = featured_links(html)
        xbmc.log("Filminvaziocc featured: carousel_cards=%d target=%s" % (len(films), any('csak-egy-ejszaka' in href for _, href, _ in films)), xbmc.LOGDEBUG)
        total_films = len(films)
        skipped_cf = 0
        loaded_films = 0
        for index, (title, href, image) in enumerate(films, 1):
            loading_tick("Film betöltése", index, total_films)
            info = {"title": title, "mediatype": "movie"}
            try:
                cf_before = FETCH_STATS["cf"]
                detail_html = fetch(href)
                if FETCH_STATS["cf"] > cf_before:
                    skipped_cf += 1
                    xbmc.log("Filminvaziocc featured skipped by CF: %s" % href, xbmc.LOGWARNING)
                    continue
                if not detail_html:
                    xbmc.log("Filminvaziocc featured skipped without detail HTML: %s" % href, xbmc.LOGDEBUG)
                    continue
                info.update(extract_movie_meta(detail_html, title))
            except Exception as exc:
                xbmc.log("Filminvaziocc featured metadata error: %s" % exc, xbmc.LOGDEBUG)
                continue
            add_item(title, plugin_url(action="movie", url=href), True, image, info)
            loaded_films += 1
        loading_stop()
        notify("%d film betöltve" % loaded_films, 1800)
        if skipped_cf:
            notify("%d film kihagyva Cloudflare-védelem miatt" % skipped_cf, 3500)
    except Exception as exc:
        xbmc.log("Filminvazio featured error: %s" % exc, xbmc.LOGERROR)
        notify("A könyvtár nem tölthető be", 2500)
    xbmcplugin.endOfDirectory(HANDLE)


def listing(url):
    loading_start("Könyvtár betöltése")
    try:
        html = fetch(url)
        xbmc.log("Filminvaziocc listing: url=%s html_bytes=%d challenge=%s" % (url, len(html), is_cloudflare_challenge(html)), xbmc.LOGDEBUG)
        if is_cloudflare_challenge(html):
            xbmc.log("Filminvaziocc search page returned a Cloudflare challenge", xbmc.LOGWARNING)
            xbmcplugin.endOfDirectory(HANDLE)
            return
        parser = parse_page(html)
        films = clean_links(parser, html, include_featured=False)
        xbmc.log("Filminvaziocc listing: films=%d target=%s" % (len(films), any('csak-egy-ejszaka' in href for _, href, _ in films)), xbmc.LOGDEBUG)
        total_films = len(films)
        skipped_cf = 0
        loaded_films = 0
        for index, (title, href, image) in enumerate(films, 1):
            loading_tick("Film betöltése", index, total_films)
            info = {"title": title, "mediatype": "movie"}
            try:
                cf_before = FETCH_STATS["cf"]
                detail_html = fetch(href)
                if FETCH_STATS["cf"] > cf_before:
                    skipped_cf += 1
                    xbmc.log("Filminvaziocc listing skipped by CF: %s" % href, xbmc.LOGWARNING)
                    continue
                if not detail_html:
                    xbmc.log("Filminvaziocc listing skipped without detail HTML: %s" % href, xbmc.LOGDEBUG)
                    continue
                info.update(extract_movie_meta(detail_html, title))
            except Exception as exc:
                xbmc.log("Filminvaziocc metadata error: %s" % exc, xbmc.LOGDEBUG)
                continue
            add_item(title, plugin_url(action="movie", url=href), True, image, info)
            loaded_films += 1
        add_next_page(url, html)
        loading_stop()
        notify("%d film betöltve" % loaded_films, 1800)
        if skipped_cf:
            notify("%d film kihagyva Cloudflare-védelem miatt" % skipped_cf, 3500)
    except Exception as exc:
        xbmc.log("Filminvazio listing error: %s" % exc, xbmc.LOGERROR)
        notify("A könyvtár nem tölthető be", 2500)
    xbmcplugin.endOfDirectory(HANDLE)


def add_next_page(url, html):
    path = urlparse(url).path.rstrip('/')
    current_match = re.search(r'/page/(\d+)/?$', path, re.I)
    current_page = int(current_match.group(1)) if current_match else 1
    candidates = []
    next_url = ''
    for href in re.findall(r'href=[\'\"]([^\'\"]+)[\'\"]', html, re.I):
        page_match = re.search(r'/page/(\d+)(?:/|$)', href, re.I)
        if page_match:
            page = int(page_match.group(1))
            candidates.append(page)
            if page == current_page + 1:
                next_url = urljoin(url, href)
    total_pages = max([current_page] + candidates)
    if not next_url or current_page >= total_pages:
        xbmc.log("Filminvaziocc pagination: current=%d total=%d next=none" % (current_page, total_pages), xbmc.LOGDEBUG)
        return
    label = colorize("Következő oldal — %d/%d" % (current_page, total_pages), ACCENT)
    xbmc.log("Filminvaziocc pagination: current=%d total=%d next=%s" % (current_page, total_pages, next_url), xbmc.LOGDEBUG)
    add_item(label, plugin_url(action="listing", url=next_url), True)


def cache_menu():
    cache_clear()
    xbmcplugin.endOfDirectory(HANDLE)


def search():
    keyboard = xbmc.Keyboard("", "Film kereső")
    keyboard.doModal()
    if not keyboard.isConfirmed():
        xbmcplugin.endOfDirectory(HANDLE)
        return
    term = keyboard.getText().strip()
    if term:
        listing(BASE + "?" + urlencode({"s": term}))
    else:
        xbmcplugin.endOfDirectory(HANDLE)


def get_submitted_entries_for_movie(url):
    """Fetch and parse the public moziverzum link table for a movie."""
    submitted = []
    cf_before = FETCH_STATS["cf"]
    try:
        slug = urlparse(url).path.rstrip('/').split('/')[-1]
        submitted_page = urljoin(SUBMITTED_BASE, 'film/' + slug + '/')
        submitted_html = fetch(submitted_page)
        if submitted_html:
            submitted = submitted_entries(submitted_html)
            if not submitted:
                cache_forget(submitted_page)
                submitted = submitted_entries(fetch(submitted_page))
        xbmc.log("Filminvaziocc submitted links: page=%s entries=%d" % (submitted_page, len(submitted)), xbmc.LOGDEBUG)
    except Exception as exc:
        xbmc.log("Filminvaziocc submitted-links error: %s" % exc, xbmc.LOGDEBUG)
    return submitted, FETCH_STATS["cf"] > cf_before


def movie(url):
    loading_start("Film adatlap betöltése")
    cf_before = FETCH_STATS["cf"]
    try:
        html = fetch(url)
    except Exception as exc:
        xbmc.log("Filminvaziocc movie page error: %s" % exc, xbmc.LOGWARNING)
        html = ""
    if not html:
        loading_stop()
        if FETCH_STATS["cf"] > cf_before:
            xbmcgui.Dialog().ok("Filminvázió", "A film adatlapja Cloudflare-védelem miatt nem olvasható.")
        else:
            xbmcgui.Dialog().ok("Filminvázió", "A film adatlapja nem tölthető be.")
        xbmcplugin.endOfDirectory(HANDLE)
        return
    parser = parse_page(html)
    title_match = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
    title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else url.rstrip("/").split("/")[-1]
    title = unescape(re.sub(r"\s+", " ", title))
    poster = parser.meta.get("og:image", "")
    post = re.search(r"data-post=['\"](\d+)", html)
    entries = source_entries(html)
    notify("%d saját forrás található" % len(entries), 1600)
    if not entries:
        entries = [(nume, "ismeretlen host") for nume in sorted(set(re.findall(r"data-nume=['\"](\d+)", html)))]
    info = extract_movie_meta(html, title)
    submitted, submitted_cf = get_submitted_entries_for_movie(url)
    if not entries and not submitted:
        loading_stop()
        if submitted_cf:
            xbmcgui.Dialog().ok("Filminvázió", "Ehhez a filmhez a moziverzum.club Cloudflare-védelme miatt nem olvashatók a források.")
        else:
            xbmcgui.Dialog().ok("Filminvázió", "Ehhez az oldalhoz nem található nyilvános lejátszóforrás.")
        xbmcplugin.endOfDirectory(HANDLE)
        return
    # Csak valódi, kiolvasott YouTube-előzetesnél jelenítünk meg külön sort.
    # Az üres #trailer fül önmagában nem bizonyítja, hogy van lejátszható trailer.
    if info.get("trailer"):
        trailer_label = colorize("Előzetes: %s" % title, GOLD)
        add_item(trailer_label, plugin_url(action="trailer", url=info["trailer"], title=title), False, poster, info)
    for index, (nume, host) in enumerate(entries, 1):
        loading_tick("Forrás betöltése", index, len(entries))
        label = "%s – %s" % (title, colorize(host, ACCENT))
        add_item(label, plugin_url(action="play", post=post.group(1), nume=nume, page=url, title=title), False, poster, info)
    for index, entry in enumerate(submitted, 1):
        loading_tick("Beküldött forrás", index, len(submitted))
        quality = colorize(entry["quality"], GOLD) if entry["quality"] else ''
        label = "%s – %s%s" % (title, colorize(entry["host"], ACCENT), (" – " + quality) if quality else '')
        add_item(label, plugin_url(action="submitted", redirect=entry["redirect"], title=title), False, poster, info)

    loading_stop()
    xbmcplugin.endOfDirectory(HANDLE)


def play_submitted(redirect, title):
    try:
        provider_url = fetch_final_url(redirect)
        media_url = resolve_embed(provider_url)
        if media_url:
            item = xbmcgui.ListItem(label=title, path=media_url)
            item.setProperty("IsPlayable", "true")
            set_video_info(item, {"title": title, "mediatype": "movie"})
            xbmcplugin.setResolvedUrl(HANDLE, True, item)
            return
    except Exception as exc:
        xbmc.log("Filminvaziocc submitted resolver error: %s" % exc, xbmc.LOGWARNING)
    xbmcgui.Dialog().ok("Filminvaziocc", "A beküldött link nem oldható fel.")


def trailer(url, title):
    video_id = extract_youtube_id(url)
    if not video_id and not urlparse(url).netloc.endswith("youtube.com"):
        try:
            video_id = extract_youtube_id(fetch(url))
        except Exception as exc:
            xbmc.log("Filminvaziocc trailer page error: %s" % exc, xbmc.LOGDEBUG)
    if video_id:
        youtube_path = "plugin://plugin.video.youtube/play/?video_id=" + quote(video_id)
        item = xbmcgui.ListItem(label=title + " - Előzetes", path=youtube_path)
        item.setProperty("IsPlayable", "true")
        set_video_info(item, {"title": title + " - Előzetes", "mediatype": "video"})
        xbmcplugin.setResolvedUrl(HANDLE, True, item)
    else:
        xbmcgui.Dialog().ok("Filminvaziocc", "Az előzetes YouTube-azonosítója nem olvasható ki.")


def resolve_embed(embed):
    # Elsődlegesen a felhasználó saját ZiderVision resolverét használjuk.
    # Ez Videa, IndaVideo és VK Video URL-ekhez adhat közvetlen médiaURL-t.
    if zidervisionurlresolver is not None:
        try:
            result = zidervisionurlresolver.resolve(embed)
            if isinstance(result, dict):
                result = result.get("url") or result.get("stream_url")
            if result:
                xbmc.log("Filminvaziocc: ZiderVision resolver selected", xbmc.LOGINFO)
                return result
        except Exception as exc:
            xbmc.log("Filminvaziocc ZiderVision resolver error: %s" % exc, xbmc.LOGWARNING)
    # Második lehetőségként a standard ResolveURL következik, például OK.ru-hoz.
    if resolveurl is not None:
        try:
            media = resolveurl.HostedMediaFile(url=embed)
            if media.valid_url():
                result = media.resolve()
                if result:
                    xbmc.log("Filminvaziocc: standard ResolveURL selected", xbmc.LOGINFO)
                    return result
        except Exception as exc:
            xbmc.log("Filminvaziocc ResolveURL error: %s" % exc, xbmc.LOGWARNING)
    return None


def play(post, nume, title, page=None):
    # A film adatlapján szereplő összes forrást sorrendben próbáljuk meg.
    # Így egy törölt OK.ru link esetén a következő, például Videa-forrás
    # automatikusan használható, ha azt a ResolveURL támogatja.
    sources = [str(nume)]
    if page:
        try:
            html = fetch(page)
            sources = sorted(set(re.findall(r"data-nume=['\"](\d+)", html)), key=int)
            if str(nume) in sources:
                sources.remove(str(nume))
                sources.insert(0, str(nume))
        except Exception as exc:
            xbmc.log("Filminvaziocc source list error: %s" % exc, xbmc.LOGWARNING)
    for source in sources:
        payload = urlencode({"action": "doo_player_ajax", "post": post, "nume": source, "type": "movie"}).encode("ascii")
        try:
            data = json.loads(fetch(urljoin(BASE, "wp-admin/admin-ajax.php"), payload))
        except Exception as exc:
            xbmc.log("Filminvaziocc player response error: %s" % exc, xbmc.LOGWARNING)
            continue
        embed = data.get("embed_url", "")
        media_url = resolve_embed(embed)
        if media_url:
            item = xbmcgui.ListItem(label=title, path=media_url)
            item.setProperty("IsPlayable", "true")
            set_video_info(item, {"title": title, "mediatype": "movie"})
            item.setMimeType("video/mp4")
            xbmcplugin.setResolvedUrl(HANDLE, True, item)
            return
    xbmcgui.Dialog().ok(
        "Filminvaziocc",
        "A filmhez tartozó nyilvános források egyike sem oldható fel ResolveURL-lal."
    )


def main():
    query = parse_qs(urlparse(sys.argv[2]).query)
    action = query.get("action", [""])[0]
    xbmc.log("Filminvaziocc dispatch: action=%s raw_query=%s" % (action, sys.argv[2]), xbmc.LOGDEBUG)
    if not action:
        home()
    elif action == "listing":
        listing(query["url"][0])
    elif action == "featured":
        featured()
    elif action == "category_menu":
        category_menu()
    elif action == "category_group":
        category_group(query.get("group", ["genres"])[0])
    elif action == "search":
        search()
    elif action == "cache_clear":
        cache_menu()
    elif action == "movie":
        movie(query["url"][0])
    elif action == "trailer":
        trailer(query["url"][0], query.get("title", [""])[0])
    elif action == "submitted":
        play_submitted(query["redirect"][0], query.get("title", [""])[0])
    elif action == "play":
        play(query["post"][0], query["nume"][0], query.get("title", [""])[0], query.get("page", [None])[0])


if __name__ == "__main__":
    main()
