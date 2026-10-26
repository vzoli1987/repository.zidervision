# Mozipremierek.hu – Kodi-kiegészítő

**Kodi 21.3-hoz készült katalógusböngésző.** A Mozipremierek.hu nyilvános premier-, streaming- és filmadatlap-adatait jeleníti meg.

## Funkciók

- Mozis premierek, online nézhető filmek, műfajok és streaming-szolgáltatók szerinti böngészés
- Rövid és részletes filmleírás, fanart és részletes Kodi-filmmetaadatok: eredeti cím, gyártási év, rendező, szereplők, ország, korhatár, játékidő, premierdátum, forgalmazó, gyártó stúdiók és IMDb-azonosító
- Filmeken jobb klikk → **Keresés az stb.hu-n**; a NapiFilm kereső nem szerepel a jobbklikkes menüben
- A filmre kattintva az adatlap megnyílik, az adapteres hostkeresés pedig automatikusan elindul
- A filmnézetben a lila színű előzetesek a hostlista fölött jelennek meg; az előzetes `>>` jelölést használ, hogy Kodi-skin betűkészletében se vesszen el az ikon
- A felesleges „Adatlap a Mozipremierek.hu-n” listaelem eltávolítva; az előzetesekről is töröltük a nem hasznos adatlap context menüt
- Az adapteres keresés színes folyamatablaka jelzi a keresési fázist, az aktuális adaptert, a lépésarányt és a külön színnel kiemelt 4K, 1080p, 720p, HD, SD, DVD és CAM forrásszámokat; a hostlista előtt nincs külön összesítő sor
- A hostok minőség szerint legjobbtól gyengébb felé rendezve, sorszám nélkül jelennek meg: `minőség | host | adapter | nyelv`; az azonos adapter/host/minőség/nyelv ismétlődő sorokat összevonja
- Nincs külön automatikus lejátszás sor: bármelyik host sorra kattintva először pontosan annak a sornak a közvetlen linkjét vagy saját lejátszóútvonalát indítja; közvetlen link feloldási hibája után a következő sorra lép. A Kodi által már átvett, de később lejátszás közben hibázó plugin-stream után az addon nem minden esetben kap visszajelzést a továbblépéshez.
- Lejátszáskor külön progress bar mutatja, éppen melyik hostot és hányadikként próbálja feloldani/ellenőrizni; sikeres feloldáskor átadja a streamet Kodinak és bezárul. A FilmDepo adatlap összes `FD_URLS` playerét külön hostként listázza, az előzetest kihagyja, és a külön adatlapokról jövő linkeket sem vonja össze.
- A sikeresen összegyűjtött hostlista filmcímenként legfeljebb 1 óráig cache-ben marad, ezért a lejátszás leállítása utáni Kodi-mappafrissítés nem indít új adapterkeresést
- A Kodi saját szülőmappa-navigációja használatos; nincs külön kézi „Előző oldal” listaelem
- Adapterek: Filminvázió.pro, Filminvázió.cc, FilmDepo.hu és NapiFilm
- A közvetlen hostlinkekhez opcionális ResolveURL-feloldás; ha ez nem érhető el, ahol lehet, a forrás-addon meglévő lejátszóútvonala használható

## Telepítés

1. Töltsd le a `plugin.video.mozipremierek-1.7.5.zip` fájlt.
2. Kodi: **Kiegészítők → Kiegészítőböngésző → Telepítés ZIP-fájlból**.
3. Válaszd ki a ZIP-et. Ha a Kodi kéri, előtte engedélyezd az ismeretlen forrásokat.
4. Az stb.hu jobbklikkes kereséshez telepítsd a `plugin.video.stb_hu` addont.
5. Az előzetesekhez legyen telepítve a Kodi YouTube addon (`plugin.video.youtube`).
6. A közvetlen hostlinkekhez telepítsd a Kodi repository-ból a **ResolveURL** kiegészítőt. Ha telepítve van, az opcionális `script.module.zidervisionurlresolver` modult is használja; ezek hiányában, ahol lehetséges, a forrás addon saját lejátszó-route-ja marad tartalék.

## Hozzáférési korlátok

A kiegészítő nyilvános HTTP-kéréseket használ. Cloudflare-ellenőrzést, CAPTCHA-t, bejelentkezést vagy más hozzáférési védelmet nem kerül meg; ha egy oldal blokkolja a kérést, az adott adapter találat nélkül tér vissza.
