# -*- coding: utf-8 -*-
import json
import os
import os.path
from datetime import datetime, timedelta
from pathlib import PurePath
from shutil import copyfile
from typing import List, Optional, Union

import click

from pyadps.geo_worker import search_most_populated_city_by_coords
from pyadps.helpers import calculate_hashsum
from pyadps.mail import (AdditionalNotesFilterData, AttachmentFilterData, CoordsData, DampingDistanceFilterData,
                         DatetimeCreatedRangeFilterData, FileAttachment, InlineMessageFilterData, LocationFilterData,
                         Mail, MailAttachmentInfo, MailFilter, NameFilterData)
from pyadps.storage import (CopyMailsCallbackData, CopyMailsStage, EstimationDeleteMailsCallbackData,
                            EstimationDeleteMailsStage, FilterMailCallbackData, Storage)


class OutputFormat:
    HASHSUMS = 'HASHSUMS'
    PATHS = 'PATHS'
    JSON = 'JSON'
    COUNT = 'COUNT'


@click.group()
def cli():
    pass


@cli.command('init', help='Init repository')
@click.argument('repo_folder', type=click.Path(exists=True, file_okay=False), default='.')
def init(repo_folder: str):
    os.mkdir(os.path.join(repo_folder, Storage.MESSAGES_FOLDER))
    os.mkdir(os.path.join(repo_folder, Storage.ATTACHMENTS_FOLDER))


def is_valid_repo_folder(repo_folder: str) -> bool:
    try:
        directories = os.listdir(repo_folder)
    except (NotADirectoryError, FileNotFoundError):
        return False

    return Storage.MESSAGES_FOLDER in directories and Storage.ATTACHMENTS_FOLDER in directories


@cli.command('create', help='Interactive command for creating a message')
@click.argument('repo_folder', type=click.Path(exists=True, file_okay=False), default='.')
def create(repo_folder: str):
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


class SearchCallback:
    def __init__(self):
        self.progressbar = None

    def __call__(self, filter_mail_callback_data: FilterMailCallbackData):
        if self.progressbar is None:
            self.progressbar = click.progressbar(
                length=filter_mail_callback_data.total_mails_number,
                label='Searching messages...'
            ).__enter__()

        self.progressbar.update(1)

        is_finished = filter_mail_callback_data.current_mail_idx + 1 == filter_mail_callback_data.total_mails_number
        if is_finished:
            self.progressbar.finish()
            self.progressbar.__exit__(None, None, None)


class CopyCallback:
    def __init__(self):
        self.progressbar = None
        self.stage = None

    def _finalize_progressbar(self):
        self.progressbar.finish()
        self.progressbar.__exit__(None, None, None)

    def _create_progressbar(self, *args, **kwargs):
        # finalizing the previous progressbar
        if self.progressbar is not None:
            self._finalize_progressbar()

        self.progressbar = click.progressbar(*args, **kwargs).__enter__()

    def __call__(self, copy_mails_callback_data: CopyMailsCallbackData):
        # Stages: None -> ESTIMATION -> COPYING
        if self.stage is None and copy_mails_callback_data.stage == CopyMailsStage.ESTIMATION:
            self.stage = copy_mails_callback_data.stage
            self._create_progressbar(length=copy_mails_callback_data.estimation_progress.total_mails_number,
                                     label='Estimation of files to copy...')

        if self.stage == CopyMailsStage.ESTIMATION and copy_mails_callback_data.stage == CopyMailsStage.COPYING:
            self.stage = copy_mails_callback_data.stage
            self._create_progressbar(length=copy_mails_callback_data.copying_progress.total_files_size_bytes,
                                     label='Copying files...')

        if self.stage == CopyMailsStage.ESTIMATION:
            self.progressbar.update(1)
        elif self.stage == CopyMailsStage.COPYING:
            self.progressbar.update(copy_mails_callback_data.copying_progress.current_file_bytes)

        if (copy_mails_callback_data.stage == CopyMailsStage.COPYING
                and (copy_mails_callback_data.copying_progress.total_files_size_bytes
                     == copy_mails_callback_data.copying_progress.copied_bytes)):
            self._finalize_progressbar()


