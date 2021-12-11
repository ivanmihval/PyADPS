from datetime import datetime
from typing import Optional, List

from pyadps.mail import Mail, CoordsData, FileAttachment

from dataclasses import dataclass


@dataclass
class TestMailAndAttachment:
    mail: Mail
    mail_content: bytes
    attachment_content: bytes


@dataclass
class TestAttachmentData:
    content: bytes
    name: str


def fabricate_mail(
    date_created: Optional[datetime] = None,
    recipient_coords: Optional[List[CoordsData]] = None,
    name: str = 'john_smith@mydomain.com',
    additional_notes: Optional[str] = None,
    inline_message: Optional[str] = None,
    attachments: Optional[List[FileAttachment]] = None
) -> Mail:
    date_created = date_created or datetime(2020, 5, 5)
    recipient_coords = recipient_coords or [CoordsData(53.3595118, -6.3086148), CoordsData(-23.5311317, -46.9026668)]
    return Mail(
        date_created=date_created,
        recipient_coords=recipient_coords,
        name=name,
        additional_notes=additional_notes,
        inline_message=inline_message,
        attachments=attachments or []
    )
