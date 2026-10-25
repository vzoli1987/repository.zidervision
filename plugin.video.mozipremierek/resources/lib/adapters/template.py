# -*- coding: utf-8 -*-
"""Copy this file to a new_site.py module to add another provider."""
from __future__ import absolute_import

from .base import Adapter


class NewSiteAdapter(Adapter):
    # Must be unique across resources/lib/adapters.
    adapter_id = 'new_site'
    name = 'NEW SITE'

    def search(self, query):
        """Return one dict per movie found on this site.

        Required fields: title, url, adapter_id, adapter_name.
        Optional fields: year, poster, plot.
        Keep requests on the public site and return [] when blocked or unavailable.
        """
        return []

    def sources(self, movie):
        """Return one dict per selectable host.

        Required fields: host, play_url, adapter_name.
        Optional fields: language, quality.
        The play_url should target this provider's existing Kodi playback route.
        """
        return []


adapter = NewSiteAdapter()
