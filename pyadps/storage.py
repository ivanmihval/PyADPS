# -*- coding: utf-8 -*-
import itertools
import json
import os
import os.path
from dataclasses import dataclass
from enum import Enum
from glob import glob, iglob
from io import BytesIO
from json import load
from pathlib import Path, PurePath
from shutil import copyfile
from typing import Callable, Collection, Generator, List, NamedTuple, Optional, Union

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


@dataclass
class EstimationFileResult:
    path: str
    hashsum_hex: str
    size_bytes: int


class FilterMailCallbackData(NamedTuple):
    current_mail_idx: int
    total_mails_number: int


class EstimationDeleteMailsStage(Enum):
    SCANNING_TARGET_FILES = 'SCANNING_TARGET_FILES'
    SCANNING_ALL_FILES = 'SCANNING_ALL_FILES'


class EstimationDeleteMailsCallbackData(NamedTuple):
    stage: EstimationDeleteMailsStage
    callback_data: FilterMailCallbackData


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


class Storage:
    MESSAGES_FOLDER = 'adps_messages'
    ATTACHMENTS_FOLDER = 'adps_attachments'
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
        attachments_folder_path = PurePath(self.root_dir_path) / self.ATTACHMENTS_FOLDER

        default_path = attachments_folder_path / (hashsum_hex[:self.HASHSUM_FILENAME_PART_LEN] + '.bin')
        default_paths = [default_path] if os.path.exists(default_path) else []

        for attachment_path in itertools.chain(
            default_paths,
            iglob(f'{attachments_folder_path}/{hashsum_hex[:self.HASHSUM_FILENAME_PART_LEN]}*')
        ):
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
        attachments_folder = PurePath(target_folder_path) / self.ATTACHMENTS_FOLDER

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
            attachment_path = mail_attachment_info.path

            target_file_search_result = self.get_free_file_path(
                attachments_folder
                / f'{mail_attachment_info.hashsum_hex[:self.HASHSUM_FILENAME_PART_LEN]}.bin',
                hashsum_hex=mail_attachment_info.hashsum_hex
            )

            if not target_file_search_result.is_exist:
                copyfile(attachment_path, target_file_search_result.path)

    def copy_mails(
        self,
        msg_paths: Collection[Union[str, Path]],
        target_folder_path: Union[str, Path],
        callback: Optional[Callable[[CopyMailsCallbackData], None]] = None
    ):
        mail_files_estimation_results: List[EstimationFileResult] = []
        attachments_files_estimation_results: List[EstimationFileResult] = []

        attachments_files_hashsums = set()

        for idx, msg_path in enumerate(msg_paths):
            msg_file_size_bytes = os.path.getsize(msg_path)
            mail_files_estimation_results.append(
                EstimationFileResult(msg_path, calculate_hashsum_hex_from_file(msg_path), msg_file_size_bytes)
            )

            mail = self.load_mail(msg_path)
            for attachment in mail.attachments:
                if attachment.hashsum_hex not in attachments_files_hashsums:
                    attachments_files_hashsums.add(attachment.hashsum_hex)
                    attachment_path = self.find_attachment_path(attachment.hashsum_hex)
                    attachments_files_estimation_results.append(
                        EstimationFileResult(attachment_path, attachment.hashsum_hex, attachment.size_bytes)
                    )

            if callback is not None:
                callback(CopyMailsCallbackData(
                    stage=CopyMailsStage.ESTIMATION,
                    estimation_progress=FilterMailCallbackData(idx, len(msg_paths))
                ))

        total_files_number = len(mail_files_estimation_results) + len(attachments_files_estimation_results)
        total_files_size_bytes = sum(
            estimation_result.size_bytes
            for estimation_result
            in itertools.chain(mail_files_estimation_results, attachments_files_estimation_results)
        )

        messages_folder = PurePath(target_folder_path) / self.MESSAGES_FOLDER
        attachments_folder = PurePath(target_folder_path) / self.ATTACHMENTS_FOLDER

        os.makedirs(messages_folder, exist_ok=True)
        os.makedirs(attachments_folder, exist_ok=True)

        copied_bytes = 0
        for idx, (folder, estimation_result, extension) in enumerate(itertools.chain(
            zip(itertools.repeat(messages_folder), mail_files_estimation_results, itertools.repeat('json')),
            zip(itertools.repeat(attachments_folder), attachments_files_estimation_results, itertools.repeat('bin'))
        )):
            file_search_result = self.get_free_file_path(
                folder
                / f'{estimation_result.hashsum_hex[:self.HASHSUM_FILENAME_PART_LEN]}.{extension}',
                hashsum_hex=estimation_result.hashsum_hex
            )

            if not file_search_result.is_exist:
                copyfile(estimation_result.path, file_search_result.path)

            copied_bytes += estimation_result.size_bytes

            if callback is not None:
                callback(CopyMailsCallbackData(
                    stage=CopyMailsStage.COPYING,
                    copying_progress=CopyMailCallbackData(
                        current_file_idx=idx,
                        current_file_bytes=estimation_result.size_bytes,
                        total_files_number=total_files_number,
                        total_files_size_bytes=total_files_size_bytes,
                        copied_bytes=copied_bytes,
                    )
                ))

    def get_attachments_for_delete(
        self,
        msg_paths: Collection[Union[str, Path]],
        callback: Optional[Callable[[EstimationDeleteMailsCallbackData], None]] = None,
    ) -> List[str]:
        """
        Checks every message file in the repo and returns paths of attachments for delete if they aren't linked
        to other messages (except messages in msg_paths arg)
        """
        if len(msg_paths) == 0:
            return []

        messages_folder_path = PurePath(self.root_dir_path) / self.MESSAGES_FOLDER

        attachment_hashsums_to_delete = set()
        attachment_path_by_hashsum = {}
        msg_paths_to_delete = set()
        for idx, msg_path in enumerate(msg_paths):
            msg_paths_to_delete.add(os.path.abspath(msg_path))

            mail = self.load_mail(msg_path)
            for attachment in mail.attachments:
                if attachment.hashsum_hex not in attachment_hashsums_to_delete:
                    try:
                        attachment_path = self.find_attachment_path(attachment.hashsum_hex)
                        attachment_hashsums_to_delete.add(attachment.hashsum_hex)
                        attachment_path_by_hashsum[attachment.hashsum_hex] = attachment_path
                    except FileNotFoundError:
                        continue

            if callback is not None:
                callback(EstimationDeleteMailsCallbackData(
                    EstimationDeleteMailsStage.SCANNING_TARGET_FILES,
                    FilterMailCallbackData(idx, len(msg_paths)),
                ))

        if not attachment_hashsums_to_delete:
            return []

        message_paths = glob(f'{messages_folder_path}/*.json')
        for idx, msg_path in enumerate(message_paths):
            if callback is not None:
                callback(EstimationDeleteMailsCallbackData(
                    EstimationDeleteMailsStage.SCANNING_ALL_FILES,
                    FilterMailCallbackData(idx, len(message_paths)),
                ))

            if os.path.abspath(msg_path) in msg_paths_to_delete:
                continue

            mail = self.load_mail(msg_path)
            for attachment in mail.attachments:
                if attachment.hashsum_hex in attachment_hashsums_to_delete:
                    attachment_hashsums_to_delete.remove(attachment.hashsum_hex)

        return [attachment_path_by_hashsum[hashsum] for hashsum in attachment_hashsums_to_delete]