class EstimationDeleteCallback(CopyCallback):
    def __call__(self, estimation_delete_callback: EstimationDeleteMailsCallbackData):
        # Stages: None -> SCANNING_TARGET_FILES -> SCANNING_ALL_FILES
        if self.stage is None and estimation_delete_callback.stage == EstimationDeleteMailsStage.SCANNING_TARGET_FILES:
            self.stage = estimation_delete_callback.stage
            self._create_progressbar(length=estimation_delete_callback.callback_data.total_mails_number,
                                     label='Searching files to delete...')

        if (self.stage == EstimationDeleteMailsStage.SCANNING_TARGET_FILES
                and estimation_delete_callback.stage == EstimationDeleteMailsStage.SCANNING_ALL_FILES):
            self.stage = estimation_delete_callback.stage
            self._create_progressbar(length=estimation_delete_callback.callback_data.total_mails_number,
                                     label='Searching other files with attachments to delete...')

        if self.progressbar:
            self.progressbar.update(1)

        if (estimation_delete_callback.stage == EstimationDeleteMailsStage.SCANNING_ALL_FILES
                and (estimation_delete_callback.callback_data.current_mail_idx
                     == estimation_delete_callback.callback_data.total_mails_number - 1)):
            self._finalize_progressbar()


def delete_messages_by_mail_paths(
    msg_paths: List[str],
    storage: Storage,
    confirm: bool,
    print_list: bool,
    show_progressbar: bool,
):
    callback = EstimationDeleteCallback() if show_progressbar else None
    attachment_paths_to_delete = storage.get_attachments_for_delete(msg_paths=msg_paths, callback=callback)

    if print_list:
        click.echo('Message files to delete:')
        click.echo('\n'.join(msg_paths))

        click.echo('Attachment files to delete:')
        click.echo('\n'.join(attachment_paths_to_delete))

    confirm_delete: bool = True
    if confirm:
        confirm_delete = click.confirm('Do you want to delete these files?')

    if not confirm_delete:
        raise click.ClickException('Operation is cancelled')

    for file_path in [*msg_paths, *attachment_paths_to_delete]:
        os.remove(file_path)

    rename_mapping = storage.get_correct_filenames_mapping_after_delete()
    for before_path, after_path in rename_mapping:
        os.rename(before_path, after_path)


@cli.command('clear', help='Deletes expired messages with attachments linked to them')
@click.argument('repo_folder', type=click.Path(exists=True, file_okay=False), default='.')
@click.option('--days', type=click.INT, default=30)
@click.option('--confirm/--no-confirm', type=click.BOOL, default=True)
@click.option('--print-list/--no-print-list', type=click.BOOL, default=True)
@click.option('--show-progressbar/--no-show-progressbar', type=click.BOOL, default=True)
def clear(repo_folder: str, days: int, confirm: bool, print_list: bool, show_progressbar: bool):
    if not is_valid_repo_folder(repo_folder):
        click.echo(f'The folder {repo_folder!r} is not valid repository. Use command init for creating the repository')
        raise click.Abort()

    storage = Storage(repo_folder)

    max_date = datetime.now() - timedelta(days=days)
    mail_filter_results = list(storage.filter_mails(MailFilter(
        datetime_created_range_filter=DatetimeCreatedRangeFilterData(date_to=max_date)
    )))
    msg_paths = [filter_result.mail_path for filter_result in mail_filter_results]
    delete_messages_by_mail_paths(
        msg_paths=msg_paths,
        storage=storage,
        confirm=confirm,
        print_list=print_list,
        show_progressbar=show_progressbar,
    )


def get_default_damping_distance_filter(
    damping_distance_latitude,
    damping_distance_longitude,
) -> DampingDistanceFilterData:
    worldcities_csv_path = str(PurePath(__file__).parents[0] / 'static_files/worldcities/worldcities.csv')
    try:
        most_populated_city = search_most_populated_city_by_coords(
            latitude=damping_distance_latitude,
            longitude=damping_distance_longitude,
            cities_csv_path=worldcities_csv_path,
        )
        if most_populated_city is None:
            raise click.ClickException('Could not find a city near by presented coordinates')
    except Exception as e:
        raise click.ClickException(f'Could not process worldcities.csv: {e!r}')

    coefficient: float = 10.0  # unit: people per meter
    base_distance_meters = most_populated_city.population / coefficient

    return DampingDistanceFilterData(
        location=CoordsData(most_populated_city.latitude, most_populated_city.longitude),
        base_distance_meters=base_distance_meters
    )


