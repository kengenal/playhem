# playhem
Simple music bot using slash commands

## System requirements:
 * ffmpeg
 * Opus
 
## Instalation
```
foo@foo$ pip install -r requirements.txt
```

## You can run web layer which redirect to invite link or just run bot
### Run web
```
foo@foo$ python main.py web 8000
```

### Run bot
```
foo@foo$ python main.py 
```

# How to run on heroku
For that you need 3 build packs python, ffmpeg and Opus.
Procfile is ready but ifyou wont web layer, you need to add to Procfile
```
web: python manage.py web $PORT
```
