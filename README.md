# PyADPS - python lib and CLI for Amateur Digital Post Service

## Installing

```
pip install -r requirements.txt  # or requirements-dev for development
pip install -e .
```

## Generating test repository

```
python pyadps/scripts/generate_data.py /path/to/repository
```

## Benchmark commands

### Filtering

```
time adps search [REPO] --output-format=COUNT --datetime-from=2022-01-10 --datetime-to=2022-07-10 --latitude=55.7558 --longitude=37.6173 --radius-meters=35000 --damping-distance-latitude=55.7558 --damping-distance-longitude=37.6173
```

### Copying

```
time adps search [SOURCE_REPO] --output-format=COUNT --datetime-from=2022-01-10 --datetime-to=2022-07-10 --latitude=55.7558 --longitude=37.6173 --radius-meters=35000 --damping-distance-latitude=55.7558 --damping-distance-longitude=37.6173 --target-repo-folder [TARGET_REPO] --copy
```

### Delete

```
time adps search [REPO] --output-format=COUNT --datetime-from=2022-01-10 --datetime-to=2022-07-10 --latitude=55.7558 --longitu
de=37.6173 --radius-meters=35000 --damping-distance-latitude=55.7558 --damping-distance-longitude=37.6173 --delete
```

## 3rd party files:

worldcities.csv - downloaded from https://simplemaps.com/data/world-cities , Creative Commons Attribution 4.0
