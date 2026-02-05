from dataclasses import dataclass
from typing import List


@dataclass
class DoctorCheckItem:
    label: str
    ok: bool
    required: bool


@dataclass
class DoctorCheckGroup:
    title: str
    items: List[DoctorCheckItem]
    failures: int


@dataclass
class DoctorReport:
    groups: List[DoctorCheckGroup]
    info_messages: List[str]
    total_failures: int
