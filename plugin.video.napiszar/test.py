import re
import requests

BASE_URL = "https://www.napiszar.biz/kategoria/video/"
BASE2_URL = "https://www.napiszar."

def video_url_kinyerese_az_entry_bol(url):
    # Weboldal lekérése, User-Agent hozzáadása a kéréshez
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print(f"Hiba a weboldal lekérésekor: {response.status_code}")
        return []
    
    html = response.text
    print(html)  # Debugging: Kiírjuk a teljes HTML-t, hogy ellenőrizzük, benne vannak-e TikTok linkek

    # Keresés a <div class="entry"> és </div> közötti tartalomra
    entry_start = html.find('<div class="entry">')
    entry_end = html.find('</div>', entry_start)

    if entry_start == -1 or entry_end == -1:
        print(f"Nem található az 'entry' szekció ezen az oldalon: {url}")
        return []

    # A tartalom kinyerése a <div class="entry"> és </div> közötti részből
    entry_html = html[entry_start:entry_end + 6]  # +6 az </div> taghez
    
    # URL-ek kinyerése <a href="...">, <iframe src="...">, <video src="..."> és TikTok videók
    video_urls = re.findall(r'href="(https?://[^\"]+)"', entry_html)  # <a href="...">
    iframe_urls = re.findall(r'src="(https?://[^\"]+)"', entry_html)  # <iframe src="...">
    video_tag_urls = re.findall(r'<video[^>]+src="(https?://[^\"]+)"', entry_html)  # <video src="...">
    
    # TikTok URL-ek kinyerése a cite és data-video-id attribútumokból
    tiktok_urls = re.findall(r'cite="(https://www\.tiktok\.com/[^"\']+)"', entry_html)
    print("TikTok URLs from 'cite' attribute:", tiktok_urls)
    
    tiktok_data_video_ids = re.findall(r'data-video-id="(\d+)"', entry_html)
    tiktok_urls_from_data = [f"https://www.tiktok.com/@username/video/{video_id}" for video_id in tiktok_data_video_ids]
    print("TikTok URLs from 'data-video-id' attribute:", tiktok_urls_from_data)

    # Az összes kinyert URL egyesítése
    all_urls = video_urls + iframe_urls + video_tag_urls + tiktok_urls + tiktok_urls_from_data

    # Kép URL-ek és BASE_URL, BASE2_URL kizárása
    filtered_urls = [url for url in all_urls if not url.lower().endswith((".jpg", ".jpeg", ".png", ".gif")) and BASE_URL not in url and not url.startswith(BASE2_URL)]

    return filtered_urls

# Példa használat:
page_url = "https://www.napiszar.biz/mi-szarunk/2024/12/29/molnar-janka-videok"
video_urls = video_url_kinyerese_az_entry_bol(page_url)

print("Kinyert videó URL-ek (beleértve TikTok linkeket):")
for video_url in video_urls:
    print(video_url)

