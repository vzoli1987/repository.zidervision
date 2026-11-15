# -*- coding: utf-8 -*-
"""Central registry: add a new adapter import and one instance here."""
from .filminvazio_pro import adapter as filminvazio_pro
from .filminvazio_cc import adapter as filminvazio_cc
from .filmdepo import adapter as filmdepo
from .napifilm import adapter as napifilm
from .mozibox import adapter as mozibox

ADAPTERS = [filminvazio_pro, filminvazio_cc, filmdepo, napifilm, mozibox]
