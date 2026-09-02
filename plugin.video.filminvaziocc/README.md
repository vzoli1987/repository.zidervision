# filminvaziocc Kodi-kiegészítő

Ez a közösségi `filminvaziocc` kiegészítő a `filminvazio.cc` nyilvános katalógusát teszi böngészhetővé Kodi 21.3 (Omega) alatt. A lejátszási URL-ek feloldásához a kiegészítő elsődlegesen a `script.module.zidervisionurlresolver` modult használja, a Kodi-ban telepített standard ResolveURL pedig tartalék feloldóként működik. A kiegészítő a webhely nyilvános HTML- és AJAX-válaszait használja kategóriák, keresési eredmények, filmadatlapok és a webhely által visszaadott beágyazott lejátszó-URL-ek megjelenítésére.

## Telepítés

A ZIP-fájlt másold a Kodi-eszközre, majd válaszd a **Kiegészítők → Kiegészítő-böngésző → Telepítés ZIP-fájlból** menüpontot. A telepítés után a kiegészítő a videókiegészítők között jelenik meg.

## Működés

A kezdőképernyőn elérhető az online filmek listája, az év szerinti bontás, a premierfilmek, a legnézettebb tartalmak és a keresés. Film kiválasztásakor a kiegészítő megjeleníti az adatlapból kiolvasható nyilvános forrásokat. A lejátszáskor az oldal által adott beágyazott URL kerül átadásra Kodi-nak.

## Fontos technikai korlát

A vizsgált oldal a filmekhez jelenleg `ok.ru` iframe-forrásokat ad vissza. Ez **weboldal-beágyazás**, nem közvetlen HLS/MP4 videóURL, ezért a Kodi beépített lejátszója önmagában nem minden eszközön képes lejátszani. A kiegészítő nem próbálja meg kinyerni, visszafejteni vagy megkerülni a forrásoldal védelmét. Ha az adott Kodi-rendszeren az iframe nem indul el, ehhez külön, jogszerűen használt kompatibilis lejátszó- vagy resolver-kiegészítő szükséges.

A webhely tartalmainak használatáért, valamint azok szerzői és felhasználási jogainak ellenőrzéséért a felhasználó felel. A kiegészítő kizárólag olyan tartalmakhoz használható, amelyekhez a felhasználónak joga van hozzáférni.

## Fájlok

| Fájl | Szerepe |
|---|---|
| `addon.xml` | Kodi-kiegészítő metaadatai és Omega-kompatibilis Python-függőség |
| `default.py` | Katalógus, keresés, adatlap és ResolveURL-alapú lejátszóforrás-kezelés |
| `script.module.zidervisionurlresolver` | Elsődleges Videa, IndaVideo és VK Video URL-feloldás |
| `script.module.resolveurl` | Tartalék hoster-URL-feloldás, például OK.ru esetén |