def build_filter(
    datetime_from: Optional[datetime],
    datetime_to: Optional[datetime],
    latitude: Optional[float],
    longitude: Optional[float],
    radius_meters: Optional[float],
    name: Optional[str],
    additional_notes: Optional[str],
    inline_message: Optional[str],
    attachment_hashsum: Optional[str],
    damping_distance_latitude: Optional[float],
    damping_distance_longitude: Optional[float],
    damping_distance_base_distance_meters: Optional[float],
) -> MailFilter:

    datetime_created_range_filter_data = None
    if datetime_from or datetime_to:
        datetime_created_range_filter_data = DatetimeCreatedRangeFilterData(datetime_from, datetime_to)

    if (latitude is None) is not (longitude is None):
        raise click.BadOptionUsage('latitude', 'both or none of (latitude, longitude) should be filled')

    if latitude is not None and radius_meters is None:
        raise click.BadOptionUsage('radius-meters', 'radius-meters should be filled if coordinates are specified')

    location_filter_data = None
    if latitude is not None:
        location_filter_data = LocationFilterData(CoordsData(latitude, longitude), radius_meters)

    name_filter_data = None
    if name is not None:
        name_filter_data = NameFilterData(name)

    additional_notes_filter_data = None
    if additional_notes is not None:
        additional_notes_filter_data = AdditionalNotesFilterData(additional_notes)

    inline_message_filter_data = None
    if inline_message is not None:
        inline_message_filter_data = InlineMessageFilterData(inline_message)

    attachment_filter_data = None
    if attachment_hashsum is not None:
        attachment_filter_data = AttachmentFilterData(attachment_hashsum)

    if (damping_distance_latitude is None) is not (damping_distance_longitude is None):
        raise click.BadOptionUsage(
            'damping-distance-latitude',
            'both or none of (damping-distance-latitude, damping-distance-longitude) should be filled'
        )

    if (damping_distance_latitude is None) and (damping_distance_base_distance_meters is not None):
        raise click.BadOptionUsage(
            'damping-distance-base-distance-meters',
            'damping-distance-base-distance-meters should be filled if coordinates are specified'
        )

    damping_distance_filter_data = None
    if damping_distance_latitude is not None:
        if damping_distance_base_distance_meters is None:
            damping_distance_filter_data = get_default_damping_distance_filter(
                damping_distance_latitude=damping_distance_latitude,
                damping_distance_longitude=damping_distance_longitude,
            )
        else:
            damping_distance_filter_data = DampingDistanceFilterData(
                location=CoordsData(damping_distance_latitude, damping_distance_longitude),
                base_distance_meters=damping_distance_base_distance_meters,
            )

    return MailFilter(
        datetime_created_range_filter=datetime_created_range_filter_data,
        location_filter=location_filter_data,
        name_filter=name_filter_data,
        additional_notes_filter=additional_notes_filter_data,
        inline_message_filter=inline_message_filter_data,
        attachment_filter=attachment_filter_data,
        damping_distance_filter=damping_distance_filter_data,
    )


class OutputPrinter:
    def __init__(self, output_format: str):
        self.output_format = output_format

    @staticmethod
    def _get_output_json(mail: Mail, mail_hashsum_hex: str, mail_path: str):
        mail_serialized = Mail.Schema().dump(mail)
        mail_serialized['mail_hashsum_hex'] = mail_hashsum_hex
        mail_serialized['mail_path'] = mail_path
        return json.dumps(mail_serialized, indent=None, sort_keys=True)

    @staticmethod
    def _print_func(s: Union[str, int]):
        click.echo(s)

    def print_item(self, mail: Mail, mail_hashsum_hex: str, mail_path: str):
        if self.output_format == OutputFormat.JSON:
            self._print_func(self._get_output_json(mail, mail_hashsum_hex, mail_path))
        elif self.output_format == OutputFormat.HASHSUMS:
            self._print_func(mail_hashsum_hex)
        elif self.output_format == OutputFormat.COUNT:
            pass
        else:
            self._print_func(mail_path)

    def print_count(self, count: int):
        if self.output_format == OutputFormat.COUNT:
            self._print_func(count)


@cli.command('search', help='Searches messages')
@click.argument('repo_folder', type=click.Path(exists=True, file_okay=False), default='.')
@click.option('--datetime-from', type=click.DateTime(), default=datetime.now() - timedelta(days=30))
@click.option('--datetime-to', type=click.DateTime(), default=None)
@click.option('--latitude', type=click.FloatRange(min=-90.0, max=90.0), default=None)
@click.option('--longitude', type=click.FloatRange(min=-180.0, max=180.0), default=None)
@click.option('--radius-meters', type=click.FLOAT, default=30 * 1000)
@click.option('--name', type=click.STRING, default=None)
@click.option('--additional-notes', type=click.STRING, default=None)
@click.option('--inline-message', type=click.STRING, default=None)
@click.option('--attachment-hashsum', type=click.STRING, default=None)
@click.option('--damping-distance-latitude', type=click.FloatRange(min=-90.0, max=90.0), default=None)
@click.option('--damping-distance-longitude', type=click.FloatRange(min=-180.0, max=180.0), default=None)
@click.option('--damping-distance-base-distance-meters', type=click.FLOAT, default=None)
@click.option('--output-format',
              type=click.Choice([OutputFormat.HASHSUMS, OutputFormat.JSON, OutputFormat.PATHS, OutputFormat.COUNT],
                                case_sensitive=False),
              default=OutputFormat.JSON)
