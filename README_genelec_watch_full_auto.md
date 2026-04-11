# Genelec full-auto vahti

Tämä paketti valvoo uusia Genelec-osumia useilta sivustoilta ja lähettää ilmoituksen WhatsAppiin, Discordiin tai sähköpostiin.

## Mukana olevat lähteet

Oletuksena päällä:
- Huutokaupat.com
- Huuto.net
- Kiertonet
- Huutomylly
- Hifiharrastajat
- Muusikoiden.net
- eBay
- Reverb

Oletuksena pois päältä:
- Tori.fi
- Facebook Marketplace

## Miksi Tori on pois päältä?

Torin sivuilla todetaan, että säännöllinen, järjestelmällinen tai jatkuva tietojen kerääminen, tallentaminen, indeksointi tai muu kokoaminen ei ole sallittua ilman kirjallista lupaa. Siksi Tori on tässä paketissa pois päältä oletuksena.

## Miksi Facebook Marketplace ei ole mukana?

Marketplace vaatii käytännössä kirjautumisen, dynaamisen käyttöliittymän ja anti-bot-suojien käsittelyä. Se ei ole luotettava eikä hyvä ylläpidettävä vaihtoehto täysautomaattiselle yleisskriptillä.

## Asennus

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements_genelec_watch_full_auto.txt
```

## Nopea käyttö

Aja kerran:

```bash
python genelec_watch_full_auto.py --once
```

Aja jatkuvasti 30 min välein:

```bash
python genelec_watch_full_auto.py --interval 1800
```

## WhatsApp-ilmoitukset Twiliolla

1. Luo Twilio-tili ja ota käyttöön WhatsApp Sandbox tai tuotantolähettäjä.
2. Avaa `config_genelec_watch.json`.
3. Täytä:
   - `whatsapp.enabled` = `true`
   - `account_sid`
   - `auth_token`
   - `from`
   - `to`

Esimerkki:

```json
"whatsapp": {
  "enabled": true,
  "account_sid": "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "auth_token": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "from": "whatsapp:+14155238886",
  "to": "whatsapp:+358401234567"
}
```

## Discord-ilmoitukset

Täytä `discord.webhook_url` ja aseta `enabled` arvoksi `true`.

## Sähköposti-ilmoitukset

Täytä SMTP-tiedot `email`-osioon ja aseta `enabled` arvoksi `true`.

## Tori käyttöön omalla vastuulla

Voit kytkeä Torin mukaan näin:

```bash
python genelec_watch_full_auto.py --interval 1800 --enable-tori
```

Tai aseta configissa:

```json
"tori": true
```

## Ajastus Linuxissa systemd:llä

Esimerkkipalvelu:

```ini
[Unit]
Description=Genelec watcher
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/polku/projektiin
ExecStart=/polku/projektiin/.venv/bin/python /polku/projektiin/genelec_watch_full_auto.py --interval 1800
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## Huomioita

- Sivustojen HTML-rakenne voi muuttua. Yksittäisiä parser-kohtia voi silloin joutua säätämään.
- Kansainvälisissä lähteissä mukaan voi tulla myös vanhempia ja ei-Suomessa olevia kohteita.
- `seen_genelec_items.json` estää saman kohteen ilmoittamisen uudelleen.
