import json
import os
from datetime import datetime
from os import listdir
from unittest.mock import Mock

import click
import pytest
from click.testing import CliRunner
from freezegun import freeze_time

from pyadps.cli import (init, create, clear, search, get_default_damping_distance_filter, build_filter, OutputPrinter,
                        delete)
from pyadps.mail import Mail, CoordsData, MailFilter, DatetimeCreatedRangeFilterData, LocationFilterData, \
    NameFilterData, AdditionalNotesFilterData, InlineMessageFilterData, AttachmentFilterData, DampingDistanceFilterData
from pyadps.storage import Storage

MOSCOW_COORDS = CoordsData(55.75222, 37.61556)
SOMEWHERE_ON_ATLANTIC_OCEAN = CoordsData(1.4487406, -2.6771144)


class TestRepoInit:
    def test_ok(self, tmp_path):
        result = CliRunner().invoke(init, [str(tmp_path)])  # type: ignore
        assert result.exit_code == 0
        assert set(listdir(tmp_path)) == {'adps_messages', 'adps_attachments'}

    def test_failed(self, tmp_path):
        result = CliRunner().invoke(init, [str(tmp_path)+'not_exists'])  # type: ignore
        assert result.exit_code == 2
        assert set(listdir(tmp_path)) == set()


class TestMailCreate:
    @freeze_time("2018-03-17T12:06:54")
    def test_ok(self, tmp_path):
        os.mkdir(tmp_path / 'adps_messages')
        os.mkdir(tmp_path / 'adps_attachments')

        test_file_content_1 = b''
        test_file_content_2 = b'456123'

        with open(tmp_path / 'empty_file.12', 'wb') as stream_1:
            stream_1.write(test_file_content_1)

        with open(tmp_path / 'test_file.txt', 'wb') as stream_2:
            stream_2.write(test_file_content_2)

        input_rows = [
            '12.345',  # First lat
            '44.890',  # First lon
            'y',  # Add more coordinates
            '-66.11',  # Second lat
            '178.43',  # Second lon
            'n',  # Stop adding more coordinates
            'name@mail.domain',  # Identity name
            'Bob Adam',  # Additional notes
            'Return my book please!',  # Inline message
            'y',  # Add attachment
            str(tmp_path / 'empty_file.12'),  # Path to the first attachment,
            'y',  # Add more attachments
            str(tmp_path / 'test_file.txt'),  # Path to the first attachment,
            'n',  # Do not add more attachments
        ]

        result = CliRunner().invoke(create, [str(tmp_path)], input='\n'.join(input_rows))  # type: ignore
        assert result.exit_code == 0

        assert os.listdir(tmp_path / 'adps_messages') == ['ee17177185.json']
        assert os.listdir(tmp_path / 'adps_attachments') == ['ca3d1dde02.bin', 'cf83e1357e.bin']

        with open(tmp_path / 'adps_messages' / 'ee17177185.json') as msg_stream:
            msg = json.load(msg_stream)

        assert msg == {
            'additional_notes': 'Bob Adam',
            'attachments': [
                {
                    'filename': 'empty_file.12',
                    'hashsum_alg': 'sha512',
                    'hashsum_hex': 'cf83e1357eefb8bdf1542850d66d8007d620e4050b5715dc83f4a921d36ce9ce'
                                   '47d0d13c5d85f2b0ff8318d2877eec2f63b931bd47417a81a538327af927da3e',
                    'size_bytes': 0
                },
                {
                    'filename': 'test_file.txt',
                    'hashsum_alg': 'sha512',
                    'hashsum_hex': 'ca3d1dde02c4b15d2e95521e259c5e08aaea8feaa722ba14014605249efe3f24'
                                   '8db3d98aa7c4accbe887e1b40573d7eba71017c5df029c16c8d6f06b0ffda310',
                    'size_bytes': 6
                }
            ],
            'date_created': '2018-03-17T12:06:54',
            'inline_message': 'Return my book please!',
            'min_version': '1.0',
            'name': 'name@mail.domain',
            'recipient_coords': [{'lat': 12.345, 'lon': 44.89}, {'lat': -66.11, 'lon': 178.43}],
            'version': '1.0'
        }


