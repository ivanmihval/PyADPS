from csv import DictReader
from typing import NamedTuple, Optional

import geopy.distance


class Coords(NamedTuple):
    lat: float
    lon: float


class City(NamedTuple):
    name: str
    name_ascii: str


def search_city_coords_by_name(city_name: str, cities_csv_path: str) -> Optional[Coords]:
    with open(cities_csv_path, newline='') as csv_file:
        reader = DictReader(csv_file)
        lower_city_name = city_name.lower()
        for row in reader:
            lower_csv_city_name: str = row['city'].lower()
            lower_csv_ascii_city_name: str = row['city_ascii'].lower()

            if lower_city_name in lower_csv_city_name or lower_city_name in lower_csv_ascii_city_name:
                return Coords(float(row['lat']), float(row['lng']))

    return None


def search_nearest_city_by_coords(coords: Coords, cities_csv_path: str) -> Optional[City]:
    min_distance: Optional[float] = None
    min_distance_city: Optional[City] = None

    with open(cities_csv_path, newline='') as csv_file:
        reader = DictReader(csv_file)
        for row in reader:
            lat = float(row['lat'])
            lon = float(row['lng'])

            distance = geopy.distance.distance(coords, (lat, lon)).m
            if min_distance is None or distance < min_distance:
                min_distance = distance
                min_distance_city = City(row['city'], row['city_ascii'])

    return min_distance_city
