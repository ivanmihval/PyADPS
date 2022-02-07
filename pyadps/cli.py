import os
import os.path
from datetime import datetime
from typing import List

import click

from pyadps.helpers import calculate_hashsum
from pyadps.mail import CoordsData, FileAttachment, Mail, MailAttachmentInfo
from pyadps.storage import Storage


@click.group()
def cli():
    pass


@cli.command()
@click.argument('repo_folder', type=click.Path(exists=True, file_okay=False), default='.')
def init(repo_folder):
    os.mkdir(os.path.join(repo_folder, Storage.MESSAGES_FOLDER))
    os.mkdir(os.path.join(repo_folder, Storage.ATTACHMENTS_FOLDERS))


def is_valid_repo_folder(repo_folder: str) -> bool:
    try:
        directories = os.listdir(repo_folder)
    except (NotADirectoryError, FileNotFoundError):
        return False

    return Storage.MESSAGES_FOLDER in directories and Storage.ATTACHMENTS_FOLDERS in directories


@cli.command()
@click.argument('repo_folder', type=click.Path(exists=True, file_okay=False), default='.')
def create(repo_folder):
    click.echo('This is the interactive command for creating mail.')

    if not is_valid_repo_folder(repo_folder):
        click.echo(f'The folder {repo_folder!r} is not valid repository. Use command init for creating the repository')
        raise click.Abort()

    coordinates = []
    add_more_coordinates: bool = True
    while add_more_coordinates:
        latitude = click.prompt('Enter the latitude', type=click.FloatRange(min=-90.0, max=90.0))
        longitude = click.prompt('Enter the latitude', type=click.FloatRange(min=-180.0, max=180.0))
        coordinates.append(CoordsData(latitude, longitude))
        add_more_coordinates = click.confirm('Add more recipient coordinates?')

    name = click.prompt('Enter the identity value (name, email, etc)', type=str)

    additional_notes = click.prompt('Additional notes (usually this field is used less than the identity)', type=str)
    additional_notes = additional_notes or None

    inline_message = click.prompt('Inline message (use attachments for big files)', type=str)
    inline_message = inline_message or None

    size_by_path = {}
    add_attachment = click.confirm('Add attachment?')
    while add_attachment:
        attachment_path = click.prompt('Enter the path', type=click.File())
        size_by_path[attachment_path.name] = os.stat(attachment_path.name).st_size
        add_attachment = click.confirm('Add more attachments?')

    file_attachments: List[FileAttachment] = []
    mail_attachment_infos: List[MailAttachmentInfo] = []
    hashsum_by_path = {}
    with click.progressbar(length=sum(size_by_path.values())) as bar:
        for attachment_path, size_bytes in size_by_path.items():
            click.echo(f'Calculating hashsum for {attachment_path!r}...')

            with open(attachment_path, 'rb') as file_stream:
                hashsum = calculate_hashsum(file_stream)  # type: ignore

            bar.update(size_bytes)
            hashsum_by_path[attachment_path] = hashsum

            file_attachments.append(FileAttachment(
                filename=os.path.basename(attachment_path),
                size_bytes=size_bytes,
                hashsum_hex=hashsum.hex_digest,
            ))
            mail_attachment_infos.append(MailAttachmentInfo(
                path=attachment_path,
                hashsum_hex=hashsum.hex_digest,
            ))

    message = Mail(
        date_created=datetime.now(),
        recipient_coords=coordinates,
        name=name,
        additional_notes=additional_notes,
        inline_message=inline_message,
        attachments=file_attachments
    )

    storage = Storage(repo_folder)
    storage.save_mail(mail=message, mail_attachment_infos=mail_attachment_infos, target_folder_path=repo_folder)


if __name__ == '__main__':
    cli()
