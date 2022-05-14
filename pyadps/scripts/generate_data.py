# -*- coding: utf-8 -*-
import json
import os
import sys
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import PurePath

import geopy.distance
import numpy as np
import pandas as pd

from pyadps.helpers import calculate_hashsum
from pyadps.mail import CoordsData, FileAttachment, Mail

# [PyADPS]$ time python -m pyadps.scripts.generate_data /path/to/adps_repo

SEED = 12345


@dataclass
class City:
    name: str
    country_code: str
    coords: CoordsData


# https://stackoverflow.com/questions/18622781/why-is-numpy-random-choice-so-slow
class FastRandomGenerator:
    def __init__(self, np_rng):
        self._rng = np_rng

    def integers(self, *args, **kwargs):
        return self._rng.integers(*args, **kwargs)

    def bytes(self, *args, **kwargs):
        return self._rng.bytes(*args, **kwargs)

    def random(self, *args, **kwargs):
        return self._rng.random(*args, **kwargs)

    def choice(self, collection: list, *args):
        if len(collection) < 100:
            return self._rng.choice(collection, *args)

        count = 1
        if args:
            count = args[0]

        indexes = set()
        for _ in range(count):
            attempts = 100
            found_number = False
            for attempt in range(attempts):
                idx = self.integers(0, len(collection))
                if idx not in indexes:
                    indexes.add(idx)
                    found_number = True
                    break

            if not found_number:
                raise Exception('Could not build unique set')

        if count == 1:
            return collection[indexes.pop()]
        else:
            return [collection[idx_] for idx_ in indexes]


def get_cumulative_list(dataframe):
    population_list = dataframe['population'].tolist()

    cumulative_list = []
    s = 0
    for population_entry in population_list:
        population_value = population_entry if not pd.isna(population_entry) else 0
        cumulative_list.append(population_value + s)
        s += population_value

    return cumulative_list


def choose_city_by_random_value(
    value: float,
    target_dataframe,
    population,
    cumulative_population_list
) -> City:
    """value is float from 0 to 1"""
    people_num = value * population
    city_idx = bisect_left(cumulative_population_list, people_num)
    city_row = target_dataframe[city_idx:city_idx + 1]

    return City(
        name=city_row['city_ascii'].tolist()[0],
        country_code=city_row['iso2'].tolist()[0],
        coords=CoordsData(city_row['lat'].tolist()[0], city_row['lng'].tolist()[0]))


def get_file_sizes_bytes(number_of_files: int, sum_bytes: int, rng: FastRandomGenerator) -> list:
    sizes_rnd = [rng.random() for _ in range(number_of_files)]
    sizes_cum_sum = np.cumsum(sizes_rnd)
    rate_coef = sum_bytes / sizes_cum_sum[-1]
    boundaries_byte_numbers = [round(rate_coef * el) for el in sizes_cum_sum]
    return boundaries_byte_numbers


def choose_attachments_for_mail(big_attachments: list, short_attachments: list, rng: FastRandomGenerator) -> list:
    random_value = rng.random()
    if 0 <= random_value < 0.05:
        return []
    elif 0.05 <= random_value < 0.10:
        return [rng.choice(big_attachments)]
    elif 0.10 <= random_value < 0.12:
        return list(rng.choice(big_attachments, 2))
    elif 0.12 <= random_value < 0.14:
        return [*list(rng.choice(big_attachments, 2)), rng.choice(short_attachments)]
    elif 0.14 <= random_value < 0.15:
        return [*list(rng.choice(big_attachments, 2)), *list(rng.choice(short_attachments, 2))]
    elif 0.15 <= random_value < 0.20:
        return [rng.choice(big_attachments), rng.choice(short_attachments)]
    elif 0.20 <= random_value < 0.90:
        return [rng.choice(short_attachments)]
    elif 0.90 <= random_value < 0.95:
        return list(rng.choice(short_attachments, 2))
    elif 0.95 <= random_value < 0.97:
        return list(rng.choice(short_attachments, 3))
    elif 0.97 <= random_value < 0.99:
        return list(rng.choice(short_attachments, 4))
    else:
        return list(rng.choice(short_attachments, 5))


