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
