# Poster Studio

Mobile poster / content creator (Python + Kivy). Android APK only.

## Get the APK (from Termux)
    pkg install git
    git init && git add . && git commit -m "Poster Studio"
    git branch -M main
    git remote add origin https://github.com/<you>/<repo>.git
    git push -u origin main
Then open the repo on GitHub: Actions > Build APK > download the
`poster-studio-apk` artifact, unzip it and install the .apk.
The first build takes 20 to 40 minutes; later ones are faster.

## Fonts
Drop any .ttf/.otf into `fonts/`; it appears in the font picker.
Bundled (SIL OFL): Lobster, Pacifico, Bebas Neue, Anton, Abril Fatface,
Righteous, Bangers.