def generate_name(names_dataframe: list, rng: FastRandomGenerator) -> str:
    random_value = rng.random()
    if 0 <= random_value < 0.6:
        return f'{rng.choice(names_dataframe).lower()}@{rng.choice(names_dataframe).lower()}.com'
    elif 0.6 <= random_value < 0.95:
        return '+' + ''.join([str(rng.integers(0, 10)) for _ in range(10)])
    else:
        return rng.choice(names_dataframe) + ' ' + rng.choice(names_dataframe)


def generate_additional_notes(names_dataframe: list, rng: FastRandomGenerator):
    random_value = rng.random()
    if 0 <= random_value < 0.8:
        return rng.choice(names_dataframe) + ' ' + rng.choice(names_dataframe)
    else:
        return None


def generate_inline_message(names_dataframe: list, rng: FastRandomGenerator):
    random_value = rng.random()
    if 0 <= random_value < 0.8:
        return ' '.join(rng.choice(names_dataframe).lower() for _ in range(rng.integers(1, 40)))
    else:
        return None


def add_error_to_coords(lat: float, lon: float, rng: FastRandomGenerator,
                        min_error_meters=100, max_error_meters=20_000) -> tuple:
    bearing = rng.random() * 360
    distance = rng.random() * (max_error_meters - min_error_meters) + min_error_meters

    geodesic = geopy.distance.geodesic()
    lat_, lon_, _ = geodesic.destination((lat, lon), bearing, distance / 1000)
    return lat_, lon_


def get_list_of_coords(
    cities,
    top_100_cities_dataframe,
    top_100_cities_population,
    top_100_cities_population_cumulative_list,
    rng: FastRandomGenerator
):
    result = []
    for city in cities:
        random_value = rng.random()
        if 0 <= random_value < 0.9:
            additional_cities = 0
        elif 0.9 <= random_value < 0.95:
            additional_cities = 1
        elif 0.95 <= random_value < 0.98:
            additional_cities = 2
        else:
            additional_cities = 3

        filtered_cities = [city]
        for _ in range(additional_cities):
            filtered_cities.append(choose_city_by_random_value(
                rng.random(),
                top_100_cities_dataframe,
                top_100_cities_population,
                top_100_cities_population_cumulative_list,
            ))

        coords_list = []
        for filtered_city in filtered_cities:
            noised_coords = add_error_to_coords(filtered_city.coords.lat, filtered_city.coords.lon, rng)
            coords_list.append(noised_coords)

        result.append(coords_list)

    return result


def create_attachment(adps_attachments_path: PurePath, size_bytes: int, rng: FastRandomGenerator) -> FileAttachment:
    tmp_file_path = adps_attachments_path / 'tmp.bin'
    with open(tmp_file_path, 'wb') as file_:
        file_.write(rng.bytes(size_bytes))

    with open(tmp_file_path, 'rb') as file_:
        hashsum_result = calculate_hashsum(file_)

    target_filename = hashsum_result.hex_digest[:10] + '.bin'
    target_file_path = adps_attachments_path / target_filename
    os.rename(tmp_file_path, target_file_path)

    return FileAttachment(target_filename, hashsum_result.size_bytes, hashsum_result.hex_digest)


def generate_random_datetime(start, end, rng: FastRandomGenerator):
    """Generate a random datetime between `start` and `end`"""
    return start + timedelta(
        # Get a random amount of seconds between `start` and `end`
        seconds=int(rng.integers(0, int((end - start).total_seconds()))),
    )


