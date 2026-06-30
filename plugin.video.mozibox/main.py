import sys
import urllib.parse
import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon
import requests
from bs4 import BeautifulSoup

# ResolveURL import
import resolveurl

# Alapváltozók
_handle = int(sys.argv[1])
_url = sys.argv[0]
_addon = xbmcaddon.Addon()
_addon_name = _addon.getAddonInfo('name')
_base_url = 'https://mozibox.hu'

_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0',
    'Accept-Language': 'hu-HU,hu;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive'
}

def log(msg, level=xbmc.LOGDEBUG):
    xbmc.log(f'[{_addon_name}] {msg}', level)

def build_url(query):
    return _url + '?' + urllib.parse.urlencode(query)

def main_menu():
    """Főmenü megjelenítése"""
    log('Főmenü megjelenítése')
    
    # Legújabb filmek
    li = xbmcgui.ListItem('[B]🎬 Legújabb filmek[/B]')
    li.setArt({'icon': 'DefaultMovies.png', 'thumb': 'DefaultMovies.png'})
    url = build_url({'mode': 'list', 'page': 1})
    xbmcplugin.addDirectoryItem(handle=_handle, url=url, listitem=li, isFolder=True)
    
    # Keresés
    li = xbmcgui.ListItem('[B]🔍 Keresés[/B]')
    li.setArt({'icon': 'DefaultAddonsSearch.png', 'thumb': 'DefaultAddonsSearch.png'})
    url = build_url({'mode': 'search'})
    xbmcplugin.addDirectoryItem(handle=_handle, url=url, listitem=li, isFolder=True)
    
    # Kategóriák
    li = xbmcgui.ListItem('[B]📂 Kategóriák[/B]')
    li.setArt({'icon': 'DefaultFolder.png', 'thumb': 'DefaultFolder.png'})
    url = build_url({'mode': 'categories'})
    xbmcplugin.addDirectoryItem(handle=_handle, url=url, listitem=li, isFolder=True)
    
    xbmcplugin.endOfDirectory(_handle)

def list_categories():
    """Kategóriák listázása - a film kártyákból kinyert műfajok alapján"""
    log('Kategóriák listázása')
    
    categories = set()
    page = 1
    
    # Végigmegyünk az összes oldalon, és kinyerjük a műfajokat
    while page <= 10:  # Maximum 10 oldal
        url = f'{_base_url}/index.php?page={page}' if page > 1 else f'{_base_url}/index.php'
        
        try:
            r = requests.get(url, headers=_HEADERS, timeout=15)
            r.raise_for_status()
        except Exception as e:
            log(f'Letöltési hiba: {e}', xbmc.LOGERROR)
            break
        
        soup = BeautifulSoup(r.text, 'html.parser')
        movie_cards = soup.find_all('article', class_='movie-card')
        
        if not movie_cards:
            break
        
        for card in movie_cards:
            genre_elem = card.find('div', class_='movie-meta')
            if genre_elem:
                genre_text = genre_elem.text.strip()
                # A műfajok vesszővel vannak elválasztva
                genres = [g.strip() for g in genre_text.split(',') if g.strip()]
                categories.update(genres)
        
        page += 1
    
    if not categories:
        xbmcgui.Dialog().notification(_addon_name, 'Nincsenek kategóriák', xbmcgui.NOTIFICATION_INFO, 3000)
        xbmcplugin.endOfDirectory(_handle, succeeded=False)
        return
    
    # Kategóriák rendezése és megjelenítése
    for category in sorted(categories):
        li = xbmcgui.ListItem(category)
        li.setArt({'icon': 'DefaultFolder.png', 'thumb': 'DefaultFolder.png'})
        url = build_url({'mode': 'category', 'category': category})
        xbmcplugin.addDirectoryItem(handle=_handle, url=url, listitem=li, isFolder=True)
    
    xbmcplugin.endOfDirectory(_handle)

