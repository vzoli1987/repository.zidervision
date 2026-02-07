import requests
from bs4 import BeautifulSoup
import urllib.parse
import xbmc

# NAPLÓ FUNKCIÓ HIBAKERESÉSHEZ
def log(message, level=xbmc.LOGINFO):
    xbmc.log(f"[Port.hu Scraper] {message}", level)

# Port.hu filmek leírásának kinyerése
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