def main():
    worldcities_path = PurePath(__file__).parents[1] / 'static_files/worldcities/worldcities.csv'
    first_names_path = PurePath(__file__).parents[1] / 'static_files/name_databases/all.txt'

    output_dir = sys.argv[1]

    target_country_code_iso2 = 'RU'
    target_country_part = 0.8
    rest_part = 1 - target_country_part

    mail_number = 50000
    attachment_number = 100000
    target_country_mail_number = round(target_country_part * mail_number)
    other_countries_mail_number = round(rest_part * mail_number)

    datetime_from = datetime(2022, 1, 1)
    datetime_to = datetime(2023, 1, 1)

    dataframe = pd.read_csv(worldcities_path)

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    adps_messages_path = PurePath(output_dir) / 'adps_messages'
    adps_attachments_path = PurePath(output_dir) / 'adps_attachments'

    os.mkdir(adps_messages_path)
    os.mkdir(adps_attachments_path)

    rng = FastRandomGenerator(np.random.default_rng(SEED))

    target_country_dataframe = dataframe.loc[dataframe['iso2'] == target_country_code_iso2]
    target_country_population = target_country_dataframe['population'].sum()
    target_country_cumulative_population_list = get_cumulative_list(target_country_dataframe)

    other_countries_dataframe = dataframe.loc[dataframe['iso2'] != target_country_code_iso2]
    other_countries_population = other_countries_dataframe['population'].sum()
    other_countries_cumulative_population_list = get_cumulative_list(other_countries_dataframe)

    print('Filtering target country cities...')
    target_country_cities = [
        choose_city_by_random_value(rng.random(), target_country_dataframe, target_country_population,
                                    target_country_cumulative_population_list)
        for _ in range(target_country_mail_number)
    ]

    print('Filtering other countries cities...')
    other_countries_cities = [
        choose_city_by_random_value(rng.random(), other_countries_dataframe, other_countries_population,
                                    other_countries_cumulative_population_list)
        for _ in range(other_countries_mail_number)
    ]

    print('Filtering top 100 cities...')
    top_100_cities_dataframe = dataframe.sort_values(by=['population'], ascending=False).head(100)
    top_100_cities_population = top_100_cities_dataframe['population'].sum()
    top_100_cities_cumulative_population_list = get_cumulative_list(top_100_cities_dataframe)

    big_files_sizes = [1024 ** 3, *([512 * 1024 ** 2] * 2), *([256 * 1024 ** 2] * 4), *([128 * 1024 ** 2] * 8)]
    short_files_sizes = list(np.diff([0, *get_file_sizes_bytes(attachment_number - len(big_files_sizes),
                                                               1 * 1024 * 1024 * 1024,
                                                               rng=rng)]))

    print('Reading names database...')
    names_df = pd.read_csv(first_names_path, header=None)
    all_names = list(names_df[0])

    print('Creating big attachments...')
    big_attachments = [create_attachment(adps_attachments_path, file_size_bytes, rng)
                       for file_size_bytes in big_files_sizes]

    print('Creating small attachments...')
    small_attachments = [create_attachment(adps_attachments_path, file_size_bytes, rng)
                         for file_size_bytes in short_files_sizes]

    print('Generating names...')
    list_of_names = [generate_name(all_names, rng) for _ in range(mail_number)]

    print('Generating additional notes...')
    list_of_additional_notes = [generate_additional_notes(all_names, rng) for _ in range(mail_number)]

    print('Generating inline messages...')
    list_of_inline_messages = [generate_inline_message(all_names, rng) for _ in range(mail_number)]

    print('Generating dates...')
    list_of_date_created = [generate_random_datetime(datetime_from, datetime_to, rng) for _ in range(mail_number)]

    print('Generating attachments sets...')
    list_of_attachments = [choose_attachments_for_mail(big_attachments, small_attachments, rng)
                           for _ in range(mail_number)]

    print('Generating coordinates...')
    list_of_coords = get_list_of_coords([*target_country_cities, *other_countries_cities],
                                        top_100_cities_dataframe,
                                        top_100_cities_population,
                                        top_100_cities_cumulative_population_list,
                                        rng)

    five_percent_indexes = {i * mail_number // 20 for i in range(1, 20)}

    progress = 0.00
    for idx, (created_date, coords_list, name, additional_notes, inline_message, attachment_infos) in enumerate(zip(
            list_of_date_created,
            list_of_coords,
            list_of_names,
            list_of_additional_notes,
            list_of_inline_messages,
            list_of_attachments
    )):
        if idx in five_percent_indexes:
            progress += 0.05
            print(f'Generating mail json files...{int(progress * 100)}%...')

        mail = Mail(
            date_created=created_date,
            recipient_coords=[CoordsData(*one_coords) for one_coords in coords_list],
            name=name,
            additional_notes=additional_notes,
            inline_message=inline_message,
            attachments=attachment_infos
        )
        mail_serialized = Mail.Schema().dump(mail)
        mail_json_bytes = json.dumps(mail_serialized, indent=4, sort_keys=True).encode()
        hashsum = calculate_hashsum(BytesIO(mail_json_bytes))

        mail_path = adps_messages_path / (hashsum.hex_digest[:10] + '.json')
        with open(mail_path, 'wb') as output_json_file:
            output_json_file.write(mail_json_bytes)


if __name__ == '__main__':
    main()
