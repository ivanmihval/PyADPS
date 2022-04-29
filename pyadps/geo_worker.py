# -*- coding: utf-8 -*-
from csv import DictReader
from typing import NamedTuple, Optional

import geopy.distance


class CoordsTuple(NamedTuple):
    lat: float
    lon: float


class City(NamedTuple):
    name: str
    name_ascii: str


class CityWithPopulation(NamedTuple):
    name: str
    name_ascii: str
    population: int
    latitude: float
    longitude: float


def search_city_coords_by_name(city_name: str, cities_csv_path: str) -> Optional[CoordsTuple]:
    with open(cities_csv_path, newline='') as csv_file:
        reader = DictReader(csv_file)
        lower_city_name = city_name.lower()
        for row in reader:
            lower_csv_city_name: str = row['city'].lower()
            lower_csv_ascii_city_name: str = row['city_ascii'].lower()

            if lower_city_name in lower_csv_city_name or lower_city_name in lower_csv_ascii_city_name:
                return CoordsTuple(float(row['lat']), float(row['lng']))

    return None


def search_nearest_city_by_coords(coords: CoordsTuple, cities_csv_path: str) -> Optional[City]:
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


def search_most_populated_city_by_coords(
        latitude: float,
        longitude: float,
        cities_csv_path: str,
        threshold_meters: float = 10 * 1000  # 10 km
) -> Optional[CityWithPopulation]:
    most_populated_city: Optional[CityWithPopulation] = None

    with open(cities_csv_path, newline='') as csv_file:
        reader = DictReader(csv_file)
        for row in reader:
            city_latitude = float(row['lat'])
            city_longitude = float(row['lng'])
            population_str = row['population']
            if population_str:
                population = int(float(population_str))
            else:
                continue

            if most_populated_city and most_populated_city.population > population:
                continue

            distance = geopy.distance.distance((latitude, longitude), (city_latitude, city_longitude)).m
            if distance < threshold_meters:
                if most_populated_city is None or most_populated_city.population < population:
                    most_populated_city = CityWithPopulation(
                        name=row['city'],
                        name_ascii=row['city_ascii'],
                        population=population,
                        latitude=city_latitude,
                        longitude=city_longitude,
                    )

    return most_populated_city
