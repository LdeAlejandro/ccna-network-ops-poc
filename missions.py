"""Curated operations using stable IDs from the bundled CCNA bank."""

from dataclasses import dataclass
from pathlib import Path


CONTENT = Path(__file__).resolve().parent / "content"


@dataclass(frozen=True)
class Mission:
    id: str
    name: str
    briefing: str
    objective: str
    focus: str
    difficulty: int
    reward: int
    questions: tuple[str, ...]

    @property
    def passing_score(self):
        return (len(self.questions) * 4 + 4) // 5


def question_ids(*suffixes):
    return tuple("ccna-exam-v2-" + suffix for suffix in suffixes)


MISSIONS = (
    Mission("M01", "CONSOLE RECOVERY",
            "A branch router rebooted after maintenance. Identify its software, navigate the CLI and verify the saved configuration.",
            "Verify the recovered router configuration.",
            "Cisco platforms / CLI / configuration and backups", 1, 60,
            question_ids("01-08", "02-07", "03-08", "04-10", "05-09")),
    Mission("M02", "SESSION TRACE",
            "A service is reachable at the link layer, but application sessions are unreliable. Trace the encapsulation and transport decisions.",
            "Trace the failing transport session.",
            "OSI / TCP and UDP / ports / traffic types", 2, 80,
            question_ids("06-08", "07-08", "08-06", "09-05", "10-09")),
    Mission("M03", "SUBNET OPS",
            "A branch expansion needs an addressing plan. Verify boundaries, size the LANs and allocate point-to-point addresses.",
            "Validate the new IPv4 allocation plan.",
            "IPv4 masks / binary / CIDR / VLSM / special prefixes", 3, 100,
            question_ids("11-08", "12-08", "13-09", "14-09", "15-08", "16-08")),
    Mission("M04", "THE VLAN BREACH",
            "Two departments lost reachability after an access-layer move. Trace how hosts choose a next hop and how switches forward traffic.",
            "Restore reachability between departments.",
            "Inter-VLAN routing / Ethernet frames / switching / ARP", 2, 80,
            ("vlan-001", *question_ids("18-10", "19-03", "19-08", "26-05"))),
    Mission("M05", "ETHERNET TRIAGE",
            "A campus rollout has unstable links and an unpowered endpoint. Identify the device roles, media and link conditions involved.",
            "Isolate link and endpoint power faults.",
            "Ethernet duplex / fiber / PoE / device roles / IOS interfaces", 2, 80,
            question_ids("20-08", "21-08", "22-10", "23-10", "24-10")),
    Mission("M06", "STATIC ROUTE RECOVERY",
            "A remote office can reach its local gateway but loses access beyond the transit link. Verify the route and its return path.",
            "Restore remote-office reachability.",
            "IPv4 static routes / next hops / NAT / diagnostics", 3, 100,
            question_ids("25-03", "25-08", "25-10", "17-10", "26-09")),
)
MISSIONS_BY_ID = {mission.id: mission for mission in MISSIONS}


def load_bundled(engine):
    """Register the shipped sources alongside existing imports."""
    bank = CONTENT / "generated" / "ccna-v1.1-exam-style-v2"
    paths = sorted(bank.glob("[0-9][0-9]-*.json"))
    if len(paths) != 26:
        raise ValueError("The bundled CCNA bank is incomplete.")
    for path in (CONTENT / "vlan-troubleshooting.json", *paths):
        engine.ingest(path, keep_existing=True)
    for name in ("ios-basics", "ipv4-subnetting", "network-fundamentals"):
        engine.ingest(CONTENT / f"{name}.json", feedback_only=True)
