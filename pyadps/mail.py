from dataclasses import dataclass
from io import FileIO
from typing import Optional, List, ClassVar, Type, NamedTuple, Tuple, Union, BinaryIO
from datetime import datetime

import os.path

import geopy.distance
from marshmallow import Schema
from marshmallow_dataclass import add_schema

from pyadps.helpers import calculate_hashsum


class MailAttachmentInfo(NamedTuple):
    path: str
    hashsum_hex: str


@dataclass
class CoordsData:
    lat: float
    lon: float

    def to_tuple(self) -> tuple:
        return self.lat, self.lon


@dataclass
class FileAttachment:
    filename: str
    size_bytes: int
    hashsum_hex: str
    hashsum_alg: str = 'sha512'


@dataclass
class Mail:
    date_created: datetime
    recipient_coords: List[CoordsData]
    name: str  # may be any identity, eg phone number, passport name, email, ICQ, telegram, etc
    additional_notes: Optional[str]  # additional field for more accurate search
    inline_message: Optional[str]  # used for short messages
    attachments: List[FileAttachment]

    version: str = '1.0'
    min_version: str = '1.0'

    Schema: ClassVar[Type[Schema]] = None

    @classmethod
    def from_attachment_streams(
        cls,
        date_created: datetime,
        recipient_coords: List[CoordsData],
        name: str,
        additional_notes: Optional[str],
        inline_message: Optional[str],
        files: List[Union[FileIO, BinaryIO]]
    ) -> Tuple['Mail', List[MailAttachmentInfo]]:
        attachments: List[FileAttachment] = []
        attachment_infos: List[MailAttachmentInfo] = []
        for file_io in files:
            file_name = os.path.basename(file_io.name)
            hashsum = calculate_hashsum(file_io)
            attachments.append(FileAttachment(file_name, hashsum.size_bytes, hashsum.hex_digest))
            attachment_infos.append(MailAttachmentInfo(file_io.name, hashsum.hex_digest))

        return cls(
            date_created=date_created,
            recipient_coords=recipient_coords,
            name=name,
            additional_notes=additional_notes,
            inline_message=inline_message,
            attachments=attachments
        ), attachment_infos


add_schema(Mail)


@dataclass
class DatetimeCreatedRangeFilterData:
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None


@dataclass
class LocationFilterData:
    location: CoordsData
    radius_meters: float


@dataclass
class NameFilterData:
    name: str


@dataclass
class AdditionalNotesFilterData:
    additional_notes: str


@dataclass
class InlineMessageFilterData:
    inline_message: str


@dataclass
class AttachmentFilterData:
    hashsum: str


@dataclass
class MailFilter:
    datetime_created_range_filter: Optional[DatetimeCreatedRangeFilterData] = None
    location_filter: Optional[LocationFilterData] = None
    name_filter: Optional[NameFilterData] = None
    additional_notes_filter: Optional[AdditionalNotesFilterData] = None
    inline_message_filter: Optional[InlineMessageFilterData] = None
    attachment_filter: Optional[AttachmentFilterData] = None

    def filter_func(self, mail: Mail) -> bool:
        if self.datetime_created_range_filter is not None:
            if (self.datetime_created_range_filter.date_from is not None
                    and mail.date_created < self.datetime_created_range_filter.date_from):
                return False

            if (self.datetime_created_range_filter.date_to is not None
                    and mail.date_created > self.datetime_created_range_filter.date_to):
                return False

        if self.location_filter is not None:
            is_inside = False
            for coord in mail.recipient_coords:
                distance = geopy.distance.distance(coord.to_tuple(),
                                                   self.location_filter.location.to_tuple()).m

                if distance < self.location_filter.radius_meters:
                    is_inside = True

            if not is_inside:
                return False

        if self.name_filter is not None and self.name_filter.name != mail.name:
            return False

        if self.additional_notes_filter is not None:
            if mail.additional_notes is None:
                return False

            if self.additional_notes_filter.additional_notes.lower() not in mail.additional_notes.lower():
                return False

        if self.inline_message_filter is not None:
            if mail.inline_message is None:
                return False

            if self.inline_message_filter.inline_message.lower() not in mail.inline_message.lower():
                return False

        if self.attachment_filter is not None:
            if self.attachment_filter.hashsum not in {attachment.hashsum_hex for attachment in mail.attachments}:
                return False

        return True
