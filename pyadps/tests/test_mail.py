from datetime import datetime
from typing import Optional
from unittest.mock import patch

import pytest

from pyadps.mail import (CoordsData, FileAttachment, MailFilter, DatetimeCreatedRangeFilterData,
                         LocationFilterData, NameFilterData, AdditionalNotesFilterData, InlineMessageFilterData,
                         AttachmentFilterData, DampingDistanceFilterData)
from pyadps.tests.helpers import fabricate_mail

MOSCOW_COORDS = CoordsData(55.75222, 37.61556)
YEKATERINBURG_COORDS = CoordsData(56.8519, 60.6122)


class TestMailFilter:
    @pytest.mark.parametrize('date_from, date_to, is_filtered_expected', [
        [datetime(2019, 4, 5), datetime(2020, 12, 31), False],
        [datetime(2019, 4, 5), None, True],
        [datetime(2021, 4, 5), datetime(2022, 12, 31), False],
        [datetime(2019, 4, 5), datetime(2022, 12, 31), True],
        [None, datetime(2022, 12, 31), True],
    ])
    def test_date_range(self, date_from: Optional[datetime], date_to: Optional[datetime], is_filtered_expected: bool):
        date_created = datetime(2021, 1, 1)
        mail_filter = MailFilter(datetime_created_range_filter=DatetimeCreatedRangeFilterData(date_from, date_to))
        mail = fabricate_mail(date_created=date_created)
        is_filtered_actual = mail_filter.filter_func(mail)
        assert is_filtered_actual is is_filtered_expected

    @pytest.mark.parametrize('location, radius_meters, is_filtered_expected', [
        [CoordsData(53.359, -6.308), 1000.0, True],
        [CoordsData(53.359, -6.308), 1.0, False],
        [CoordsData(-23.531, -46.902), 2000.0, True]
    ])
    def test_distance(self, location: CoordsData, radius_meters: float, is_filtered_expected: bool):
        mail_filter = MailFilter(location_filter=LocationFilterData(location, radius_meters))
        mail = fabricate_mail()
        is_filtered_actual = mail_filter.filter_func(mail)
        assert is_filtered_actual is is_filtered_expected

    def test_damping_distance(self):
        mail_filter = MailFilter(damping_distance_filter=DampingDistanceFilterData(MOSCOW_COORDS, 2000*1000))
        mail = fabricate_mail(recipient_coords=[YEKATERINBURG_COORDS])
        with patch('pyadps.mail.DampingDistanceFilterData._is_matched_with_probability', return_value=True) as rnd_mock:
            is_filtered_actual = mail_filter.filter_func(mail)

        rnd_mock.assert_called_once()
        called_probability: float = rnd_mock.call_args_list[0][0][0]
        assert abs(called_probability - 0.6108781088799166) < 0.00001

        assert is_filtered_actual is True

    @pytest.mark.parametrize('name, is_filtered_expected', [
        ['john_smith@mydomain.com', True],
        ['john_smIth@mydomain.com', False],
        ['john_smith@mydomain.com ', False],
    ])
    def test_name(self, name: str, is_filtered_expected: bool):
        mail_filter = MailFilter(name_filter=NameFilterData(name))
        mail = fabricate_mail()
        is_filtered_actual = mail_filter.filter_func(mail)
        assert is_filtered_actual is is_filtered_expected

    @pytest.mark.parametrize('additional_notes, is_filtered_expected', [
        ['for john smith', True],
        ['not for john smith', False],
    ])
    def test_additional_notes(self, additional_notes: str, is_filtered_expected: str):
        mail_filter = MailFilter(additional_notes_filter=AdditionalNotesFilterData(additional_notes))
        mail = fabricate_mail(additional_notes='This message is for John Smith')
        is_filtered_actual = mail_filter.filter_func(mail)
        assert is_filtered_actual is is_filtered_expected

    @pytest.mark.parametrize('inline_message, is_filtered_expected', [
        ['for john smith', True],
        ['not for john smith', False],
    ])
    def test_inline_message(self, inline_message: str, is_filtered_expected: str):
        mail_filter = MailFilter(inline_message_filter=InlineMessageFilterData(inline_message))
        mail = fabricate_mail(inline_message='This message is for John Smith')
        is_filtered_actual = mail_filter.filter_func(mail)
        assert is_filtered_actual is is_filtered_expected

    @pytest.mark.parametrize('hashsum_hex, is_filtered_expected', [
        ['0123456789abcdef', True],
        ['12345', False],
    ])
    def test_attachment(self, hashsum_hex, is_filtered_expected):
        mail_filter = MailFilter(attachment_filter=AttachmentFilterData(hashsum_hex))
        mail = fabricate_mail(attachments=[FileAttachment('123.mp4', 12345678, '0123456789abcdef')])
        is_filtered_actual = mail_filter.filter_func(mail)
        assert is_filtered_actual is is_filtered_expected
