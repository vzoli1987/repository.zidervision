# MoziPont katalógus Kodi-kiegészítő

Az azonosító megmaradt: `plugin.video.mozipont.catalog`. A csomag Kodi 19 vagy újabb verzióhoz készült, és a manifest a `script.module.resolveurl` függőséget használja.

## Telepítés

1. A Kodi kiegészítőkezelőjében válaszd a **Telepítés ZIP-fájlból** lehetőséget.
2. Válaszd ki a `plugin.video.mozipont.catalog-0.3.0.zip` fájlt.
3. Ha Kodi kéri, engedélyezd a külső tárolókból történő telepítést.
4. A kiegészítőt a Videók → Kiegészítők alatt találod.

A telepítés frissíti az azonosítót megtartó meglévő kiegészítőt. Biztonsági mentésként előtte mentsd el a jelenlegi kiegészítő mappáját.

## Működés

A katalóguslisták és az API-metaadatok lemez-cache-be kerülnek. A katalógusoldalak rövid ideig, a metaadatok 15 percig használják a cache-t. A trailer nélküli, API által megerősített film listaeleme közvetlenül lejátszható Kodi `setResolvedUrl` útvonalon, így leállítás után a Kodi visszatér a listához, nem indítja újra automatikusan a filmet. Trailerrel rendelkező film adatlapot nyit; ott külön választható a lejátszás vagy az előzetes.

A külső videó URL-jét kizárólag a MoziPont oldal iframe-jének nyilvános `src`, `data-t` vagy `data-src` attribútumából olvassa be. Nem dekódol rejtett/obfuszkált adatot. A lejátszhatóságot a külső tárhely, a ResolveURL és a Kodi környezete is befolyásolhatja.

A Kodi naplójában a `[MoziPont]` előtaggal találhatók a cache-találatok, hálózati kérések és hibák.
