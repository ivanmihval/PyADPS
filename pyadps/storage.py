# -*- coding: utf-8 -*-
import json
import os
import os.path
from dataclasses import dataclass
from enum import Enum
from glob import glob
from io import BytesIO
from json import load
from pathlib import Path, PurePath
from shutil import copyfile
from typing import Callable, Collection, Generator, Iterable, List, NamedTuple, Optional, Union

from pyadps.helpers import calculate_hashsum, calculate_hashsum_hex_from_file
from pyadps.mail import Mail, MailAttachmentInfo, MailFilter


class MessageFileTooBigError(Exception):
    pass


class FileSearchResult(NamedTuple):
    path: str
    is_exist: bool


@dataclass
class FilteredMailResult:
    mail: Mail
    mail_path: str
    mail_hashsum_hex: str


class FilterMailCallbackData(NamedTuple):
    current_mail_idx: int
    total_mails_number: int


class CopyMailCallbackData(NamedTuple):
    current_file_idx: int
    current_file_bytes: int

    total_files_number: int
    total_files_size_bytes: int

    copied_bytes: int


class CopyMailsStage(Enum):
    ESTIMATION = 'ESTIMATION'
    COPYING = 'COPYING'


class CopyMailsCallbackData(NamedTuple):
    stage: CopyMailsStage

    estimation_progress: Optional[FilterMailCallbackData] = None
    copying_progress: Optional[CopyMailCallbackData] = None


class CopyMailCallback:
    def __init__(
        self,
        total_files_number: int,
        total_files_size_bytes: int,
        copy_mails_callback: Optional[Callable[[CopyMailsCallbackData], None]],
    ):
        self.total_files_number = total_files_number
        self.total_files_size_bytes = total_files_size_bytes
        self.copy_mails_callback = copy_mails_callback

        self.bytes_copied = 0
        self.files_copied = 0

    def __call__(self, callback_data: CopyMailCallbackData) -> None:
        self.bytes_copied += callback_data.current_file_bytes
        self.files_copied += 1

        self.copy_mails_callback(CopyMailsCallbackData(
            stage=CopyMailsStage.COPYING,
            copying_progress=CopyMailCallbackData(
                total_files_number=self.total_files_number,
                current_file_idx=self.files_copied - 1,
                current_file_bytes=callback_data.current_file_bytes,
                total_files_size_bytes=self.total_files_size_bytes,
                copied_bytes=self.bytes_copied,
            )
        ))


