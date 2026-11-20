"""Mock dashboard data and shared visual tokens."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    name: str
    background: str
    panel: str
    border: str
    secondary: str
    shadow: str
    text: str
    muted: str
    accent: str


THEMES = (
    Theme("Mint Circuit", "080e11", "101b20", "66f6c5", "6bdcf7", "245255", "f0f8fa", "9bb8bd", "ffd16e"),
    Theme("Neon Rose", "09060f", "12091b", "ff4f91", "b77ad1", "69347f", "f5d9ed", "c89cce", "ff69a6"),
    Theme("Cyber Emerald", "050f0a", "0d2016", "58ffc2", "38f3d5", "22573a", "e9fff0", "96c2a4", "a7ff9f"),
    Theme("Amber CRT", "110c05", "211609", "ffb647", "ff9153", "703b1a", "fff1d7", "cfad7a", "ffdb75"),
    Theme("Violet Protocol", "0e0a19", "191329", "b59aff", "a87cff", "493273", "f5efff", "b7acd5", "ddd0ff"),
)

XP, XP_GOAL = 640, 1000
MISSION_DETAILS = (
    ("TYPE", "SWITCHING LAB"),
    ("DIFFICULTY", "02 / 05"),
    ("XP REWARD", "+400 XP"),
    ("FOCUS", "VLAN TRUNKING"),
)

PANELS = (
    ("CURRENT MISSION", ("M04 / VLANs and Trunking", "Configure an 802.1Q trunk", "Objectives completed  2 / 4")),
    ("RECENT PROGRESS", ("Subnetting drills  8 / 10", "Switching basics  complete")),
    ("NEXT REVIEW", ("Today     IPv4 subnet masks", "Tomorrow  Ethernet switching")),
    ("STUDIED TOPICS", ("IPv4 addressing", "OSI and TCP/IP", "VLAN fundamentals")),
    ("UNLOCKED GEAR", ("Console cable", "Access switch", "Packet analyzer")),
)
