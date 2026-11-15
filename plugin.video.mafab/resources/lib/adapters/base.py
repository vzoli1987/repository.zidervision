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
