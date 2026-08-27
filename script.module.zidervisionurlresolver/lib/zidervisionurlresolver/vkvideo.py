import json
import random
import re
import string
from urllib.parse import parse_qsl, urlencode, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener
from http.cookiejar import CookieJar
import xbmc
from .common import BASE_URL, USER_AGENT, fetch, fetch_bytes, post_bytes, rc4_decrypt

VK_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:154.0) Gecko/20100101 Firefox/154.0"

def resolve_vk_new(provider_url):
    parsed = urlparse(provider_url)
    query = dict(parse_qsl(parsed.query))
    oid = query.get("oid", "")
    video_id = query.get("id", "")
    access_key = query.get("hash", "")
    if not oid or not video_id:
        return ""
    host = parsed.netloc.lower() or "vkvideo.ru"
    referer = "https://%s/" % host
    # VK requires a browser-like bootstrap request before issuing the first
    # anonymous token.  The token endpoint otherwise returns
    # "cant prolong token|l" when no remix cookies exist.
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    common_headers = {"User-Agent": VK_USER_AGENT, "Accept": "*/*", "Origin": "https://%s" % host, "Referer": referer}
    home_req = Request("https://%s/" % host, headers={**common_headers, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
    with opener.open(home_req, timeout=15) as response:
        response.read(4096)
    page_req = Request(provider_url, headers=common_headers)
    with opener.open(page_req, timeout=15) as response:
        response.read(4096)
    token_form = {
        "client_secret": "o557NLIkAErNhakXrQ7A",
        "client_id": "52461373",
        "scopes": "audio_anonymous,video_anonymous,photos_anonymous,profile_anonymous",
        "isApiOauthAnonymEnabled": "false",
        "version": "1",
        "app_id": "6287487",
    }
    token_req = Request("https://login.vk.ru/?act=get_anonym_token", data=urlencode(token_form).encode("utf-8"), headers={**common_headers, "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "X-Requested-With": "XMLHttpRequest"}, method="POST")
    with opener.open(token_req, timeout=15) as response:
        token_data = json.loads(response.read().decode("utf-8", "replace"))
    access_token = token_data.get("data", {}).get("access_token", "") if isinstance(token_data, dict) else ""
    if not access_token:
        xbmc.log("NapiFilm VK token response type=%s error=%s description=%s" % (token_data.get("type", ""), token_data.get("error", ""), token_data.get("error_description", "")), xbmc.LOGWARNING)
        return ""
    api_form = {"owner_id": "", "videos": "%s_%s_%s" % (oid, video_id, access_key), "extended": "0", "is_embed": "true", "track_code": "", "access_token": access_token}
    api_req = Request("https://api.vkvideo.ru/method/video.get?v=5.285&client_id=52461373", data=urlencode(api_form).encode("utf-8"), headers={**common_headers, "Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with opener.open(api_req, timeout=15) as response:
        api_data = json.loads(response.read().decode("utf-8", "replace"))
    items = api_data.get("response", {}).get("items", []) if isinstance(api_data, dict) else []
    if not items:
        xbmc.log("NapiFilm VK new API returned no items", xbmc.LOGWARNING)
        return ""
    files = items[0].get("files", {}) or {}
    candidates = []
    for key, value in files.items():
        if key.startswith("mp4_") and isinstance(value, str) and value.startswith(("http://", "https://")):
            match = re.search(r"(\d+)", key)
            candidates.append((int(match.group(1)) if match else 0, value, "video/mp4"))
    if not candidates:
        for key in ("hls_fmp4", "hls", "dash_sep"):
            value = files.get(key, "")
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                candidates.append((0, value, "application/vnd.apple.mpegurl" if key.startswith("hls") else "application/dash+xml"))
                break
    if not candidates:
        xbmc.log("NapiFilm VK new API returned no public media URL", xbmc.LOGWARNING)
        return ""
    quality, stream, mimetype = sorted(candidates, key=lambda item: item[0], reverse=True)[0]
    xbmc.log("NapiFilm VK new API selected quality=%s mime=%s" % (quality, mimetype), xbmc.LOGINFO)
    return {"url": stream + "|User-Agent=%s&Referer=%s&Origin=https://%s" % (VK_USER_AGENT, referer, host), "content-type": mimetype}


def resolve_vk(provider_url):
    parsed = urlparse(provider_url)
    query = dict(parse_qsl(parsed.query))
    oid = query.get("oid", "")
    video_id = query.get("id", "")
    if not oid or not video_id:
        return ""
    host = parsed.netloc.lower() or "vkvideo.ru"
    headers = {
        "Referer": "https://%s/" % host,
        "Origin": "https://%s" % host,
        "X-Requested-With": "XMLHttpRequest",
    }
    api_url = "https://%s/al_video.php?act=show" % host
    payload, _ = post_bytes(api_url, {"act": "show", "al": "1", "video": "%s_%s" % (oid.replace("video", ""), video_id)}, headers=headers)
    text = payload.decode("utf-8", "replace")
    if text.startswith("<!--"):
        text = text[4:]
    data = json.loads(text)
    xbmc.log("NapiFilm VK API response keys=%s" % sorted(data.keys()) if isinstance(data, dict) else "NapiFilm VK API response is not an object", xbmc.LOGINFO)
    candidates = []

    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(key, str) and key.startswith("url") and isinstance(item, str) and item.startswith(("http://", "https://")):
                    quality = re.search(r"(\d+)", key)
                    candidates.append((int(quality.group(1)) if quality else 0, item))
                else:
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(data)
    if candidates:
        quality, stream = sorted(candidates, key=lambda item: item[0], reverse=True)[0]
        xbmc.log("NapiFilm VK selected quality=%s" % quality, xbmc.LOGINFO)
        return {"url": stream + "|User-Agent=%s&Referer=https://%s/&Origin=https://%s" % (USER_AGENT, host, host), "content-type": "video/mp4"}
    # Current VK Video embeds may return only SPA metadata from this endpoint.
    # Do not invent or cache a stream URL when the provider did not expose one.
    xbmc.log("NapiFilm VK API returned no public direct source for %s_%s" % (oid, video_id), xbmc.LOGWARNING)
    return ""
