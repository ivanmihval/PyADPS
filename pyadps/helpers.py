# -*- coding: utf-8 -*-
import hashlib
from dataclasses import dataclass
from io import IOBase


@dataclass
class CalculateHashResult:
    hex_digest: str
    size_bytes: int


def calculate_hashsum(stream: IOBase) -> CalculateHashResult:
    file_hash = hashlib.sha512()
    filesize_bytes = 0
    while chunk := stream.read(8 * 1024 * 1024):  # read 8 MB
        filesize_bytes += len(chunk)
        file_hash.update(chunk)

    return CalculateHashResult(file_hash.hexdigest(), filesize_bytes)


def calculate_hashsum_hex_from_file(path: str) -> str:
    with open(path, 'rb') as file_stream:
        return calculate_hashsum(file_stream).hex_digest
