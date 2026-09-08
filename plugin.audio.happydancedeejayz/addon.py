# -*- coding: utf-8 -*-
"""HappyDanceDeejayz audio plugin for Kodi 21.3."""
from urllib.parse import parse_qs, quote_plus, urlencode, urljoin, urlparse
from html.parser import HTMLParser
from html import unescape
import re
import sys
import os
from urllib.request import Request, urlopen

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

try:
    import resolveurl
except ImportError:
    resolveurl = None

ADDON = xbmcaddon.Addon()
HANDLE = int(sys.argv[1])
BASE = "https://www.happydancedeejayz.hu/"
FEED = urljoin(BASE, "feed/")
USER_AGENT = "Mozilla/5.0 (Kodi; HappyDanceDeejayz addon)"
ADDON_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo("path"))
FANART = os.path.join(ADDON_PATH, "fanart.jpg")
CATEGORY_SLUGS = {
    "Dance / Hands Up!": "dance-hands-up",
    "Trance": "trance",
    "House": "house",
    "Egyéb": "egyeb",
    "Promo": "promo",
}


def notify(message, level=xbmcgui.NOTIFICATION_INFO):
    xbmcgui.Dialog().notification("HappyDanceDeejayz", message, level, 5000)


def progress_create(title, total):
    progress = xbmcgui.DialogProgress()
    progress.create("HappyDanceDeejayz", "[COLOR cyan]" + title + "[/COLOR]")
    progress.update(0, "[COLOR lightblue]0/%d elem[/COLOR]" % total)
    return progress


def fetch(url):
    try:
        request = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=20) as response:
            data = response.read()
        return data.decode("utf-8", "replace") if isinstance(data, bytes) else (data or "")
    except Exception as exc:
        xbmc.log("HappyDanceDeejayz HTTP: %s" % exc, xbmc.LOGWARNING)
        return ""


def follow_redirect(url, referer=""):
    """Follow the site's click redirect and return the final URL and body."""
    try:
        headers = {"User-Agent": USER_AGENT}
        if referer:
            headers["Referer"] = referer
        request = Request(url, headers=headers)
        with urlopen(request, timeout=30) as response:
            data = response.read()
            if isinstance(data, bytes):
                data = data.decode("utf-8", "replace")
            return response.geturl(), data or ""
    except Exception as exc:
        xbmc.log("HappyDanceDeejayz redirect: %s" % exc, xbmc.LOGWARNING)
        return url, ""


