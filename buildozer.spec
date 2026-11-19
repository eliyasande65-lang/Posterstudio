[app]
title = Poster Studio
package.name = posterstudio
package.domain = org.elias
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf,otf
source.exclude_dirs = .github,bin,.buildozer
version = 1.0.0

requirements = python3,kivy==2.3.0,pillow,plyer,pyjnius,android

icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/presplash.png
android.presplash_color = #1a1535

orientation = portrait
fullscreen = 0

android.permissions = READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_IMAGES
android.api = 33
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
android.ndk = 25b
android.accept_sdk_license = True
android.allow_backup = True

p4a.branch = v2024.01.21

[buildozer]
log_level = 1
warn_on_root = 1
