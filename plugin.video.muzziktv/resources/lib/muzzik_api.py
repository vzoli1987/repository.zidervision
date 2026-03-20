import requests
import json

class MuzzikAPI:
    BASE_URL = "https://prd-muzzikbalkan.spectar.tv/client_api.php"
    APP_ID = "556354"
    UUID = "69b38b87be9c34-63893935"

    def __init__(self, email, password):
        self.email = email
        self.password = password
        self.session_id = None
        self.access_token = None
        self.streaming_token = None
        self.subscriber_id = None

    def get_session(self):
        # A korábbi curl teszt alapján a session_id-t a bejelentkezés előtt a config-ból kellene kapni, 
        # de ha üres, akkor a bejelentkezésnél a session_id-t a szerver generálja vagy fix.
        # A böngészőben látott session_id: 2b12edd2f7ff43fca36e14b9c1e39891
        # Próbáljuk meg először session_id nélkül, vagy a böngészőben látottal.
        self.session_id = "2b12edd2f7ff43fca36e14b9c1e39891"
        return self.session_id

    def login(self):
        if not self.session_id:
            self.get_session()
        
        url = f"{self.BASE_URL}/user/login/session_id/{self.session_id}/format/json"
        payload = {
            "username": self.email,
            "password": self.password
        }
        headers = {"Content-Type": "application/json"}
        response = requests.post(url, json=payload, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            # A tesztek alapján ez a fix token szükséges a csatornalistához
            self.access_token = "3d51b66d85ef7df644198f05cdef7ef09f598a85"
            
            # A streaming token és subscriber_id viszont dinamikus a login válaszból
            if 'userData' in data:
                user_data = data['userData']
                self.streaming_token = user_data.get('secure_streaming_token')
                self.subscriber_id = user_data.get('subscriber_id') or user_data.get('id')
            else:
                self.streaming_token = data.get('secure_streaming_token')
                self.subscriber_id = data.get('subscriber_id') or data.get('id')
                
            return True if self.streaming_token else False
        return False

    def get_channels(self):
        if not self.access_token:
            return []

        url = f"{self.BASE_URL}/channel/list/session_id/{self.session_id}/access_token/{self.access_token}/format/json/cache/1"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            # Ha a válasz közvetlenül egy lista, akkor az a csatornalista
            if isinstance(data, list):
                return data
            # Ha szótár, akkor keressük a 'channel' kulcsot
            channels = data.get('channel', [])
            if isinstance(channels, dict):
                return [channels]
            return channels
        return []

    def get_stream_url(self, channel_id, external_id=None):
        # Ha van external_id (pl. mts-a7), használjuk azt az URL-ben
        stream_name = external_id if external_id else "mts-3-ao"
        url = (
            f"https://muzzikbalkan-live.morescreens.com/{stream_name}/playlist.m3u8?"
            f"id={stream_name}&video_id={channel_id}&token={self.streaming_token}&"
            f"authority_instance_id=spectar-prd-muzzikbalkan&profile_id={self.subscriber_id}&"
            f"application_installation_id={self.APP_ID}&uuid={self.UUID}&"
            f"subscriber_id={self.subscriber_id}&application_id=web&"
            f"detected_delivery_method=hls&playlist_template=nginx"
        )
        return url
