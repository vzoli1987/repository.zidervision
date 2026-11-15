# -*- coding: utf-8 -*-
"""Mafab's own "Minden szűrő" search: the options of its filter form and the request it sends."""
from __future__ import absolute_import

from urllib.parse import urljoin

from .net import SourceUnavailable, post_json

BASE = 'https://www.mafab.hu/'
ENDPOINT = BASE + 'filmek/filmek/1'

GENRES = [(28, 'akció'), (16, 'animáció'), (10751, 'családi'), (99, 'dokumentum'), (18, 'dráma'),
          (10787, 'életrajzi'), (2916, 'erotikus'), (14, 'fantasy'), (10851, 'fekete komédia'),
          (10752, 'háborús'), (27, 'horror'), (10771, 'játékfilm'), (12, 'kaland'), (105, 'katasztrófafilm'),
          (10784, 'kísérleti film'), (80, 'krimi'), (9648, 'misztikus'), (22, 'musical'), (10835, 'politikai'),
          (1115, 'road movie'), (10749, 'romantikus'), (10755, 'rövidfilm'), (878, 'sci-fi'), (9805, 'sportfilm'),
          (10789, 'szatíra'), (53, 'thriller'), (36, 'történelmi'), (10764, 'valóságshow'), (35, 'vígjáték'),
          (37, 'western'), (10402, 'zenés')]
PLATFORMS = [(32, 'Amazon Prime Video'), (31, 'Apple TV'), (27, 'Cinego'), (41, 'Disney+'), (29, 'Filmio'),
             (25, 'HBO Max'), (24, 'Netflix'), (45, 'SkyShowtime'), (26, 'Telekom FilmPremier')]
RATINGS = [('all', 'Mindegy'), ('95', '95% felett'), ('90', '90% felett'), ('80', '80% felett'),
           ('70', '70% felett'), ('50', '50% felett'), ('none', 'Még nincs értékelés')]
AGES = [('all', 'Mindegy'), ('x', 'Korhatár nélkül'), ('18', '18+'), ('16', '16+'), ('12', '12+'), ('6', '6+'),
        ('1', '0+')]
COUNTRIES = [(3, 'Amerikai Egyesült Államok'), (8, 'Egyesült Királyság'), (34, 'Magyarország'), (9, 'Franciaország'),
             (6, 'Németország'), (29, 'Olaszország'), (11, 'Spanyolország'), (4, 'Japán'), (22, 'Koreai Köztársaság'),
             (18, 'Kína'), (39, 'India'), (10, 'Kanada'), (31, 'Ausztrália'), (40, 'Oroszország'), (21, 'Lengyelország'),
             (7, 'Svédország'), (26, 'Norvégia'), (20, 'Dánia'), (2, 'Finnország'), (14, 'Hollandia'), (28, 'Belgium'),
             (5, 'Ausztria'), (16, 'Svájc'), (19, 'Írország'), (36, 'Törökország'), (13, 'Mexikó'), (42, 'Brazília'),
             (56, 'Argentína'), (49, 'Thaiföld'), (33, 'Csehország'), (45, 'Görögország'), (37, 'Portugália'),
             (12, 'Izrael'), (17, 'Hongkong'), (27, 'Tajvan'), (24, 'Új-Zéland'), (30, 'Dél-afrikai Köztársaság'),
             (1, 'Szovjetunió'), (75, 'Horvátország'), (68, 'Szerbia'), (50, 'Románia'), (71, 'Szlovákia')]


def new_state():
    return {'movies': True, 'series': True, 'genres': [], 'platforms': [], 'rating': 'all', 'age': 'all',
            'year_from': 0, 'year_to': 0, 'country': None, 'keyword': ''}


def form_data(state):
    """The fields the site's form would serialize (name -> value)."""
    data = {'ajax_filter': ''}
    if state.get('movies'):
        data['type_movies'] = '1'
    if state.get('series'):
        data['type_series'] = '1'
    for gid in state.get('genres', []):
        data['genre[%s]' % gid] = 'on'
    for pid in state.get('platforms', []):
        data['platform[%s]' % pid] = 'on'
    if state.get('rating') not in (None, 'all'):
        data['rating'] = state['rating']
    if state.get('age') not in (None, 'all'):
        data['selected_age'] = state['age']
    if state.get('year_from'):
        data['yrf'] = str(state['year_from'])
    if state.get('year_to'):
        data['yrt'] = str(state['year_to'])
    if state.get('country'):
        cid, name = state['country']
        data['country[%s]' % cid] = name
    if state.get('keyword'):
        data['kword[]'] = state['keyword']
    return data


def results_url(state):
    """POST the filters like the page does; the site answers with the result URL and the hit count."""
    answer, _ = post_json(ENDPOINT, form_data(state), headers={'Referer': BASE + 'filmek/filmek/'})
    if not isinstance(answer, dict) or 'URL' not in answer:
        raise SourceUnavailable('Unexpected filter answer: %r' % (answer,))
    path = str(answer['URL'])
    try:
        count = int(answer.get('num_result'))
    except (TypeError, ValueError):
        count = None
    return urljoin(ENDPOINT + '/', path), count
