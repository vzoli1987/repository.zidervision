# -*- coding: utf-8 -*-
"""Contract implemented by each independently pluggable source adapter."""


class Adapter(object):
    adapter_id = 'base'
    name = 'Base adapter'

    def search(self, query):
        """Return movie dicts: title, year, url, poster, plot, adapter_id, adapter_name."""
        raise NotImplementedError

    def sources(self, movie):
        """Return dicts: host, language, quality, play_url, adapter_name."""
        return []


import re as _re

_QUALITY_TEXT = _re.compile(r'^(FULL\s?HD|FHD|HD|UHD|4K|2160P?|1080P?|720P?)$', _re.I)
_QUALITY_CLASS = _re.compile(r'hd|qual|res|badge|tag', _re.I)


def detect_quality(node):
    """'HD' / '1080p' ... when a quality badge (e.g. <span class="hd-tag">HD</span>) is inside the BeautifulSoup node."""
    if node is None:
        return ''
    for el in node.find_all(['span', 'div', 'small', 'b', 'i', 'em', 'strong', 'label']):
        text = ' '.join(el.get_text(' ', strip=True).split())
        if not _QUALITY_TEXT.match(text):
            continue
        classes = ' '.join(el.get('class') or [])
        if classes and not _QUALITY_CLASS.search(classes):
            continue
        key = text.upper().replace(' ', '')
        if key in ('FULLHD', 'FHD', '1080', '1080P'):
            return '1080p'
        if key in ('4K', 'UHD', '2160', '2160P'):
            return '4K'
        if key in ('720', '720P'):
            return '720p'
        return 'HD'
    return ''


_VOE_BARE_ID = _re.compile(r'^/([a-z0-9]{12})/?$')
_NOT_VOE = ('streamtape', 'doodstream', 'dood.', 'filemoon', 'mixdrop', 'upstream', 'vidmoly', 'vinovo', 'vidara',
            'indavideo', 'videa.hu', 'ok.ru', 'youtube', 'youtu.be')


def normalize_mirror(url):
    """VOE keeps rotating its domains (susanexpectcare.com, arianathankspecial.com ...) and ResolveURL cannot
    know them all. The same 12-character id always works on voe.sx: return (url, True) after that rewrite."""
    from urllib.parse import urlparse
    parsed = urlparse(url or '')
    host = parsed.netloc.lower()
    match = _VOE_BARE_ID.match(parsed.path or '')
    if not match or not host or host.endswith('voe.sx') or any(token in host for token in _NOT_VOE):
        return url, False
    return 'https://voe.sx/e/%s' % match.group(1), True