def list_movies_by_category(category, page=1):
    """Filmek listázása egy adott kategóriából - kliens oldali szűrés"""
    log(f'Kategória listázása: {category}, oldal: {page}')
    
    all_movies = []
    current_page = 1
    
    # Lekérjük az összes filmet
    while current_page <= 10:  # Maximum 10 oldal
        url = f'{_base_url}/index.php?page={current_page}' if current_page > 1 else f'{_base_url}/index.php'
        
        try:
            r = requests.get(url, headers=_HEADERS, timeout=15)
            r.raise_for_status()
        except Exception as e:
            log(f'Letöltési hiba: {e}', xbmc.LOGERROR)
            break
        
        soup = BeautifulSoup(r.text, 'html.parser')
        movie_cards = soup.find_all('article', class_='movie-card')
        
        if not movie_cards:
            break
        
        for card in movie_cards:
            try:
                title_elem = card.find('h2', class_='movie-title')
                title = title_elem.text.strip() if title_elem else 'Ismeretlen'
                
                img_elem = card.find('img')
                poster = img_elem['src'] if img_elem and img_elem.get('src') else ''
                
                year_elem = card.find('div', class_='movie-year')
                year = year_elem.text.strip() if year_elem else ''
                
                genre_elem = card.find('div', class_='movie-meta')
                genre = genre_elem.text.strip() if genre_elem else ''
                
                link_elem = card.find('a', class_='btn-primary')
                href = link_elem['href'] if link_elem and link_elem.get('href') else ''
                if not href:
                    continue
                
                movie_url = href if href.startswith('http') else f'{_base_url}/{href}'
                
                # Ellenőrizzük, hogy a film tartalmazza-e a kategóriát
                genres = [g.strip() for g in genre.split(',') if g.strip()]
                if category in genres:
                    all_movies.append({
                        'title': title,
                        'poster': poster,
                        'year': year,
                        'genre': genre,
                        'url': movie_url
                    })
            except Exception as e:
                log(f'Kártya hiba: {e}', xbmc.LOGERROR)
        
        current_page += 1
    
    if not all_movies:
        xbmcgui.Dialog().notification(_addon_name, 'Nincs találat ebben a kategóriában', xbmcgui.NOTIFICATION_INFO, 3000)
        xbmcplugin.endOfDirectory(_handle, succeeded=False)
        return
    
    # Oldalra bontás (20 film oldalanként)
    movies_per_page = 20
    start_idx = (page - 1) * movies_per_page
    end_idx = start_idx + movies_per_page
    page_movies = all_movies[start_idx:end_idx]
    
    for movie in page_movies:
        try:
            li = xbmcgui.ListItem(movie['title'])
            video_info = li.getVideoInfoTag()
            video_info.setTitle(movie['title'])
            if movie['year'].isdigit():
                video_info.setYear(int(movie['year']))
            video_info.setGenres([movie['genre']])
            
            li.setArt({
                'thumb': movie['poster'],
                'icon': movie['poster'],
                'poster': movie['poster'],
                'fanart': movie['poster']
            })
            
            li.setProperty('IsPlayable', 'true')
            
            item_url = build_url({'mode': 'play', 'url': movie['url'], 'title': movie['title']})
            xbmcplugin.addDirectoryItem(handle=_handle, url=item_url, listitem=li, isFolder=False)
        except Exception as e:
            log(f'Film hiba: {e}', xbmc.LOGERROR)
    
    # Következő oldal
    if end_idx < len(all_movies):
        next_url = build_url({'mode': 'category', 'category': category, 'page': page + 1})
        li_next = xbmcgui.ListItem(f'[B][COLOR gold]>> Következő oldal ({page + 1})[/COLOR][/B]')
        li_next.setArt({'icon': 'DefaultFolder.png'})
        xbmcplugin.addDirectoryItem(handle=_handle, url=next_url, listitem=li_next, isFolder=True)
    
    xbmcplugin.setContent(_handle, 'movies')
    xbmcplugin.endOfDirectory(_handle)

