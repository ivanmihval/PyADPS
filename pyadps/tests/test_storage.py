import os

from pyadps.mail import Mail, CoordsData, MailFilter, DatetimeCreatedRangeFilterData
from datetime import datetime

from hashlib import sha512

from pyadps.storage import Storage


class TestCopyMails:
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
            date_created=datetime(2020, 1, 1),
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
            date_created=datetime(2019, 3, 4),
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

        target_dir = tmp_path / 'target'

        storage = Storage(str(source_dir))

        storage.save_mail(mail_1, attachment_infos_1, str(source_dir))
        assert list(os.listdir(source_dir / 'adps_messages')) == ['0d948fdc77.json']
        mail_1_sha512 = sha512()
        mail_1_sha512.update(open(source_dir / 'adps_messages' / '0d948fdc77.json', 'rb').read())
        assert mail_1_sha512.hexdigest().startswith('0d948fdc77')

        storage.save_mail(mail_2, attachment_infos_2, str(source_dir))

        storage.copy_mails([source_dir / 'adps_messages' / 'bee12b5bd6.json'], target_dir)

        assert list(os.listdir(target_dir / 'adps_messages')) == ['bee12b5bd6.json']
        assert list(os.listdir(target_dir / 'adps_attachments')) == ['158911a346.bin', '3627909a29.bin']


class TestFilterMails:
    def test_ok(self, tmp_path):
        mail_1, _ = Mail.from_attachment_streams(
            date_created=datetime(2020, 1, 1),
            recipient_coords=[CoordsData(55.0, 37.0)],
            name='Donald Smith',
            additional_notes=None,
            inline_message='',
            files=[]
        )

        mail_2, _ = Mail.from_attachment_streams(
            date_created=datetime(2019, 3, 4),
            recipient_coords=[CoordsData(54.0, 36.0)],
            name='abcde@abcde.com',
            additional_notes=None,
            inline_message='The document is in attachment',
            files=[]
        )

        storage = Storage(str(tmp_path))
        storage.save_mail(mail_1, [], str(tmp_path))
        storage.save_mail(mail_2, [], str(tmp_path))

        filtered_mails = list(
            storage.filter_mails(
                MailFilter(
                    datetime_created_range_filter=DatetimeCreatedRangeFilterData(date_from=datetime(2019, 12, 1))
                )
            )
        )

        assert filtered_mails == [mail_1]
