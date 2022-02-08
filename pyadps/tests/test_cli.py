import json
import os
from datetime import datetime
from os import listdir

from click.testing import CliRunner
from freezegun import freeze_time

from pyadps.cli import init, create, clear
from pyadps.mail import Mail, CoordsData
from pyadps.storage import Storage


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