@click.option('--show-progressbar/--no-show-progressbar', type=click.BOOL, default=True)
@click.option('--copy/--no-copy', 'copy_msg', type=click.BOOL, default=False,
              help='Copy filtered files to another repo')
@click.option('--delete/--no-delete', 'delete_msg', type=click.BOOL, default=False,
              help='Delete filtered files to another repo')
@click.option('--confirm-delete/--no-confirm-delete', type=click.BOOL, default=False,
              help='ask confirmation before delete')
@click.option('--print-list-to-delete/--no-print-list-to-delete', type=click.BOOL, default=False)
@click.option('--target-repo-folder', type=click.STRING, default=None)
def search(
    repo_folder: str,
    datetime_from: Optional[datetime],
    datetime_to: Optional[datetime],
    latitude: Optional[float],
    longitude: Optional[float],
    radius_meters: Optional[float],
    name: Optional[str],
    additional_notes: Optional[str],
    inline_message: Optional[str],
    attachment_hashsum: Optional[str],
    damping_distance_latitude: Optional[float],
    damping_distance_longitude: Optional[float],
    damping_distance_base_distance_meters: Optional[float],
    output_format: str,
    show_progressbar: bool,
    copy_msg: bool,
    delete_msg: bool,
    confirm_delete: bool,
    print_list_to_delete: bool,
    target_repo_folder: Optional[str],
):
    if not is_valid_repo_folder(repo_folder):
        raise click.UsageError(f'The folder {repo_folder!r} is not valid repository. '
                               f'Use command init for creating the repository')

    if copy_msg and (target_repo_folder is None):
        raise click.UsageError('You should specify the target_repo_folder in case you want to copy the messages')

    if target_repo_folder is not None and not is_valid_repo_folder(target_repo_folder):
        raise click.UsageError(f'The target folder {repo_folder!r} is not valid repository. '
                               'Use command init for creating the repository')

    storage = Storage(repo_folder)

    mail_filter = build_filter(
        datetime_from=datetime_from,
        datetime_to=datetime_to,
        latitude=latitude,
        longitude=longitude,
        radius_meters=radius_meters,
        name=name,
        additional_notes=additional_notes,
        inline_message=inline_message,
        attachment_hashsum=attachment_hashsum,
        damping_distance_latitude=damping_distance_latitude,
        damping_distance_longitude=damping_distance_longitude,
        damping_distance_base_distance_meters=damping_distance_base_distance_meters,
    )

    output_printer = OutputPrinter(output_format)

    search_callback = SearchCallback() if show_progressbar else None
    copy_callback = CopyCallback() if show_progressbar else None

    count = 0
    filtered_message_paths = []
    for search_result in storage.filter_mails(mail_filter, search_callback):
        output_printer.print_item(search_result.mail, search_result.mail_hashsum_hex, search_result.mail_path)
        count += 1

        if copy_msg or delete_msg:
            filtered_message_paths.append(search_result.mail_path)

    if copy_msg:
        storage.copy_mails(filtered_message_paths, target_repo_folder, copy_callback)  # type: ignore

    if delete_msg:
        delete_messages_by_mail_paths(
            msg_paths=filtered_message_paths,
            storage=storage,
            confirm=confirm_delete,
            print_list=print_list_to_delete,
            show_progressbar=show_progressbar
        )

    output_printer.print_count(count)


def get_msg_paths_by_user_input(
    hashsums: Optional[str],
    msg_path: Optional[str],
    storage: Storage
) -> List[str]:
    if hashsums is not None and msg_path is not None:
        raise click.BadOptionUsage('hashsums', 'Cannot specify both --hashsums and --msg-path options')

    if hashsums is None and msg_path is None:
        raise click.BadOptionUsage('hashsums', 'You should specify one of the following options: '
                                               '--hashsums, --msg-path')

    msg_paths = []
    if msg_path is not None:
        msg_paths.append(msg_path)
    elif hashsums is not None:
        hashsums_list = hashsums.split(',')
        for search_result in storage.filter_mails(mail_filter=None):
            for hashsum_part in hashsums_list:
                if search_result.mail_hashsum_hex.startswith(hashsum_part):
                    msg_paths.append(search_result.mail_path)
                    break

    return msg_paths


