# -*- coding: utf-8 -*-
"""Small, dependency-free public HTTP helpers for source adapters."""
from __future__ import absolute_import

import json
import re
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

UA = 'Mozilla/5.0 (Kodi; plugin.video.mozipremierek/1.7.5) AppleWebKit/537.36'
CHALLENGE_MARKERS = (
    'cf-chl-captcha-container', 'cf-chl-widget', 'Just a moment...',
    'Attention Required! | Cloudflare', 'Enable JavaScript and cookies to continue'
)


class SourceUnavailable(Exception):
    """Raised when an adapter source is offline, blocked, or changed."""


def get(url, headers=None, timeout=15):
    request_headers = {'User-Agent': UA, 'Accept': 'text/html,application/json;q=0.9,*/*;q=0.8', 'Accept-Language': 'hu-HU,hu;q=0.9,en;q=0.7'}
    if headers:
        request_headers.update(headers)
    request = Request(url, headers=request_headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode('utf-8', 'replace')
            final_url = response.geturl()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise SourceUnavailable(str(exc))
    if any(marker.lower() in body.lower() for marker in CHALLENGE_MARKERS):
        raise SourceUnavailable('Cloudflare verification returned; not bypassed')
    return body, final_url


def get_json(url, headers=None, timeout=15):
    body, final_url = get(url, headers=headers, timeout=timeout)
    try:
        return json.loads(body), final_url
    except (ValueError, TypeError) as exc:
        raise SourceUnavailable('Invalid JSON response: %s' % exc)


def post_json(url, data, headers=None, timeout=10):
    request_headers = {
        'User-Agent': UA,
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Accept-Language': 'hu-HU,hu;q=0.9,en;q=0.7',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest'
    }
    if headers:
        request_headers.update(headers)
    request = Request(url, data=urlencode(data).encode('utf-8'), headers=request_headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode('utf-8', 'replace')
            final_url = response.geturl()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise SourceUnavailable(str(exc))
    if any(marker.lower() in body.lower() for marker in CHALLENGE_MARKERS):
        raise SourceUnavailable('Verification returned; not bypassed')
    try:
        return json.loads(body), final_url
    except (ValueError, TypeError) as exc:
        raise SourceUnavailable('Invalid JSON response: %s' % exc)


def text_only(value):
    value = re.sub(r'<script\b.*?</script\s*>|<style\b.*?</style\s*>', ' ', value or '', flags=re.I | re.S)
    value = re.sub(r'<[^>]+>', ' ', value)
    return re.sub(r'\s+', ' ', unescape(value)).strip()


def query_url(base, **params):
    return base + ('&' if '?' in base else '?') + urlencode(params)
