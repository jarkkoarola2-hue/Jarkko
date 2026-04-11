Sähköposti-ilmoitusten käyttöönotto

1. Korvaa GitHub-repon tiedosto genelec_watch_full_auto.py tällä uudella versiolla.
2. GitHub Actions workflow voi jäädä ennalleen, jos siellä on:
   python genelec_watch_full_auto.py

GitHub Secrets:
- ENABLE_EMAIL = true
- SMTP_HOST = smtp.gmail.com
- SMTP_PORT = 587
- SMTP_USERNAME = oma@gmail.com
- SMTP_PASSWORD = Gmail App Password
- EMAIL_FROM = oma@gmail.com
- EMAIL_TO = vastaanottaja@gmail.com

Testi:
- muuta workflow-tiedoston Run script -rivi hetkeksi muotoon:
  run: python genelec_watch_full_auto.py --send-test-email

Kun testiviesti tuli:
- vaihda takaisin:
  run: python genelec_watch_full_auto.py