class Storage:
    MESSAGES_FOLDER = 'adps_messages'
    ATTACHMENTS_FOLDERS = 'adps_attachments'
    HASHSUM_FILENAME_PART_LEN = 10
    MESSAGE_FILE_MAX_SIZE_BYTES = 4 * 1024  # 4 KB

    def __init__(self, root_dir_path: str):
        self.root_dir_path = root_dir_path

    @classmethod
    def get_free_file_path(cls, path: Union[str, PurePath], hashsum_hex: str) -> FileSearchResult:
        attempts = 10000

        if not os.path.isfile(path):
            return FileSearchResult(path, False)

        if calculate_hashsum_hex_from_file(path) == hashsum_hex:
            return FileSearchResult(path, True)

        root, ext = os.path.splitext(path)
        for i in range(attempts):
            new_path = f'{root}_{i}{ext}'
            if not os.path.isfile(new_path):
                return FileSearchResult(path, False)

            if calculate_hashsum_hex_from_file(new_path) == hashsum_hex:
                return FileSearchResult(path, True)

        raise Exception(f'Could not get free path value for {path!r}')

    def find_attachment_path(self, hashsum_hex: str) -> str:
        attachments_folder_path = PurePath(self.root_dir_path) / self.ATTACHMENTS_FOLDERS
        for attachment_path in glob(f'{attachments_folder_path}/{hashsum_hex[:self.HASHSUM_FILENAME_PART_LEN]}*'):
            calculated_hashsum = calculate_hashsum_hex_from_file(attachment_path)
            if calculated_hashsum == hashsum_hex:
                return os.path.abspath(attachment_path)

        raise FileNotFoundError()

    @classmethod
    def load_mail(cls, msg_path) -> Mail:
        size_bytes = os.path.getsize(msg_path)
        if size_bytes > cls.MESSAGE_FILE_MAX_SIZE_BYTES:
            raise MessageFileTooBigError()

        with open(msg_path) as msg_json_file:
            msg_json = load(msg_json_file)

        return Mail.Schema().load(msg_json)

    def filter_mails(
        self,
        mail_filter: Optional[MailFilter],
        callback: Optional[Callable[[FilterMailCallbackData], None]] = None,
    ) -> Generator[FilteredMailResult, None, None]:
        messages_folder_path = PurePath(self.root_dir_path) / self.MESSAGES_FOLDER
        message_paths = glob(f'{messages_folder_path}/*.json')
        for idx, msg_path in enumerate(message_paths):
            mail = self.load_mail(msg_path)
            hashsum_hex = calculate_hashsum_hex_from_file(msg_path)
            if mail_filter is None or mail_filter.filter_func(mail):
                yield FilteredMailResult(mail, os.path.abspath(msg_path), hashsum_hex)

            if callback is not None:
                callback(FilterMailCallbackData(idx, len(message_paths)))

    def save_mail(self, mail: Mail, mail_attachment_infos: List[MailAttachmentInfo], target_folder_path: str):
        messages_folder = PurePath(target_folder_path) / self.MESSAGES_FOLDER
        attachments_folder = PurePath(target_folder_path) / self.ATTACHMENTS_FOLDERS

        os.makedirs(messages_folder, exist_ok=True)
        os.makedirs(attachments_folder, exist_ok=True)

        mail_serialized = Mail.Schema().dump(mail)
        mail_json_bytes = json.dumps(mail_serialized, indent=4, sort_keys=True).encode()
        hashsum = calculate_hashsum(BytesIO(mail_json_bytes))

        file_search_result = self.get_free_file_path(
            messages_folder
            / f'{hashsum.hex_digest[:self.HASHSUM_FILENAME_PART_LEN]}.json',
            hashsum_hex=hashsum.hex_digest
        )

        if not file_search_result.is_exist:
            with open(file_search_result.path, 'wb') as target_message_file:
                target_message_file.write(mail_json_bytes)

        for mail_attachment_info in mail_attachment_infos:
            try:
                attachment_path = self.find_attachment_path(mail_attachment_info.hashsum_hex)
            except FileNotFoundError:
                attachment_path = mail_attachment_info.path

            target_file_search_result = self.get_free_file_path(
                attachments_folder
                / f'{mail_attachment_info.hashsum_hex[:self.HASHSUM_FILENAME_PART_LEN]}.bin',
                hashsum_hex=mail_attachment_info.hashsum_hex
            )

            if not target_file_search_result.is_exist:
                copyfile(attachment_path, target_file_search_result.path)

    def copy_mail(
        self,
        original_json_path: str,
        target_folder_path: str,
        callback: Optional[Callable[[CopyMailCallbackData], None]] = None
    ):
        messages_folder = PurePath(target_folder_path) / self.MESSAGES_FOLDER
        attachments_folder = PurePath(target_folder_path) / self.ATTACHMENTS_FOLDERS

        message_file_hashsum = calculate_hashsum_hex_from_file(original_json_path)

        file_search_result = self.get_free_file_path(
            messages_folder
            / f'{message_file_hashsum[:self.HASHSUM_FILENAME_PART_LEN]}.json',
            hashsum_hex=message_file_hashsum
        )

        mail = self.load_mail(original_json_path)

        mail_file_size_bytes = os.path.getsize(original_json_path)
        attachments_size_bytes = sum(attachment.size_bytes for attachment in mail.attachments)
        total_files_size_bytes = mail_file_size_bytes + attachments_size_bytes

        if not file_search_result.is_exist:
            copyfile(original_json_path, file_search_result.path)
            if callback is not None:
                callback(CopyMailCallbackData(
                    total_files_number=len(mail.attachments) + 1,  # + original json file
                    current_file_idx=0,
                    current_file_bytes=mail_file_size_bytes,
                    total_files_size_bytes=total_files_size_bytes,
                    copied_bytes=mail_file_size_bytes,
                ))

        attachments_bytes_copied = 0
        for idx, attachment in enumerate(mail.attachments, start=1):
            attachment_path = self.find_attachment_path(attachment.hashsum_hex)
            attachment_hashsum = calculate_hashsum_hex_from_file(attachment_path)
            target_file_search_result = self.get_free_file_path(
                attachments_folder
                / f'{attachment.hashsum_hex[:self.HASHSUM_FILENAME_PART_LEN]}.bin',
                hashsum_hex=attachment_hashsum
            )

            if not target_file_search_result.is_exist:
                copyfile(attachment_path, target_file_search_result.path)

            attachments_bytes_copied += attachment.size_bytes

            if callback is not None:
                callback(CopyMailCallbackData(
                    total_files_number=len(mail.attachments) + 1,  # + original json file
                    current_file_idx=idx,
                    current_file_bytes=attachment.size_bytes,
                    total_files_size_bytes=total_files_size_bytes,
                    copied_bytes=mail_file_size_bytes + attachments_bytes_copied,
                ))

    def copy_mails(
        self,
        msg_paths: Collection[Union[str, Path]],
        target_folder_path: Union[str, Path],
        callback: Optional[Callable[[CopyMailsCallbackData], None]] = None
    ):
        total_files_number = None
        total_files_size_bytes = None
        if callback is not None:
            total_files_number = 0
            total_files_size_bytes = 0

            for idx, msg_path in enumerate(msg_paths):
                msg_file_size_bytes = os.path.getsize(msg_path)
                mail = self.load_mail(msg_path)
                attachments_size_bytes = sum(attachment.size_bytes for attachment in mail.attachments)
                mail_files_size_bytes = msg_file_size_bytes + attachments_size_bytes

                total_files_number += len(mail.attachments) + 1
                total_files_size_bytes += mail_files_size_bytes

                callback(CopyMailsCallbackData(
                    stage=CopyMailsStage.ESTIMATION,
                    estimation_progress=FilterMailCallbackData(idx, len(msg_path))
                ))

        messages_folder = PurePath(target_folder_path) / self.MESSAGES_FOLDER
        attachments_folder = PurePath(target_folder_path) / self.ATTACHMENTS_FOLDERS

        os.makedirs(messages_folder, exist_ok=True)
        os.makedirs(attachments_folder, exist_ok=True)

        copy_mail_callback = (
            None if callback is None
            else CopyMailCallback(
                total_files_number=total_files_number,
                total_files_size_bytes=total_files_size_bytes,
                copy_mails_callback=callback,
            )
        )

        for msg_path in msg_paths:
            self.copy_mail(msg_path, target_folder_path, copy_mail_callback)

    def get_attachments_for_delete(
        self,
        msg_paths: Iterable[Union[str, Path]],
        callback: Optional[Callable[[FilterMailCallbackData], None]] = None,
    ) -> List[str]:
        """
        Checks every message file in the repo and returns paths of attachments for delete if they aren't linked
        to other messages (except messages in msg_paths arg)
        """
        messages_folder_path = PurePath(self.root_dir_path) / self.MESSAGES_FOLDER

        attachment_hashsums_to_delete = set()
        attachment_path_by_hashsum = {}
        msg_paths_to_delete = set()
        for msg_path in msg_paths:
            msg_paths_to_delete.add(os.path.abspath(msg_path))

            mail = self.load_mail(msg_path)
            for attachment in mail.attachments:
                try:
                    attachment_path = self.find_attachment_path(attachment.hashsum_hex)
                    attachment_hashsums_to_delete.add(attachment.hashsum_hex)
                    attachment_path_by_hashsum[attachment.hashsum_hex] = attachment_path
                except FileNotFoundError:
                    continue

        message_paths = glob(f'{messages_folder_path}/*.json')
        for idx, msg_path in enumerate(message_paths):
            if callback is not None:
                callback(FilterMailCallbackData(idx, len(message_paths)))

            if os.path.abspath(msg_path) in msg_paths_to_delete:
                continue

            mail = self.load_mail(msg_path)
            for attachment in mail.attachments:
                if attachment.hashsum_hex in attachment_hashsums_to_delete:
                    attachment_hashsums_to_delete.remove(attachment.hashsum_hex)

        return [attachment_path_by_hashsum[hashsum] for hashsum in attachment_hashsums_to_delete]