def search_movies():
    """Keresés indítása"""
    log('Keresés indítása')
    
    # Input mező megjelenítése
    kb = xbmcgui.Dialog()
    search_query = kb.input('Keresés cím alapján:', type=xbmcgui.INPUT_ALPHANUM)
    
    if not search_query:
        xbmcplugin.endOfDirectory(_handle, succeeded=False)
        return
    
    log(f'Keresési kifejezés: {search_query}')
    
    # Keresés URL összeállítása
    url = f'{_base_url}/index.php?q={urllib.parse.quote(search_query)}'
    
    try:
        r = requests.get(url, headers=_HEADERS, timeout=15)
        r.raise_for_status()
    except Exception as e:
        log(f'Letöltési hiba: {e}', xbmc.LOGERROR)
        xbmcgui.Dialog().notification(_addon_name, f'Hiba: {str(e)[:50]}', xbmcgui.NOTIFICATION_ERROR, 5000)
        xbmcplugin.endOfDirectory(_handle, succeeded=False)
        return
    
    soup = BeautifulSoup(r.text, 'html.parser')
    movie_cards = soup.find_all('article', class_='movie-card')
    
    if not movie_cards:
        xbmcgui.Dialog().notification(_addon_name, 'Nincs találat', xbmcgui.NOTIFICATION_INFO, 3000)
        xbmcplugin.endOfDirectory(_handle, succeeded=False)
        return
    
    for card in movie_cards:
        try:
            title_elem = card.find('h2', class_='movie-title')
            title = title_elem.text.strip() if title_elem else 'Ismeretlen'
            
            img_elem = card.find('img')
            poster = img_elem['src'] if img_elem and img_elem.get('src') else ''
            
            year_elem = card.find('div', class_='movie-year')
            year = year_elem.text.strip() if year_elem else ''
            
            genre_elem = card.find('div', class_='movie-meta')
            genre = genre_elem.text.strip() if genre_elem else ''
            
            link_elem = card.find('a', class_='btn-primary')
            href = link_elem['href'] if link_elem and link_elem.get('href') else ''
            if not href:
                continue
            
            movie_url = href if href.startswith('http') else f'{_base_url}/{href}'
            
            li = xbmcgui.ListItem(title)
            video_info = li.getVideoInfoTag()
            video_info.setTitle(title)
            if year.isdigit():
                video_info.setYear(int(year))
            video_info.setGenres([genre])
            
            li.setArt({
                'thumb': poster,
                'icon': poster,
                'poster': poster,
                'fanart': poster
            })
            
            li.setProperty('IsPlayable', 'true')
            
            item_url = build_url({'mode': 'play', 'url': movie_url, 'title': title})
            xbmcplugin.addDirectoryItem(handle=_handle, url=item_url, listitem=li, isFolder=False)
            
        except Exception as e:
            log(f'Kártya hiba: {e}', xbmc.LOGERROR)
    
    xbmcplugin.setContent(_handle, 'movies')
    xbmcplugin.endOfDirectory(_handle)

def list_movies(page=1):
    """Filmek listázása a főoldalról"""
    log(f'Filmek listázása, oldal: {page}')
    url = f'{_base_url}/index.php?page={page}' if page > 1 else f'{_base_url}/index.php'
    
    try:
        r = requests.get(url, headers=_HEADERS, timeout=15)
        r.raise_for_status()
    except Exception as e:
        log(f'Letöltési hiba: {e}', xbmc.LOGERROR)
        xbmcgui.Dialog().notification(_addon_name, f'Hiba: {str(e)[:50]}', xbmcgui.NOTIFICATION_ERROR, 5000)
        xbmcplugin.endOfDirectory(_handle, succeeded=False)
        return
    
    soup = BeautifulSoup(r.text, 'html.parser')
    movie_cards = soup.find_all('article', class_='movie-card')
    
    if not movie_cards:
        xbmcplugin.endOfDirectory(_handle, succeeded=False)
        return
    
    for card in movie_cards:
        try:
            title_elem = card.find('h2', class_='movie-title')
            title = title_elem.text.strip() if title_elem else 'Ismeretlen'
            
            img_elem = card.find('img')
            poster = img_elem['src'] if img_elem and img_elem.get('src') else ''
            
            year_elem = card.find('div', class_='movie-year')
            year = year_elem.text.strip() if year_elem else ''
            
            genre_elem = card.find('div', class_='movie-meta')
            genre = genre_elem.text.strip() if genre_elem else ''
            
            link_elem = card.find('a', class_='btn-primary')
            href = link_elem['href'] if link_elem and link_elem.get('href') else ''
            if not href:
                continue
            
            movie_url = href if href.startswith('http') else f'{_base_url}/{href}'
            
            li = xbmcgui.ListItem(title)
            video_info = li.getVideoInfoTag()
            video_info.setTitle(title)
            if year.isdigit():
                video_info.setYear(int(year))
            video_info.setGenres([genre])
            
            li.setArt({
                'thumb': poster,
                'icon': poster,
                'poster': poster,
                'fanart': poster
            })
            
            li.setProperty('IsPlayable', 'true')
            
            item_url = build_url({'mode': 'play', 'url': movie_url, 'title': title})
            xbmcplugin.addDirectoryItem(handle=_handle, url=item_url, listitem=li, isFolder=False)
            
        except Exception as e:
            log(f'Kártya hiba: {e}', xbmc.LOGERROR)
    
    # Következő oldal
    next_url = build_url({'mode': 'list', 'page': page + 1})
    li_next = xbmcgui.ListItem(f'[B][COLOR gold]>> Következő oldal ({page + 1})[/COLOR][/B]')
    li_next.setArt({'icon': 'DefaultFolder.png'})
    xbmcplugin.addDirectoryItem(handle=_handle, url=next_url, listitem=li_next, isFolder=True)
    
    xbmcplugin.setContent(_handle, 'movies')
    xbmcplugin.endOfDirectory(_handle)

