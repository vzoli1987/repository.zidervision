"""Public API for the ZiderVision URL Resolver."""
from urllib.error import HTTPError
from urllib.parse import urlparse


class ResolverHTTPError(Exception):
    """HTTP failure that can be presented cleanly by Kodi frontends."""
    def __init__(self, provider, status, url):
        self.provider = provider
        self.status = int(status or 0)
        self.url = url or ""
        super().__init__("%s HTTP %s: %s" % (provider, self.status, self.url))

from .videa import resolve_videa
from .vkvideo import resolve_vk_new, resolve_vk
from .indavideo import resolve_indavideo

def resolve(url):
    host = urlparse(url).netloc.lower()
    provider = "ismeretlen szolgáltató"
    try:
        if "videa.hu" in host:
            provider = "Videa"
            return resolve_videa(url)
        if "vkvideo.ru" in host or "vk.com" in host:
            provider = "VK Video"
            return resolve_vk_new(url) or resolve_vk(url)
        if "indavideo.hu" in host or "videakid.hu" in host:
            provider = "IndaVideo"
            return resolve_indavideo(url)
        return ""
    except HTTPError as exc:
        raise ResolverHTTPError(provider, exc.code, getattr(exc, "url", None) or url) from exc
