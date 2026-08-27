import html
import json
from urllib.error import HTTPError
import random
import re
import string
import time
from urllib.parse import parse_qsl, urlencode, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener
from http.cookiejar import CookieJar
import xbmc
from .common import BASE_URL, USER_AGENT, fetch, fetch_bytes, post_bytes, rc4_decrypt

def _cookie_header(cookie_jar):
    return "; ".join("%s=%s" % (cookie.name, cookie.value) for cookie in cookie_jar)


def resolve_indavideo(provider_url):
    match = re.search(r"(?:embed\.)?indavideo\.hu/player/video/([0-9A-Za-z_-]+)", provider_url, re.I)
    if not match:
        return ""
    media_id = match.group(1)
    # The embed player generates a short-lived CDN URL together with the
    # session cookies expected by the media host. Prefer that exact browser
    # path; the JSON endpoint remains a fallback for older embeds.
    try:
        cookie_jar = CookieJar()
        player_opener = build_opener(HTTPCookieProcessor(cookie_jar))
        player_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": BASE_URL + "/",
        }
        player_html = ""
        for attempt in range(3):
            try:
                with player_opener.open(Request(provider_url, headers=player_headers), timeout=15) as response:
                    player_html = response.read().decode("utf-8", "replace")
                if player_html:
                    break
            except HTTPError:
                raise
            except Exception as attempt_exc:
                xbmc.log("NapiFilm IndaVideo embed attempt %d/3: %s" % (attempt + 1, attempt_exc), xbmc.LOGDEBUG)
                if attempt < 2:
                    time.sleep(0.6 * (attempt + 1))
        direct_urls = re.findall(r'<(?:video|source)\b[^>]*\bsrc=["\']([^"\']+)', player_html, re.I)
        direct_urls = [html.unescape(re.sub(r"\?+", "?", value.strip())) for value in direct_urls]
        direct_urls = [value for value in direct_urls if ".mp4" in value.lower() and "token=" in value.lower()]
        if direct_urls:
            def direct_quality(value):
                match = re.search(r"\.(\d+)\.mp4", value)
                return int(match.group(1)) if match else 0
            stream = sorted(direct_urls, key=direct_quality, reverse=True)[0]
            cookie_header = _cookie_header(cookie_jar)
            header_parts = ["User-Agent=%s" % player_headers["User-Agent"], "Referer=%s" % provider_url, "Origin=https://embed.indavideo.hu"]
            if cookie_header:
                header_parts.append("Cookie=%s" % cookie_header)
            return stream + "|" + "&".join(header_parts)
    except Exception as exc:
        xbmc.log("NapiFilm IndaVideo embed adapter fallback: %s" % exc, xbmc.LOGDEBUG)
    api_url = "https://amfphp.indavideo.hu/SYm0json.php/player.playerHandler.getVideoData/%s/?_=%d" % (media_id, int(time.time() * 1000))
    try:
        payload = None
        for attempt in range(3):
            try:
                payload = json.loads(fetch(api_url, timeout=10))
                break
            except HTTPError:
                raise
            except Exception as attempt_exc:
                xbmc.log("NapiFilm IndaVideo API attempt %d/3: %s" % (attempt + 1, attempt_exc), xbmc.LOGDEBUG)
                if attempt < 2:
                    time.sleep(0.6 * (attempt + 1))
        if not isinstance(payload, dict):
            return ""
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        if str(payload.get("success", "0")) != "1":
            return ""
        files = data.get("video_files", {})
        tokens = data.get("filesh", {})
        if isinstance(files, dict):
            files = list(files.values())
        candidates = []
        for entry in files or []:
            if not isinstance(entry, str):
                continue
            quality = re.search(r"\.(\d+)\.mp4", entry)
            quality_value = int(quality.group(1)) if quality else 0
            token_key = quality.group(1) if quality else ""
            token = tokens.get(token_key, "") if isinstance(tokens, dict) else ""
            # Some IndaVideo API responses contain a malformed `??&` query
            # separator. Kodi/libcurl sends that literally and the CDN returns
            # 403, so normalize it before adding the short-lived token.
            entry = re.sub(r"\?+", "?", entry.strip().replace("&amp;", "&"))
            if token:
                entry = entry + ("&" if "?" in entry else "?") + "token=" + str(token)
            candidates.append((quality_value, entry))
        if not candidates:
            return ""
        stream = sorted(candidates, key=lambda item: item[0], reverse=True)[0][1]
        return stream + "|User-Agent=%s&Referer=%s&Origin=https://embed.indavideo.hu" % ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36", provider_url)
    except Exception as exc:
        xbmc.log("NapiFilm IndaVideo adapter error: %s" % exc, xbmc.LOGWARNING)
        return ""