def play_movie(movie_url, title):
    """Film lejátszása ResolveURL segítségével"""
    log(f'Movie page letöltése: {movie_url}')
    
    try:
        r = requests.get(movie_url, headers=_HEADERS, timeout=15)
        r.raise_for_status()
        html = r.text
    except Exception as e:
        log(f'Movie page hiba: {e}', xbmc.LOGERROR)
        xbmcgui.Dialog().notification(_addon_name, 'Nem sikerült letölteni a film oldalt', xbmcgui.NOTIFICATION_ERROR, 5000)
        return
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # Iframe keresése
    iframe = soup.find('div', class_='player-frame').find('iframe') if soup.find('div', class_='player-frame') else None
    embed_url = None
    
    if iframe and iframe.get('src'):
        embed_url = iframe['src']
        log(f'Iframe megtalálva: {embed_url}')
    
    if not embed_url:
        # Alternatív: sima iframe keresése
        iframe = soup.find('iframe')
        if iframe and iframe.get('src'):
            embed_url = iframe['src']
            log(f'Iframe megtalálva (alternatív): {embed_url}')
    
    if not embed_url:
        xbmcgui.Dialog().notification(_addon_name, 'Nem található videó forrás!', xbmcgui.NOTIFICATION_ERROR, 5000)
        log('Nincs iframe a movie.php oldalon', xbmc.LOGERROR)
        return
    
    # ResolveURL használata a videó URL feloldásához
    log(f'ResolveURL hívás: {embed_url}')
    
    try:
        resolved_url = resolveurl.resolve(embed_url)
        
        if resolved_url and resolved_url != embed_url:
            log(f'ResolveURL sikeres: {resolved_url[:100]}...')
            
            # Lejátszás indítása
            play_item = xbmcgui.ListItem(path=resolved_url)
            video_info = play_item.getVideoInfoTag()
            video_info.setTitle(title)
            
            play_item.setProperty('IsPlayable', 'true')
            
            xbmcplugin.setResolvedUrl(_handle, True, listitem=play_item)
        else:
            log(f'ResolveURL nem tudta feloldani: {embed_url}', xbmc.LOGERROR)
            xbmcgui.Dialog().notification(_addon_name, 'Nem sikerült feloldani a videó URL-t', xbmcgui.NOTIFICATION_ERROR, 5000)
    
    except Exception as e:
        log(f'ResolveURL hiba: {e}', xbmc.LOGERROR)
        xbmcgui.Dialog().notification(_addon_name, f'ResolveURL hiba: {str(e)[:50]}', xbmcgui.NOTIFICATION_ERROR, 5000)

def router(paramstring):
    """Navigáció (routing) kezelése"""
    params = dict(urllib.parse.parse_qsl(paramstring))
    log(f'Router params: {params}')
    
    if not params:
        # Főmenü megjelenítése
        main_menu()
    elif params.get('mode') == 'list':
        # Legújabb filmek listázása
        page = int(params.get('page', 1))
        list_movies(page=page)
    elif params.get('mode') == 'search':
        # Keresés
        search_movies()
    elif params.get('mode') == 'categories':
        # Kategóriák listázása
        list_categories()
    elif params.get('mode') == 'category':
        # Kategória szerinti listázás
        category = params.get('category')
        page = int(params.get('page', 1))
        list_movies_by_category(category, page=page)
    elif params.get('mode') == 'play':
        # Film lejátszása
        movie_url = params.get('url')
        title = params.get('title', 'Ismeretlen')
        play_movie(movie_url, title)
    else:
        raise ValueError(f'Ismeretlen mód: {paramstring}')

if __name__ == '__main__':
    router(sys.argv[2][1:])