def text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def xml_text(item, tag):
    match = re.search(r"<%s(?:\s[^>]*)?>(.*?)</%s>" % (tag, tag), item, re.I | re.S)
    if not match:
        return ""
    return unescape(text(re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", match.group(1), flags=re.S)))


def feed_items(feed_url=FEED):
    raw = fetch(feed_url)
    items = []
    for block in re.findall(r"<item>(.*?)</item>", raw, re.I | re.S):
        title = xml_text(block, "title")
        url = xml_text(block, "link")
        category = xml_text(block, "category")
        description = xml_text(block, "description")
        if title and url:
            items.append({"title": title, "url": url, "category": category,
                          "description": description})
    return items


def category_feed(category, page=1):
    slug = CATEGORY_SLUGS.get(category, "")
    if not slug:
        return FEED
    page_path = "category/mixx/%s/" % slug
    if page > 1:
        page_path += "page/%d/" % page
    return urljoin(BASE, page_path + "feed/")


def category_page(category, page=1):
    slug = CATEGORY_SLUGS.get(category, "")
    if not slug:
        return BASE
    path = "category/mixx/%s/" % slug
    if page > 1:
        path += "page/%d/" % page
    return urljoin(BASE, path)


def category_items(category, page=1, progress=None):
    """Read the site's actual paginated category HTML, not the RSS limit."""
    raw = fetch(category_page(category, page))
    items = []
    seen = set()
    pattern = r'<a[^>]+href=["\']([^"\']+\.music)["\'][^>]*>(.*?)</a>'
    for match in re.finditer(pattern, raw, re.I | re.S):
        url = urljoin(BASE, match.group(1))
        title = unescape(text(re.sub(r"<[^>]+>", " ", match.group(2))))
        if url in seen or not title:
            continue
        seen.add(url)
        post = fetch(url)
        heading = re.search(r"<h1[^>]*>(.*?)</h1>", post, re.I | re.S)
        full_title = unescape(text(re.sub(r"<[^>]+>", " ", heading.group(1)))) if heading else title
        items.append({"title": full_title or title, "url": url,
                      "category": category, "description": ""})
        if progress:
            progress.update(len(items) * 5, "[COLOR lightblue]Címek betöltése: %d/10[/COLOR]" % len(items))
        if len(items) == 10:
            break
    return items


def item_is_available(item):
    """Keep only posts whose download redirect still reaches a live host page."""
    try:
        download, _, _, _ = post_details(item)
        if not download:
            return False
        final_url, body = follow_redirect(download, item["url"])
        if not body or "mediafire.com" not in final_url.lower():
            return False
        lowered = body.lower()
        return "download" in lowered and "file not found" not in lowered
    except Exception as exc:
        xbmc.log("HappyDanceDeejayz availability check: %s" % exc, xbmc.LOGWARNING)
        return False


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.image = ""
        self.youtube = ""
        self.in_title = False
        self.title = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag.lower() == "a" and attrs.get("href"):
            self.links.append((text(attrs.get("href")), attrs.get("href")))
        if tag.lower() == "meta" and attrs.get("property", "").lower() == "og:image":
            self.image = attrs.get("content", "")
        if tag.lower() == "img" and not self.image:
            candidate = attrs.get("data-src") or attrs.get("data-lazy-src") or attrs.get("src", "")
            if not candidate.startswith("data:image"):
                self.image = candidate
        if tag.lower() in ("iframe", "a"):
            candidate = attrs.get("src") or attrs.get("href") or ""
            if "youtube.com" in candidate or "youtu.be" in candidate:
                self.youtube = candidate
        if tag.lower() == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)


def post_details(item):
    raw = fetch(item["url"])
    parser = LinkParser()
    parser.feed(raw)
    download = ""
    for label, href in parser.links:
        if label.lower() == "download" or "dl/click.php" in href:
            download = urljoin(item["url"], href)
            break
    image = urljoin(item["url"], parser.image) if parser.image else ""
    content_match = re.search(r'<div[^>]+class=["\'][^"\']*new_data[^"\']*["\'][^>]*>(.*?)</div>\s*</div>', raw, re.I | re.S)
    content = content_match.group(1) if content_match else raw
    content = re.sub(r"<script.*?</script>|<style.*?</style>", " ", content, flags=re.I | re.S)
    content = re.sub(r"<br\s*/?>", "\n", content, flags=re.I)
    content = re.sub(r"</p>", "\n\n", content, flags=re.I)
    body = unescape(re.sub(r"<[^>]+>", " ", content))
    body = "\n".join(line.strip() for line in body.splitlines() if line.strip())
    youtube = parser.youtube
    if not youtube:
        match = re.search(r"https?://www\.youtube\.com/(?:embed/|watch\?v=)[^\"'<> ]+", raw, re.I)
        youtube = match.group(0) if match else ""
    return download, image, body, youtube


def build_url(action, **kwargs):
    query = urlencode({"action": action, **kwargs})
    return sys.argv[0] + "?" + query


def add_folder(label, action, **kwargs):
    li = xbmcgui.ListItem(label=label)
    li.setArt({"fanart": FANART})
    xbmcplugin.addDirectoryItem(HANDLE, build_url(action, **kwargs), li, True)


def add_mix(item, progress=None, index=0, total=0):
    _, image, details, youtube = post_details(item)
    li = xbmcgui.ListItem(label=item["title"] + "  [COLOR magenta][MediaFire][/COLOR]")
    li.setInfo("music", {"title": item["title"], "genre": item.get("category", ""),
                          "comment": details, "plot": details,
                          "description": details})
    li.setProperty("description", details)
    li.setProperty("IsPlayable", "true")
    li.setArt({"thumb": image or FANART, "icon": image or FANART, "fanart": FANART})
    li.addContextMenuItems([
        ("Mix információk / Tracklist", "RunPlugin(%s)" %
         build_url("details", url=item["url"], title=item["title"]))
    ])
    xbmcplugin.addDirectoryItem(HANDLE, build_url("play", url=item["url"],
                              title=item["title"]), li, False)
    # Add a separate preview entry when the post embeds a YouTube video.
    if youtube:
        video_id = re.search(r"(?:embed/|v=)([A-Za-z0-9_-]{6,})", youtube)
        if video_id:
            preview = xbmcgui.ListItem(label=item["title"] + "  [COLOR red][YouTube][/COLOR]")
            preview.setProperty("IsPlayable", "true")
            preview.setArt({"thumb": image or FANART, "icon": image or FANART, "fanart": FANART})
            preview_url = "plugin://plugin.video.youtube/play/?video_id=" + video_id.group(1)
            xbmcplugin.addDirectoryItem(HANDLE, preview_url, preview, False)
    if progress and total:
        progress.update(int(index * 100 / total),
                        "[COLOR lightblue]%d/%d[/COLOR]  %s" % (index, total, item["title"]))


def list_home():
    add_folder("Friss mixek", "recent")
    add_folder("Dance / Hands Up!", "category", name="Dance / Hands Up!")
    add_folder("Trance", "category", name="Trance")
    add_folder("House", "category", name="House")
    add_folder("Egyéb", "category", name="Egyéb")
    add_folder("Promo", "category", name="Promo")
    add_folder("Keresés", "search")
    xbmcplugin.endOfDirectory(HANDLE)


def list_items(items):
    if not items:
        notify("Nem található mix", xbmcgui.NOTIFICATION_WARNING)
    progress = progress_create("Friss mixek betöltése", len(items)) if items else None
    for index, item in enumerate(items, 1):
        add_mix(item, progress, index, len(items))
    if progress:
        progress.close()
    xbmcplugin.endOfDirectory(HANDLE)


def list_category(category, page):
    progress = progress_create("Kategória betöltése", 10)
    items = category_items(category, page, progress)
    for index, item in enumerate(items, 1):
        add_mix(item, progress, 10 + index * 9, 100)
    progress.update(100, "[COLOR lime]Kész – %d mix[/COLOR]" % len(items))
    progress.close()
    if len(items) >= 10:
        add_folder("Következő oldal »", "category", name=category, page=page + 1)
    xbmcplugin.endOfDirectory(HANDLE)


def do_search():
    keyboard = xbmcgui.Dialog().input("Keresés", type=xbmcgui.INPUT_ALPHANUM)
    if not keyboard:
        xbmcplugin.endOfDirectory(HANDLE)
        return
    needle = keyboard.casefold()
    list_items([x for x in feed_items() if needle in (x["title"] + " " + x["description"]).casefold()])


def resolve_audio(url, referer):
    if not url:
        return ""
    # The site's click URL redirects to a MediaFire page. ResolveURL needs the
    # MediaFire page URL, while MediaFire exposes a temporary direct MP3 URL.
    final_url, page = follow_redirect(url, referer)
    if final_url != url and page and "mediafire.com" in final_url:
        direct = re.search(r"https://download[^\"'<> ]+\.mp3", page, re.I)
        if direct:
            return direct.group(0).replace("\\u0026", "&")
    candidate = final_url + "$$" + referer if referer else final_url
    if resolveurl:
        try:
            hmf = resolveurl.HostedMediaFile(candidate)
            if hmf:
                resolved = hmf.resolve()
                if isinstance(resolved, dict):
                    resolved = resolved.get("url", "")
                if resolved:
                    return resolved
        except Exception as exc:
            xbmc.log("HappyDanceDeejayz ResolveURL: %s" % exc, xbmc.LOGWARNING)
    return final_url


def play(item_url, title):
    item = {"url": item_url}
    download, image, details, _ = post_details(item)
    if not download:
        notify("Nem található lejátszási link", xbmcgui.NOTIFICATION_ERROR)
        return
    stream = resolve_audio(download, item_url)
    host = urlparse(stream).hostname or "ismeretlen host"
    xbmcgui.Dialog().notification("HappyDanceDeejayz", "Lejátszás: " + host,
                                  xbmcgui.NOTIFICATION_INFO, 4000)
    li = xbmcgui.ListItem(label=title, path=stream)
    li.setInfo("music", {"title": title, "comment": details[:1000]})
    li.setArt({"thumb": image or FANART, "icon": image or FANART, "fanart": FANART})
    xbmcplugin.setResolvedUrl(HANDLE, True, li)


def show_details(item_url, title):
    _, _, details, _ = post_details({"url": item_url})
    if not details:
        details = "Ehhez a mixhez nem található részletes tracklist."
    styled = "[COLOR cyan]" + title + "[/COLOR]\n"
    styled += "[COLOR yellow]TRACKLIST ÉS MIX INFORMÁCIÓK[/COLOR]\n\n" + details
    xbmcgui.Dialog().textviewer(title, styled)


params = parse_qs(urlparse(sys.argv[2]).query)
action = params.get("action", [""])[0]
if not action:
    list_home()
elif action == "recent":
    list_items(feed_items())
elif action == "category":
    category = params.get("name", [""])[0]
    page = max(1, int(params.get("page", ["1"])[0]))
    list_category(category, page)
elif action == "search":
    do_search()
elif action == "play":
    play(params.get("url", [""])[0], params.get("title", ["Mix"])[0])
elif action == "details":
    show_details(params.get("url", [""])[0], params.get("title", ["Mix információk"])[0])