class TestClearRepository:
    @freeze_time("2018-03-17T12:06:54")
    def test_ok(self, tmp_path):
        originals_path = tmp_path / 'originals'
        os.makedirs(originals_path)

        attachment_1_content = b'12345'
        attachment_2_content = b'12345677899'
        attachment_3_content = b'123123123123'

        with open(originals_path / 'test.txt', 'wb') as file_:
            file_.write(attachment_1_content)

        with open(originals_path / 'document', 'wb') as file_:
            file_.write(attachment_2_content)

        with open(originals_path / 'document.txt', 'wb') as file_:
            file_.write(attachment_1_content)

        with open(originals_path / 'document.bin', 'wb') as file_:
            file_.write(attachment_3_content)

        mail_1, attachment_infos_1 = Mail.from_attachment_streams(
            date_created=datetime(2018, 1, 1),
            recipient_coords=[CoordsData(55.0, 37.0)],
            name='Donald Smith',
            additional_notes=None,
            inline_message='Please see 2 attachments',
            files=[
                open(originals_path / 'test.txt', 'rb'),
                open(originals_path / 'document', 'rb'),
                open(originals_path / 'document.txt', 'rb')
            ]
        )

        mail_2, attachment_infos_2 = Mail.from_attachment_streams(
            date_created=datetime(2018, 3, 4),
            recipient_coords=[CoordsData(54.0, 36.0)],
            name='abcde@abcde.com',
            additional_notes=None,
            inline_message='The document is in attachment',
            files=[open(originals_path / 'document.txt', 'rb'), open(originals_path / 'document.bin', 'rb')]
        )

        source_dir = tmp_path / 'source'
        os.makedirs(source_dir)
        os.makedirs(tmp_path / 'source' / 'adps_messages')
        os.makedirs(tmp_path / 'source' / 'adps_attachments')

        storage = Storage(str(source_dir))

        storage.save_mail(mail_1, attachment_infos_1, str(source_dir))
        storage.save_mail(mail_2, attachment_infos_2, str(source_dir))

        result = CliRunner().invoke(clear, [str(source_dir)], input='y')  # type: ignore
        assert result.exit_code == 0
        assert 'Message files to delete' in result.output
        assert '647ebe7b8d.json' in result.output
        assert 'Attachment files to delete' in result.output
        assert 'e711a66e46.bin' in result.output
        assert 'Do you want to delete these files?'


class TestGetDefaultDampingDistanceFilter:
    def test_moscow(self):
        damping_distance_filter = get_default_damping_distance_filter(MOSCOW_COORDS.lat, MOSCOW_COORDS.lon)
        assert damping_distance_filter.base_distance_meters == 1712500.0
        assert damping_distance_filter.location == CoordsData(55.7558, 37.6178)

    def test_fail(self):
        with pytest.raises(click.Abort):
            get_default_damping_distance_filter(SOMEWHERE_ON_ATLANTIC_OCEAN.lat, SOMEWHERE_ON_ATLANTIC_OCEAN.lon)


class TestBuildFilter:
    def test_all(self):
        mail_filter = build_filter(
            datetime_from=datetime(2016, 1, 2),
            datetime_to=datetime(2021, 4, 5),
            latitude=5.67,
            longitude=11.23,
            radius_meters=12345.0,
            name='Alex',
            additional_notes='Deliver to Lincoln Street 62/14 pls',
            inline_message='Hi, how are you?',
            attachment_hashsum='abcde1231455',
            damping_distance_longitude=22.22,
            damping_distance_latitude=33.33,
            damping_distance_base_distance_meters=123000.0,
        )

        assert mail_filter == MailFilter(
            datetime_created_range_filter=DatetimeCreatedRangeFilterData(
                date_from=datetime(2016, 1, 2, 0, 0),
                date_to=datetime(2021, 4, 5, 0, 0)
            ),
            location_filter=LocationFilterData(location=CoordsData(lat=5.67, lon=11.23), radius_meters=12345.0),
            name_filter=NameFilterData(name='Alex'),
            additional_notes_filter=AdditionalNotesFilterData(additional_notes='Deliver to Lincoln Street 62/14 pls'),
            inline_message_filter=InlineMessageFilterData(inline_message='Hi, how are you?'),
            attachment_filter=AttachmentFilterData(hashsum='abcde1231455'),
            damping_distance_filter=DampingDistanceFilterData(
                location=CoordsData(lat=33.33, lon=22.22),
                base_distance_meters=123000.0,
                threshold_probability=0.05
            ),
        )

    def test_none(self):
        mail_filter = build_filter(
            datetime_from=None,
            datetime_to=None,
            latitude=None,
            longitude=None,
            radius_meters=None,
            name=None,
            additional_notes=None,
            inline_message=None,
            attachment_hashsum=None,
            damping_distance_longitude=None,
            damping_distance_latitude=None,
            damping_distance_base_distance_meters=None,
        )

        assert mail_filter == MailFilter(
            datetime_created_range_filter=None,
            location_filter=None,
            name_filter=None,
            additional_notes_filter=None,
            inline_message_filter=None,
            attachment_filter=None,
            damping_distance_filter=None
        )

    @pytest.mark.parametrize('lat, lon, radius_meters', [[None, 1.23, 3.45], [1.23, None, 7.68], [1.23, 3.45, None]])
    def test_conflict_lat_lon_radius(self, lat: float, lon: float, radius_meters: float):
        with pytest.raises(click.BadOptionUsage):
            build_filter(
                datetime_from=None,
                datetime_to=None,
                latitude=lat,
                longitude=lon,
                radius_meters=None,
                name=None,
                additional_notes=None,
                inline_message=None,
                attachment_hashsum=None,
                damping_distance_longitude=None,
                damping_distance_latitude=None,
                damping_distance_base_distance_meters=None,
            )

    @pytest.mark.parametrize(
        'lat, lon, base_distance_meters',
        [[None, 1.23, 3.45], [1.23, None, 7.68], [None, None, 123.00]]
    )
    def test_conflict_damping_distance_params(self, lat: float, lon: float, base_distance_meters: float):
        with pytest.raises(click.BadOptionUsage):
            build_filter(
                datetime_from=None,
                datetime_to=None,
                latitude=None,
                longitude=None,
                radius_meters=None,
                name=None,
                additional_notes=None,
                inline_message=None,
                attachment_hashsum=None,
                damping_distance_longitude=lon,
                damping_distance_latitude=lat,
                damping_distance_base_distance_meters=base_distance_meters,
            )

    def test_default_damping_distance(self):
        mail_filter = build_filter(
            datetime_from=None,
            datetime_to=None,
            latitude=None,
            longitude=None,
            radius_meters=None,
            name=None,
            additional_notes=None,
            inline_message=None,
            attachment_hashsum=None,
            damping_distance_longitude=MOSCOW_COORDS.lon,
            damping_distance_latitude=MOSCOW_COORDS.lat,
            damping_distance_base_distance_meters=None,
        )
        assert mail_filter == MailFilter(
            datetime_created_range_filter=None,
            location_filter=None,
            name_filter=None,
            additional_notes_filter=None,
            inline_message_filter=None,
            attachment_filter=None,
            damping_distance_filter=DampingDistanceFilterData(
                location=CoordsData(55.7558, 37.6178),
                base_distance_meters=1712500.0,
                threshold_probability=0.05
            ),
        )


