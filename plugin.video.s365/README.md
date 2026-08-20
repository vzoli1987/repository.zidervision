# S365 – Kodi 21.3 videóbővítmény

Ez a projekt **Kodi 21.3-hoz** készült Python 3 bővítmény. A keresési találatokból és a katalógusból a sorozatot először **évad**, majd azon belül **epizód** szinten jeleníti meg. Az epizód „Linkek megtekintése” lépéséből kinyert videóforrásokat ResolveURL-lel oldja fel.

## Telepítés

A kiadott `plugin.video.s365-0.6.10.zip` fájlt másold a Kodi eszközre. Ezután a Kodi főmenüben válaszd a **Kiegészítők → Telepítés ZIP-fájlból** lehetőséget, keresd ki a ZIP-et, majd a **Videókiegészítők** között indítsd el az **S365** bővítményt. A bővítmény a `script.module.resolveurl` **5.1.0 vagy újabb** függőséget deklarálja, ezért a ResolveURL-nek a Kodi-ban elérhetőnek kell lennie a telepítéskor. Ez a kiadás Kodi 21.3 v1 formátumú beállításfájlt használ, így a helyi előzmények és az elérhetőségi gyorsítótár beállításai is regisztrálódnak.

## Navigáció és lejátszási feloldás

A normál útvonal: **sorozat → évad → epizód-mappa → Linkek megtekintése → forrás → lejátszás**. Az epizód nem közvetlenül lejátszható elem, hanem mappa: ettől a Kodi a forrásválasztó listát jeleníti meg. A bővítmény a SRZT forrástáblájának minden `MEGNÉZ` hivatkozását kiolvassa. A lista elsődleges címkéje csak a rövid szolgáltatónév, például `VOE` vagy `MIXDROP`; az ismétlődő szolgáltatók sorszámot kapnak, a hangsáv pedig másodlagos mezőbe kerül. A relatív `embed.php` hivatkozásból kiolvassa a tényleges külső videóhoszt URL-jét, majd azt a ResolveURL `HostedMediaFile(...).resolve()` mechanizmusának adja át. A közvetlen HLS/MP4-forrásokat a Kodi közvetlenül indítja.

## Folytatás és keresési előzmények

A **Folytatás** nézet automatikusan megjegyzi azokat az epizódokat, amelyeknek megnyitottad a forráslistáját. Az epizódok legfeljebb 24 elemig, legutóbbi megnyitás szerinti sorrendben tárolódnak, és egy kattintással visszanyitják a forrásválasztót. A `Folytatás törlése` kiüríti ezt a listát.

A főmenü **Keresés** pontja egy külön keresési nézetet nyit. Itt az **Új keresés** mellett ugyanebben a listában megjelennek a korábbi keresések, valamint az **Előzmények törlése** művelet. A Folytatás és a keresési előzmények készüléken, a Kodi-kiegészítő helyi beállításaiban tárolódnak.

A bővítmény az évad- és epizódlisták megnyitásakor automatikusan ellenőrzi a forrásállapotot. A vizsgálat alatt a Kodi **Források ellenőrzése** folyamatjelzőt jelenít meg, benne az ellenőrzött évad vagy epizód sorszámával és címével; a folyamat megszakítható. Kodi 21.3 alatt a folyamatjelző egyetlen, kompatibilis üzenetsorban jeleníti meg ezeket az adatokat. A `Szinkronizálás alatt` választ adó, illetve tényleges videóforrást nem tartalmazó epizódok nem jelennek meg. Az az évad, amelyben egyetlen elérhető epizód sincs, szintén kimarad a sorozat nézetéből. Az eredményt húsz percig helyben gyorsítótárazza, hogy a későbbi megnyitások gyorsabbak legyenek; átmeneti hálózati hiba esetén nem rejt el tartalmat.

A kategórialapozás a webhely számozott útvonalait is felismeri, de a Kodi-listát nem zsúfolja tele oldalszámokkal. A lista végén csak egyetlen menüpont jelenik meg: **Következő oldal · aktuális / összes**. Például a `/friss-epizodok/2` nézetben a `Következő oldal · 2 / 5` elem közvetlenül a `/friss-epizodok/3` címre vezet. A számozott katalóguslapoknál a bővítmény nem ágyazza be a teljes külső webcímet a Kodi plugin-URL-jébe: csak a kategória azonosítóját és az oldalszámot küldi át, majd ebből építi vissza a pontos célcímet. A bővítmény a kizárólag az `EZ IS TETSZHET` című, minden oldalon azonos ajánlósáv kezdetétől levágja a dokumentumot; a főoldal más, tényleges katalógust tartalmazó blokkjai ettől változatlanul megmaradnak. Így az ajánlóblokk elemei nem kerülnek a Kodi-listába, de egyik nézet sem marad üres. Az oldalváltáskor a bővítmény kifejezetten frissíti a Kodi-listát is, ezért nem maradhat a korábbi oldal tartalma a képernyőn. Az utolsó oldalon ez az elem nem látszik.

A forráslista közvetlenül a lejátszható szolgáltatókkal indul; nincs külön ellenőrző vagy várakoztató menüpont. A szolgáltatás által ténylegesen közölt hangsáv-, felirat- vagy technikai jelölések a forrás másodlagos adataként jelennek meg, de a bővítmény nem találgat HD/SD minőséget vagy játékidőt.

A főmenü és a forrásnevek Kodi-kompatibilis színkódolást használnak. A bővítmény saját, narancs–türkiz S365 ikont használ; a tényleges listanézet a telepített Kodi skintől függ.

## Lejátszási API (opcionális, ajánlott éles integráció)

A saját feloldó API elsőbbséget élvez a HTML-forráslista előtt. Megbízható, hozzáférés-szabályozott éles lejátszáshoz állítsd be a **Saját lejátszási API sablonja** értéket a bővítmény beállításaiban.

A `Saját lejátszási API sablonja` értéke például:

```text
https://api.example.hu/kodi/resolve?slug={slug}
```

A végpont JSON-válasza:

```json
{
  "label": "Magyar szinkron",
  "url": "https://media.example.hu/path/episode.m3u8",
  "headers": {
    "Authorization": "Bearer rövid-élettartamú-token",
    "Referer": "https://sorozat365.hu/"
  }
}
```

A `{slug}` helyőrző az S365 epizódazonosítójára cserélődik. A `{episode_url}` helyőrző a teljes epizódoldal URL-jét kapja URL-kódolt alakban. Amennyiben az API hitelesítést igényel, a token a `Lejátszási API token` beállításban adható meg, és a kérés `Authorization: Bearer …` fejlécében kerül továbbításra.

## Projektstruktúra

| Útvonal | Szerep |
|---|---|
| `addon.xml` | Kodi-manifeszt és Python 3-függőség |
| `default.py` | Kodi belépési pont |
| `resources/lib/router.py` | Sorozat–évad–epizód navigáció, forráslista és Kodi-lejátszás |
| `resources/lib/s365.py` | Katalógus-, keresési, évad-, epizód- és ResolveURL-adapter |
| `resources/settings.xml` | Szolgáltatás- és API-beállítások |

## Üzemeltetési megjegyzés

A bővítmény a meglévő HTML-katalógust olvassa; külön az `e/...` évadoldal `seasons` és `episodes` blokkját, valamint az SRZT oldalon a forrástábla sorait dolgozza fel. Az oldal HTML-szerkezetének módosulása esetén a `resources/lib/s365.py` parserét frissíteni kell. Hosszú távon stabilabb megoldás a leírt saját JSON API használata.