@cli.command('delete', help='Deletes messages by their hashsums or by path')
@click.argument('repo_folder', type=click.Path(exists=True, file_okay=False), default='.')
@click.option(
    '--hashsums',
    type=click.STRING,
    default=None,
    help='hashsums of messages divided by comma, for example, "e375f79f4e,1f478f4d9d". '
         'Warning: this option conflicts with the --path option'
)
@click.option('--msg-path', type=click.Path(exists=True, file_okay=True, dir_okay=False), default=None, required=False)
@click.option('--confirm/--no-confirm', type=click.BOOL, default=True, help='ask confirmation before delete')
@click.option('--print-list/--no-print-list', type=click.BOOL, default=True)
@click.option('--show-progressbar/--no-show-progressbar', type=click.BOOL, default=True)
def delete(
    repo_folder: str,
    hashsums: Optional[str],
    msg_path: Optional[str],
    confirm: bool,
    print_list: bool,
    show_progressbar: bool,
):
    if not is_valid_repo_folder(repo_folder):
        click.echo(f'The folder {repo_folder!r} is not valid repository. Use command init for creating the repository')
        raise click.Abort()

    storage = Storage(repo_folder)
    msg_paths = get_msg_paths_by_user_input(
        hashsums=hashsums,
        msg_path=msg_path,
        storage=storage
    )

    delete_messages_by_mail_paths(
        msg_paths=msg_paths,
        storage=storage,
        confirm=confirm,
        print_list=print_list,
        show_progressbar=show_progressbar,
    )


@cli.command('copy', help='Copy messages (with attachments) by their hashsums or by path to another repository')
@click.argument('source_repo_folder', type=click.Path(exists=True, file_okay=False), default='.')
@click.argument('target_repo_folder', type=click.Path(exists=True, file_okay=False), default='.')
@click.option(
    '--hashsums',
    type=click.STRING,
    default=None,
    help='hashsums of messages divided by comma, for example, "e375f79f4e,1f478f4d9d". '
         'Warning: this option conflicts with the --path option'
)
@click.option('--msg-path', type=click.Path(exists=True, file_okay=True, dir_okay=False), default=None, required=False)
@click.option('--show-progressbar/--no-show-progressbar', type=click.BOOL, default=True)
def copy(
    source_repo_folder: str,
    target_repo_folder: str,
    hashsums: Optional[str],
    msg_path: Optional[str],
    show_progressbar: bool,
):
    for repo_folder in [source_repo_folder, target_repo_folder]:
        if not is_valid_repo_folder(repo_folder):
            click.echo(f'The folder {repo_folder!r} is not valid repository. '
                       f'Use command init for creating the repository')
            raise click.Abort()

    source_storage = Storage(source_repo_folder)
    msg_paths = get_msg_paths_by_user_input(
        hashsums=hashsums,
        msg_path=msg_path,
        storage=source_storage
    )

    copy_callback = CopyCallback() if show_progressbar else None
    source_storage.copy_mails(msg_paths, target_repo_folder, copy_callback)


@cli.command('export', help='Export one message to another folder.')
@click.argument('msg_path', type=click.Path(exists=True, file_okay=True, dir_okay=False), required=True)
@click.argument('export_folder', type=click.Path(file_okay=False, dir_okay=True))
@click.option('--abort-on-not-empty-folder/--not-abort-on-not-empty-folder', type=click.BOOL, default=True)
def export(msg_path: str, export_folder: str, abort_on_not_empty_folder: bool):
    repo_folder = str(PurePath(msg_path).parents[1])
    if not is_valid_repo_folder(repo_folder):
        click.echo(f'The folder {repo_folder!r} is not valid repository. '
                   f'Use command init for creating the repository')
        raise click.Abort()

    storage = Storage(repo_folder)
    mail = storage.load_mail(msg_path)

    os.makedirs(export_folder, exist_ok=True)
    if os.listdir(export_folder) and abort_on_not_empty_folder:
        click.echo(f'The {export_folder!r} folder should be empty. '
                   'Pass "--not-abort-on-not-empty-folder" to avoid this error or specify an empty folder.')
        raise click.Abort()

    copyfile(msg_path, PurePath(export_folder) / os.path.basename(msg_path))
    for attachment in mail.attachments:
        attachment_path = storage.find_attachment_path(attachment.hashsum_hex)
        copyfile(attachment_path, PurePath(export_folder) / attachment.filename)


if __name__ == '__main__':
    cli()
