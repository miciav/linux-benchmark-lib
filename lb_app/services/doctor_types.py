from dataclasses import dataclass


@dataclass
class DoctorCheckItem:
    label: str
    ok: bool
    required: bool


@dataclass
class DoctorCheckGroup:
    title: str
    items: list[DoctorCheckItem]
    failures: int


@dataclass
class DoctorReport:
    groups: list[DoctorCheckGroup]
    info_messages: list[str]
    total_failures: int
