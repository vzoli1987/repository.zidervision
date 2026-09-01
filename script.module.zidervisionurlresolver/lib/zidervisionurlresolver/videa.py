import html
import json
from urllib.error import HTTPError
import random
import re
import string
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener
from http.cookiejar import CookieJar
import xbmc
from .common import BASE_URL, USER_AGENT, fetch, fetch_bytes, post_bytes, rc4_decrypt

def resolve_videa(provider_url, _depth=0):
    if _depth >= 3:
        xbmc.log("NapiFilm Videa noembed fallback limit reached", xbmc.LOGWARNING)
        return ""
    browser_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
    cookie_jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(cookie_jar))
    parsed = urlparse(provider_url)
    query = dict(parse_qsl(parsed.query))
    param_name = "f" if query.get("f") else "v"
    f_value = query.get(param_name)
    if not f_value:
        # Gujal's resolver follows the canonical Videa URL returned by a
        # noembed response and extracts its current player iframe.
        try:
            page_request = Request(provider_url, headers={
                "User-Agent": browser_ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": BASE_URL + "/",
            })
            with opener.open(page_request, timeout=15) as response:
                page_html = response.read().decode("utf-8", "replace")
            iframe = re.search(r'<iframe[^>]+src=["\']([^"\']*?/player(?:\?[^"\']*)?)["\']', page_html, re.I)
            if not iframe:
                return ""
            provider_url = urljoin(provider_url, html.unescape(iframe.group(1)))
            parsed = urlparse(provider_url)
            query = dict(parse_qsl(parsed.query))
            param_name = "f" if query.get("f") else "v"
            f_value = query.get(param_name)
        except Exception as exc:
            xbmc.log("NapiFilm Videa canonical page fallback: %s" % exc, xbmc.LOGDEBUG)
            return ""
    if not f_value:
        return ""
    player_request = Request(provider_url, headers={
        "User-Agent": browser_ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": BASE_URL + "/",
    })
    player_html_bytes = b""
    player_headers = {}
    for attempt in range(3):
        try:
            with opener.open(player_request, timeout=15) as response:
                player_html_bytes = response.read()
                player_headers = dict(response.headers.items())
            if player_html_bytes:
                break
        except HTTPError:
            raise
        except Exception as attempt_exc:
            xbmc.log("NapiFilm Videa player attempt %d/3: %s" % (attempt + 1, attempt_exc), xbmc.LOGDEBUG)
    player_html = player_html_bytes.decode("utf-8", "replace")
    xbmc.log("NapiFilm Videa player response bytes=%d status_headers=%s" % (len(player_html_bytes), sorted(player_headers.keys())), xbmc.LOGINFO)
    nonce_match = re.search(r"_xt\s*=\s*['\"]([^'\"]+)['\"]", player_html)
    if not nonce_match:
        xbmc.log("NapiFilm Videa nonce not found in player response", xbmc.LOGWARNING)
        return ""
    nonce = nonce_match.group(1)
    secret = "xHb0ZvME5q8CBcoQi6AngerDu3FGO9fkUlwPmLVY_RTzj2hJIS4NasXWKy1td7p"
    lookup = nonce[:32]
    tail = nonce[32:]
    if len(lookup) < 32 or len(tail) < 32:
        return ""
    derived = ""
    try:
        for index in range(32):
            offset = index - (secret.index(lookup[index]) - 31)
            derived += tail[offset]
    except (ValueError, IndexError) as exc:
        xbmc.log("NapiFilm Videa nonce derivation failed: %s" % exc, xbmc.LOGWARNING)
        return ""
    random_seed = "".join(random.choice(string.ascii_letters + string.digits) for _ in range(8))
    key = derived[16:] + random_seed
    signed = derived[:16]
    # The current Videa player includes language and start-position parameters;
    # omitting them can yield a valid 200 response containing noembed.
    xml_url = "https://videa.hu/player/xml?platform=desktop&%s&lang=hu&_s=%s&_t=%s&start=0" % (param_name + "=" + f_value, random_seed, signed)
    xml_request = Request(xml_url, headers={
        "User-Agent": browser_ua,
        "Accept": "*/*",
        "Referer": provider_url,
        "Origin": "https://videa.hu",
    })
    xml_bytes = b""
    xml_headers = {}
    for attempt in range(3):
        try:
            with opener.open(xml_request, timeout=15) as response:
                xml_bytes = response.read()
                xml_headers = dict(response.headers.items())
            if xml_bytes:
                break
        except HTTPError:
            raise
        except Exception as attempt_exc:
            xbmc.log("NapiFilm Videa XML attempt %d/3: %s" % (attempt + 1, attempt_exc), xbmc.LOGDEBUG)
    if not xml_bytes:
        return ""
    xbmc.log("NapiFilm Videa XML response bytes=%d headers=%s" % (len(xml_bytes), sorted(xml_headers.keys())), xbmc.LOGINFO)
    if xml_bytes.lstrip().startswith(b"<?xml"):
        xml_preview = xml_bytes.decode("utf-8", "replace")
        error_match = re.search(r"<error\b[^>]*>(.*?)</error>", xml_preview, re.I | re.S)
        if error_match:
            fallback_url = html.unescape(re.sub(r"<[^>]+>", "", error_match.group(1))).strip()
            if fallback_url.startswith("//"):
                fallback_url = "https:" + fallback_url
            if fallback_url and fallback_url != provider_url and "videa.hu" in urlparse(fallback_url).netloc.lower():
                xbmc.log("NapiFilm Videa noembed fallback URL követése: %s" % fallback_url, xbmc.LOGINFO)
                return resolve_videa(fallback_url, _depth + 1)
    if not xml_bytes.lstrip().startswith(b"<?xml"):
        xs_header = next((value for key, value in xml_headers.items() if key.lower() == "x-videa-xs"), "")
        if not xs_header:
            xbmc.log("NapiFilm Videa XML response is not XML and has no X-Videa-Xs header; prefix=%r" % xml_bytes[:120], xbmc.LOGWARNING)
            return ""
        xml_bytes = rc4_decrypt(xml_bytes, key + xs_header)
    xml = xml_bytes.decode("utf-8", "replace")
    xbmc.log("NapiFilm Videa parsed XML prefix=%r" % xml[:120], xbmc.LOGINFO)
    subtitle_tracks = {}
    for subtitle_src, subtitle_title, subtitle_id in re.findall(
        r'<subtitle\b[^>]*\bsrc="([^"]+)"[^>]*\btitle="([^"]*)"[^>]*\bid="(\d+)"',
        xml,
        re.I,
    ):
        subtitle_src = html.unescape(subtitle_src)
        if subtitle_src.startswith("//"):
            subtitle_src = "https:" + subtitle_src
        if subtitle_src.startswith("/"):
            subtitle_src = "https://videa.hu" + subtitle_src
        if subtitle_src and subtitle_id:
            subtitle_tracks[subtitle_title or subtitle_id] = subtitle_src
    raw_sources = re.findall(r'<video_source\b([^>]*)>([^<]+)</video_source>', xml, re.I)
    sources = []
    for attributes, source_url in raw_sources:
        name_match = re.search(r'\bname="([^"]+)"', attributes, re.I)
        exp_match = re.search(r'\bexp="([^"]+)"', attributes, re.I)
        mime_match = re.search(r'\bmimetype="([^"]+)"', attributes, re.I)
        if name_match and exp_match:
            width_match = re.search(r'\bwidth="(\d+)"', attributes, re.I)
            height_match = re.search(r'\bheight="(\d+)"', attributes, re.I)
            hd_match = re.search(r'\bis_hd="(\d+)"', attributes, re.I)
            sources.append((name_match.group(1), exp_match.group(1), mime_match.group(1) if mime_match else "", source_url, int(width_match.group(1)) if width_match else 0, int(height_match.group(1)) if height_match else 0, int(hd_match.group(1)) if hd_match else 0))
    if not sources:
        master = re.search(r"<master_playlist_url>([^<]+)", xml, re.I)
        if master:
            return {"url": master.group(1).replace("&amp;", "&") + "|User-Agent=%s&Referer=https://videa.hu/" % USER_AGENT, "content-type": "application/vnd.apple.mpegurl", "subtitles": subtitle_tracks}
        return ""
    def source_score(item):
        quality = re.search(r"(\d+)", item[0])
        # Prefer the highest resolution; use MP4 as a tie-breaker for equal resolution.
        mp4_bonus = 1 if item[2].lower() == "video/mp4" else 0
        return (item[5], item[4], item[6], mp4_bonus, int(quality.group(1)) if quality else 0)
    label, expires, mimetype, source_url, width, height, is_hd = sorted(sources, key=source_score, reverse=True)[0]
    xbmc.log("NapiFilm Videa selected quality=%s %sx%s mime=%s" % (label, width, height, mimetype), xbmc.LOGINFO)
    source_url = source_url.strip().replace("&amp;", "&")
    if source_url.startswith("//"):
        source_url = "https:" + source_url
    hash_match = re.search(r"<hash_value_%s>([^<]+)" % re.escape(label), xml, re.I)
    if hash_match:
        separator = "&" if "?" in source_url else "?"
        source_url = "%s%smd5=%s&expires=%s" % (source_url, separator, hash_match.group(1), expires)
    return {"url": source_url + "|User-Agent=%s&Referer=https://videa.hu/&Origin=https://videa.hu" % USER_AGENT, "content-type": mimetype, "subtitles": subtitle_tracks}
