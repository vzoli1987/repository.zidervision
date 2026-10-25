# -*- coding: utf-8 -*-
"""Multi-source search, grouping, and provider collection."""
from __future__ import absolute_import

import hashlib
import json
import os
import re
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from .adapters import ADAPTERS


def normalize_title(value):
    value = unicodedata.normalize('NFKD', (value or '').casefold())
    value = ''.join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r'\b(?:19|20)\d{2}\b', ' ', value)
    value = re.sub(r'[^a-z0-9]+', ' ', value)
    return ' '.join(value.split())


def _year(value):
    match = re.search(r'\b(?:19|20)\d{2}\b', str(value or ''))
    return match.group(0) if match else ''


def group_movies(records):
    groups = []
    for item in records:
        norm = normalize_title(item.get('title', ''))
        if not norm:
            continue
        year = _year(item.get('year'))
        found = None
        for group in groups:
            if group['_norm'] == norm and not (year and group.get('year') and year != group['year']):
                found = group
                break
        if found is None:
            found = {
                'id': uuid.uuid4().hex,
                'title': item.get('title', '').strip(),
                'year': year,
                'poster': item.get('poster', ''),
                'plot': item.get('plot', ''),
                '_norm': norm,
                'movies': []
            }
            groups.append(found)
        elif not found.get('year') and year:
            found['year'] = year
        if not found.get('poster') and item.get('poster'):
            found['poster'] = item['poster']
        if not found.get('plot') and item.get('plot'):
            found['plot'] = item['plot']
        key = (item.get('adapter_id'), item.get('url'))
        if not any((x.get('adapter_id'), x.get('url')) == key for x in found['movies']):
            found['movies'].append(item)
    for group in groups:
        group.pop('_norm', None)
    groups.sort(key=lambda x: (normalize_title(x['title']), x.get('year', '')))
    return groups


def search_all(query, logger=None, on_progress=None):
    records = []
    errors = []
    total = len(ADAPTERS)
    completed = 0
    with ThreadPoolExecutor(max_workers=max(1, min(4, len(ADAPTERS)))) as pool:
        future_map = {pool.submit(adapter.search, query): adapter for adapter in ADAPTERS}
        for future in as_completed(future_map):
            adapter = future_map[future]
            try:
                found = future.result()
                records.extend(found or [])
            except Exception as exc:
                found = []
                errors.append('%s: %s' % (adapter.name, exc))
                if logger:
                    logger('%s search failed: %s' % (adapter.name, exc))
            completed += 1
            if on_progress:
                try:
                    on_progress('search', adapter.name, completed, total, found or [])
                except Exception:
                    pass
    return group_movies(records), errors


def collect_sources(group, logger=None, on_progress=None):
    sources = []
    errors = []
    by_id = {adapter.adapter_id: adapter for adapter in ADAPTERS}
    completed = 0
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {}
        for movie in group.get('movies', []):
            adapter = by_id.get(movie.get('adapter_id'))
            if adapter:
                futures[pool.submit(adapter.sources, movie)] = adapter
        for future in as_completed(futures):
            adapter = futures[future]
            try:
                found = future.result() or []
                sources.extend(found)
            except Exception as exc:
                found = []
                errors.append('%s: %s' % (adapter.name, exc))
                if logger:
                    logger('%s source listing failed: %s' % (adapter.name, exc))
            completed += 1
            if on_progress:
                try:
                    on_progress('sources', adapter.name, completed, len(futures), found or [])
                except Exception:
                    pass
    unique, seen = [], set()
    for source in sources:
        source['adapter_name'] = source.get('adapter_name') or 'Ismeretlen forrás'
        key = (source['adapter_name'], source.get('host', ''), source.get('play_url', ''))
        if key in seen:
            continue
        seen.add(key)
        unique.append(source)
    unique.sort(key=lambda x: (x.get('adapter_name', '').casefold(), x.get('host', '').casefold(), x.get('quality', '').casefold()))
    return unique, errors


def group_store_path(profile, token):
    return os.path.join(profile, 'search_%s.json' % token)


def save_groups(profile, groups):
    token = uuid.uuid4().hex
    payload = {'groups': groups}
    path = group_store_path(profile, token)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False)
    return token


def load_group(profile, token, group_id):
    if not re.fullmatch(r'[a-f0-9]{32}', token or '') or not re.fullmatch(r'[a-f0-9]{32}', group_id or ''):
        return None
    path = group_store_path(profile, token)
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            groups = json.load(handle).get('groups', [])
        return next((group for group in groups if group.get('id') == group_id), None)
    except (OSError, ValueError, TypeError):
        return None
