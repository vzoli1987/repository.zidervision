import requests
from bs4 import BeautifulSoup
from datetime import datetime
import urllib.parse
import xbmc
import xbmcgui

# NAPLÓ FUNKCIÓ HIBAKERESÉSHEZ
def log(message, level=xbmc.LOGINFO):
    xbmc.log(f"[Műsor TV Debug] {message}", level)

# A port.hu filmek leírásának kinyerése
def get_port_film_description(movie_url):
    try:
        response = requests.get(movie_url)
        if response.status_code != 200:
            log(f"Hiba történt a film oldalának lekérésekor: {response.status_code}", xbmc.LOGERROR)
            return "Nincs leírás elérhető."

        soup = BeautifulSoup(response.text, 'html.parser')

        # A film leírása
        description = soup.find('div', class_='description')
        if description:
            description_text = description.find('article').text.strip()
        else:
            description_text = "Nincs leírás elérhető."

        return description_text

    except Exception as e:
        log(f"Hiba a port.hu film adatainak lekérésekor: {str(e)}", xbmc.LOGERROR)
        return "Nincs leírás elérhető."

# Port.hu keresés a film címével
def search_port_movies(title):
    search_url = f"https://port.hu/kereso?type=movie&q={urllib.parse.quote(title)}"
    try:
        response = requests.get(search_url)
        if response.status_code != 200:
            log(f"Hiba történt a port.hu keresésekor: {response.status_code}", xbmc.LOGERROR)
            return None

        soup = BeautifulSoup(response.text, 'html.parser')
        # Keresés találatainak kigyűjtése
        search_results = soup.find_all('a', class_='title', href=True)

        # Ha találunk találatokat, az elsőt használjuk
        if search_results:
            movie_url = "https://port.hu" + search_results[0].get('href')
            return movie_url
        else:
            log(f"Nincs találat a port.hu keresésre a(z) {title} címre.", xbmc.LOGWARNING)
            return None

    except Exception as e:
        log(f"Hiba történt a port.hu keresés során: {str(e)}", xbmc.LOGERROR)
        return None

# A műsorok listájának beolvasása a musor.tv-ről
def get_programs():
    url = "https://musor.tv/romantikus_filmek"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    log(f"URL lekérdezése: {url}")
    
    try:
        response = requests.get(url, headers=headers)
        log(f"HTTP válaszkód: {response.status_code}")
        
        if response.status_code != 200:
            xbmcgui.Dialog().notification("Hiba", f"HTTP hiba: {response.status_code}", xbmcgui.NOTIFICATION_ERROR)
            return []

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # HTML struktúra ellenőrzése
        tables = soup.find_all('table', {'class': 'showeventtable'})
        log(f"Műsor táblázatok száma: {len(tables)}")

        programs = []
        for table in tables:
            program = {}
            
            # Időpont
            time = table.find('span', {'class': 'showeventtime'})
            if time:
                event_time = time.get('content')
                if event_time:
                    program['time'] = datetime.fromisoformat(event_time).strftime('%Y-%m-%d %H:%M:%S')

            # Csatorna neve és logója
            channel = table.find('a', {'class': 'channelheaderlink'})
            if channel:
                # Csatorna neve az 'alt' attribútumból
                img_tag = channel.find('img', {'src': True})
                if img_tag:
                    channel_name = img_tag.get('alt', '')
                    program['channel'] = channel_name
                    log(f"Csatorna neve: {channel_name}")
                    
                    # Csatorna logója
                    logo_url = "https://musor.tv" + img_tag.get('src')
                    program['logo_url'] = logo_url
                    log(f"Csatorna logó URL: {logo_url}")

            # Film címe és URL
            title_tag = table.find_all('a', href=True)
            if title_tag:
                for tag in title_tag:
                    log(f"Talált <a> tag szövege: {tag.text.strip()}")
                    if tag.text.strip():
                        program['title'] = tag.text.strip()
                        program['url'] = "https://musor.tv" + tag.get('href')  # Film URL-ja
                        break
                if 'title' not in program:
                    log("Nem találtunk címeket a <a> tagekben.", xbmc.LOGWARNING)
                    program['title'] = "Ismeretlen cím"
            else:
                log("Nem található <a> tag.", xbmc.LOGWARNING)
                program['title'] = "Ismeretlen cím"

            # Nagyobb bélyegkép
            img_tag = table.find('img', {'class': 'showeventimg'})
            if img_tag:
                large_img_url = "https://musor.tv" + img_tag.get('src').replace('small', 'normal')
                program['img_url'] = large_img_url
                log(f"Nagyobb bélyegkép URL: {large_img_url}")

            # Naplózás
            log(f"Program: {program}")
            programs.append(program)

        return programs

    except Exception as e:
        log(f"Hiba történt: {str(e)}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification("Hiba", "Nem sikerült lekérni a műsorokat.", xbmcgui.NOTIFICATION_ERROR)
        return []
