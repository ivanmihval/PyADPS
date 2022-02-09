from pathlib import PurePath

import pytest

from pyadps.geo_worker import City, CoordsTuple, search_city_coords_by_name, search_nearest_city_by_coords

WORLDCITIES_CSV_PATH = str(PurePath(__file__).parents[1] / 'static_files/worldcities/worldcities.csv')


class TestSearchCityCoordsByName:
    @pytest.mark.parametrize('city_name, lat, lon', [
        ['osAka', 34.75, 135.4601],
        ['varna', 43.2114, 27.9111],
        ['Unknown City', None, None]
    ])
    def test_ok(self, city_name: str, lat: float, lon: float):
        city_coords = search_city_coords_by_name(city_name, WORLDCITIES_CSV_PATH)
        if city_coords is not None:
            assert city_coords.lat == lat
            assert city_coords.lon == lon


class TestSearchNearestCityByCoords:
    @pytest.mark.parametrize('lat, lon, city_name, city_name_ascii', [
        [50.2745, 28.7005, 'Zhytomyr', 'Zhytomyr'],
        [53.3595118, -6.3086148, 'Dublin', 'Dublin'],
        [-23.5501, -46.6203, 'São Paulo', 'Sao Paulo']
    ])
    def test_ok(self, lat: float, lon: float, city_name: str, city_name_ascii: str):
        city = search_nearest_city_by_coords(CoordsTuple(lat, lon), WORLDCITIES_CSV_PATH)
        assert city == City(city_name, city_name_ascii)