class TestOutputPrinter:
    @pytest.mark.parametrize('output_format, expected_output', [
        ['JSON', ('{"additional_notes": null, "attachments": [], "date_created": "2021-02-03T00:00:00", '
                  '"inline_message": null, "mail_hashsum_hex": "12345", "mail_path": "/1234/5678", '
                  '"min_version": "1.0", "name": "Donald", "recipient_coords": [{"lat": 55.75222, "lon": 37.61556}], '
                  '"version": "1.0"}')],
        ['HASHSUMS', '12345'],
        ['PATHS', '/1234/5678'],
    ])
    def test_ok(self, output_format, expected_output):
        mail = Mail(
            date_created=datetime(2021, 2, 3),
            recipient_coords=[MOSCOW_COORDS],
            name='Donald',
            additional_notes=None,
            inline_message=None,
            attachments=[]
        )
        printer = OutputPrinter(output_format=output_format)
        printer._print_func = Mock()
        printer.print(mail, '12345', '/1234/5678')

        printer._print_func.assert_called_once()
        assert printer._print_func.call_args.args[0] == expected_output


class TestSearch:
    def test_repo_does_not_exist(self, tmp_path):
        result = CliRunner().invoke(search, [str(tmp_path)+'not_exists'])  # type: ignore
        assert result.exit_code == 2

    @pytest.mark.parametrize('filter_args', [
        ['--datetime-from=2010-01-01', '--latitude=54.5', '--longitude=36.5', '--radius-meters=1000000'],
        ['--datetime-from=2018-01-01', '--datetime-to=2018-05-01'],
        ['--datetime-from=2010-01-01', '--name=donald@smith.com'],
        ['--datetime-from=2010-01-01', '--additional-notes=vavilova'],
        ['--datetime-from=2010-01-01', '--inline-message=ATTACHMENT'],
        ['--datetime-from=2010-01-01', '--attachment-hashsum=3627909a29c31381a'],
    ])
    @freeze_time("2018-03-17T12:06:54")
    def test_ok(self, tmp_path, filter_args: list):
        originals_path = tmp_path / 'originals'
        os.makedirs(originals_path)

        attachment_1_content = b'12345'
        attachment_2_content = b'12345677899'
        attachment_3_content = b'123123123123'

        with open(originals_path / 'test.txt', 'wb') as file_:
            file_.write(attachment_1_content)

        with open(originals_path / 'document', 'wb') as file_:
            file_.write(attachment_2_content)

        with open(originals_path / 'document.txt', 'wb') as file_:
            file_.write(attachment_1_content)

        with open(originals_path / 'document.bin', 'wb') as file_:
            file_.write(attachment_3_content)

        mail_1, attachment_infos_1 = Mail.from_attachment_streams(
            date_created=datetime(2018, 1, 1),
            recipient_coords=[CoordsData(55.0, 37.0)],
            name='donald@smith.com',
            additional_notes='Moscow City, ul. Vavilova',
            inline_message='Please see 2 attachments',
            files=[
                open(originals_path / 'test.txt', 'rb'),
                open(originals_path / 'document', 'rb'),
                open(originals_path / 'document.txt', 'rb')
            ]
        )

        mail_2, attachment_infos_2 = Mail.from_attachment_streams(
            date_created=datetime(2018, 3, 4),
            recipient_coords=[CoordsData(54.0, 36.0)],
            name='donald@smith.com',
            additional_notes='ul. vavilova, 5',
            inline_message='The document is in attachment',
            files=[open(originals_path / 'document.txt', 'rb'), open(originals_path / 'document.bin', 'rb')]
        )

        source_dir = tmp_path / 'source'
        os.makedirs(source_dir)
        os.makedirs(tmp_path / 'source' / 'adps_messages')
        os.makedirs(tmp_path / 'source' / 'adps_attachments')

        storage = Storage(str(source_dir))

        storage.save_mail(mail_1, attachment_infos_1, str(source_dir))
        storage.save_mail(mail_2, attachment_infos_2, str(source_dir))

        result = CliRunner().invoke(search, [str(source_dir), *filter_args, '--output-format=paths'])  # type: ignore
        assert result.exit_code == 0
        assert result.output == (
            f'{tmp_path}/source/adps_messages/e375f79f4e.json\n'
            f'{tmp_path}/source/adps_messages/1f478f4d9d.json\n'
        )


