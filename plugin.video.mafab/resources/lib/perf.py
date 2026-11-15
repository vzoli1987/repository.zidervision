# -*- coding: utf-8 -*-
"""Tiny timing helper: every slow step leaves one '[perf]' line in kodi.log."""
from __future__ import absolute_import

import time
from contextlib import contextmanager

try:
    import xbmc
    _log = lambda msg: xbmc.log('plugin.video.mafab [perf] %s' % msg, xbmc.LOGINFO)
except ImportError:  # unit tests outside Kodi
    _log = lambda msg: None


@contextmanager
def timed(label, min_ms=0):
    start = time.time()
    try:
        yield
    finally:
        ms = int((time.time() - start) * 1000)
        if ms >= min_ms:
            _log('%s: %d ms' % (label, ms))