class TestDelete:
    def test_repo_does_not_exist(self, tmp_path):
        result = CliRunner().invoke(search, [str(tmp_path)+'not_exists'])  # type: ignore
        assert result.exit_code == 2

    @pytest.mark.parametrize('option', ['--hashsums', '--msg-path'])
    def test_ok(self, tmp_path, option):
        originals_path = tmp_path / 'originals'
        os.makedirs(originals_path)

        attachment_1_content = b'12345'
        attachment_2_content = b'12345677899'
        attachment_3_content = b'123123123123'

        with open(originals_path / 'test.txt', 'wb') as file_:
            file_.write(attachment_1_content)

        with open(originals_path / 'document', 'wb') as file_:
            file_.write(attachment_2_content)

        with open(originals_path / 'document.txt', 'wb') as file_:
            file_.write(attachment_1_content)

        with open(originals_path / 'document.bin', 'wb') as file_:
            file_.write(attachment_3_content)

        mail_1, attachment_infos_1 = Mail.from_attachment_streams(
            date_created=datetime(2018, 1, 1),
            recipient_coords=[CoordsData(55.0, 37.0)],
            name='Donald Smith',
            additional_notes=None,
            inline_message='Please see 2 attachments',
            files=[
                open(originals_path / 'test.txt', 'rb'),
                open(originals_path / 'document', 'rb'),
                open(originals_path / 'document.txt', 'rb')
            ]
        )

        mail_2, attachment_infos_2 = Mail.from_attachment_streams(
            date_created=datetime(2018, 3, 4),
            recipient_coords=[CoordsData(54.0, 36.0)],
            name='abcde@abcde.com',
            additional_notes=None,
            inline_message='The document is in attachment',
            files=[open(originals_path / 'document.txt', 'rb'), open(originals_path / 'document.bin', 'rb')]
        )

        source_dir = tmp_path / 'source'
        os.makedirs(source_dir)
        os.makedirs(tmp_path / 'source' / 'adps_messages')
        os.makedirs(tmp_path / 'source' / 'adps_attachments')

        storage = Storage(str(source_dir))

        storage.save_mail(mail_1, attachment_infos_1, str(source_dir))
        storage.save_mail(mail_2, attachment_infos_2, str(source_dir))

        cmd_option = (f'{option}={tmp_path / "source" / "adps_messages" / "647ebe7b8d.json"}'
                      if option == '--msg-path'
                      else f'{option}=647ebe7b8d,2492374abcde')

        result = CliRunner().invoke(delete, [str(source_dir), cmd_option], input='y')  # type: ignore
        assert result.exit_code == 0
        assert 'Message files to delete' in result.output
        assert '647ebe7b8d.json' in result.output
        assert 'Attachment files to delete' in result.output
        assert 'e711a66e46.bin' in result.output
        assert 'Do you want to delete these files?'
