"""Audit the generated bank and exercise the app with isolated study data."""

from collections import Counter
from contextlib import closing
from difflib import SequenceMatcher
from ipaddress import IPv4Address as address, IPv4Network as network
from ipaddress import collapse_addresses, summarize_address_range
from itertools import combinations
import json
import os
from pathlib import Path
from random import Random
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

BANK = Path(__file__).resolve().parent
REPO = BANK.parents[2]
sys.path.insert(0, str(REPO))

from learning import Learning, LearningError, WEIGHTS, parse_pack
from ops import Dashboard


def normalized(value):
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def check_calculations(questions):
    def check(suffix, expected):
        q = questions["ccna-exam-v2-" + suffix]
        answers = [q["options"][k] for k in q["correct_answers"]]
        assert answers == [str(expected)], (suffix, answers, expected)

    def hosts(cidr):
        return list(network(cidr, strict=False).hosts())

    def longest(first, second):
        return max(
            length for length in range(33)
            if address(second) in network(f"{first}/{length}", strict=False)
        )

    def aggregate(*prefixes):
        return list(collapse_addresses(map(network, prefixes)))

    def smallest(needed):
        return max(bits for bits in range(31) if (1 << (32 - bits)) - 2 >= needed)

    check("09-03", 64 - 3)
    check("09-05", 84 - 5 * 4)
    check("10-05", network("198.51.100.64/26").broadcast_address)
    check("11-01", 1 << (8 - 3))
    check("11-02", int("10000001", 2))
    check("11-03", int("10110110", 2))
    check("11-04", f"{107:08b}")
    check("11-05", f"{int(str(network('0.0.0.0/19').netmask).split('.')[2]):08b}")
    check("11-06", f"{0b11010110 & 0b11110000:08b}")
    check("11-07", address(bytes(int(b, 2) for b in "11001011 00000000 01110001 00010011".split())))
    check("11-08", f"{int(network('192.0.2.173/28', strict=False).network_address) & 255:08b}")
    check("11-09", f"{int(address('198.51.100.109')) & 31:05b}")
    check("11-10", f"/{longest('192.0.2.114', '192.0.2.127')}")
    check("12-01", network("0.0.0.0/22").netmask)
    check("12-02", 32 - network("0.0.0.0/19").prefixlen)
    check("12-03", f"/{network('0.0.0.0/255.255.255.248').prefixlen}")
    valid_masks = {str(network(f"0.0.0.0/{p}").netmask) for p in range(33)}
    q = questions["ccna-exam-v2-12-04"]
    mask, = valid_masks & set(q["options"].values())
    check("12-04", mask)
    assert address("192.0.2.157") in hosts("192.0.2.142/27")
    assert address("198.51.100.101") not in network("198.51.100.94/27", strict=False)
    assert address("198.51.100.65") in hosts("198.51.100.94/27")
    assert address("198.51.100.70") not in network("198.51.100.61/26", strict=False)
    assert address("198.51.100.61") in network("198.51.100.70/25", strict=False)
    check("12-09", f"/{longest('203.0.113.33', '203.0.113.62')}")
    local = network("172.19.47.32/21", strict=False)
    matching, = (a for a in questions["ccna-exam-v2-12-10"]["options"].values() if address(a) in local)
    check("12-10", matching)
    assert address("127.5.4.3").is_loopback
    check("13-07", network("203.0.113.183/26", strict=False).network_address)
    check("13-09", network("172.22.112.0/20").broadcast_address)
    check("14-01", network("0.0.0.0/28").num_addresses)
    check("14-02", 27 - 24)
    check("14-03", len(list(network("10.0.0.0/20").subnets(new_prefix=24))))
    check("14-04", len(hosts("192.0.2.0/25")))
    check("14-05", hosts("198.51.100.144/28")[0])
    check("14-06", hosts("203.0.113.200/30")[-1])
    check("14-07", network("172.18.171.8/21", strict=False).network_address)
    usable = hosts("10.31.195.74/19")
    check("14-08", f"{usable[0]}–{usable[-1]}")
    feasible = [
        p for p in range(25, 31)
        if len(list(network("192.0.2.0/24").subnets(new_prefix=p))) >= 6
        and len(hosts(f"192.0.2.0/{p}")) >= 25
    ]
    assert feasible == [27]
    check("14-09", f"/{feasible[0]}")
    check("14-10", network("192.0.2.110/29", strict=False).broadcast_address)
    check("15-03", f"/{smallest(62)}")
    assert str(network("192.0.2.48/27", strict=False)) == "192.0.2.32/27"
    reserved = list(map(network, ["192.0.2.0/25", "192.0.2.128/26"]))
    check("15-05", next(n for n in network("192.0.2.0/24").subnets(new_prefix=27)
                        if not any(n.overlaps(r) for r in reserved)))
    check("15-06", aggregate("172.28.44.0/24", "172.28.45.0/24")[0])
    check("15-07", aggregate("198.51.100.0/25", "198.51.100.128/26", "198.51.100.192/26")[0])
    consumed = sum(network(f"0.0.0.0/{smallest(n)}").num_addresses for n in (120, 60, 28, 12))
    check("15-08", f"{256 - consumed} addresses")
    extra = list(network("10.20.8.0/21").address_exclude(network("10.20.8.0/22")))[0]
    check("15-09", f"{extra.network_address}–{extra.broadcast_address}")
    check("15-10", " and ".join(map(str, summarize_address_range(address("203.0.113.0"), address("203.0.113.191")))))
    check("16-01", f"/{longest('198.51.100.77', '198.51.100.77')}")
    check("16-02", len(hosts("192.0.2.0/30")))
    check("16-03", " and ".join(map(str, hosts("192.0.2.36/31"))))
    check("16-04", f"/{smallest(3)}")
    check("16-07", next(a for a in hosts("203.0.113.53/31") if a != address("203.0.113.53")))
    assert network("198.51.100.97/31", strict=False) != network("198.51.100.98/31", strict=False)
    check("16-09", 8 * (network("0.0.0.0/30").num_addresses - network("0.0.0.0/31").num_addresses))
    target = network("203.0.113.42/32")
    assert address("192.0.2.3") in hosts("192.0.2.0/29")
    check("16-10", f"ip route {target.network_address} {target.netmask} 192.0.2.3")
    private = list(map(network, ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")))
    for i in range(1, 5):
        suffix = f"17-{i:02}"
        q = questions["ccna-exam-v2-" + suffix]
        matches = [a for a in q["options"].values()
                   if any(network(a).subnet_of(p) for p in private)]
        assert len(matches) == 1
        check(suffix, matches[0])


def check_packs(paths):
    schema = json.loads((REPO / "question-pack.schema.json").read_text())
    spec = schema["$defs"]["question"]
    assert set(spec["properties"]["category"]["enum"]) == set(WEIGHTS)
    earlier = [parse_pack(p.read_text()) for p in sorted((REPO / "content").glob("*.json"))]
    pack_ids = {pid for pid, _, _, _ in earlier}
    seen_ids = {qid for _, _, _, items in earlier for qid in items}
    topics, questions, wording = set(), {}, {}
    all_categories, all_difficulties, keys = Counter(), Counter(), Counter()
    for path in paths:
        raw = path.read_text()
        document = json.loads(raw)
        pack_id, _, topic, items = parse_pack(raw)
        assert set(schema["required"]) <= document.keys()
        assert pack_id not in pack_ids and topic not in topics and len(items) == 10
        pack_ids.add(pack_id)
        topics.add(topic)
        for item in document["questions"]:
            assert set(spec["required"]) <= item.keys()
            assert item["type"] in spec["properties"]["type"]["enum"]
        for qid, q in items.items():
            assert qid not in seen_ids and set(q["options"]) == set("ABCD")
            seen_ids.add(qid)
            stem = normalized(q["question"])
            assert stem not in wording.values()
            wording[qid] = stem
            for option in q["options"].values():
                assert normalized(option) not in {"all of the above", "none of the above"}
            if q["type"] == "multiple_choice":
                assert q["question"].startswith("Select TWO.") and len(q["correct_answers"]) == 2
            else:
                keys.update(q["correct_answers"])
            assert q["option_explanations"].keys() == q["options"].keys()
            if q["snippet"]:
                assert q["snippet"].startswith("Illustrative excerpt\n")
                assert max(map(len, q["snippet"].splitlines())) <= 80
            questions[qid] = q
        categories = Counter(q["category"] for q in items.values())
        difficulties = Counter(q["difficulty"] for q in items.values())
        assert 2 <= difficulties[1] <= 3 and 4 <= difficulties[2] <= 5 and 2 <= difficulties[3] <= 3
        all_categories.update(categories)
        all_difficulties.update(difficulties)
        print(f"{path.name}: {dict(categories)}, {dict(sorted(difficulties.items()))}")
    for (a, left), (b, right) in combinations(wording.items(), 2):
        assert SequenceMatcher(None, left, right).ratio() < 0.90, (a, b)
    assert len(topics) == 26 and len(questions) == 260
    assert set(keys) == set("ABCD") and max(keys.values()) - min(keys.values()) <= 3
    assert set(all_difficulties) == {1, 2, 3}
    print(f"Totals: {dict(all_categories)}, {dict(sorted(all_difficulties.items()))}; single-answer keys {dict(sorted(keys.items()))}")
    return questions


def check_exhibits(questions):
    def item(suffix):
        return questions[f"ccna-exam-v2-{suffix}"]

    def answer(q):
        key, = q["correct_answers"]
        return q["options"][key]

    for suffix, destination in (("25-03", "203.0.113.77"), ("25-08", "198.51.100.200")):
        q = item(suffix)
        routes = [(network(prefix), address(hop)) for prefix, hop in
                  re.findall(r"^S (\S+) \[1/0\] via (\S+)", q["snippet"], re.M)]
        connected, = re.findall(r"^C (\S+) is directly connected", q["snippet"], re.M)
        assert all(hop in network(connected) for _, hop in routes)
        best = max((route for route in routes if address(destination) in route[0]),
                   key=lambda route: route[0].prefixlen)
        assert answer(q) == str(best[1])
    q = item("24-01")
    interface, = re.findall(r"^(Gi\S+) +\S+ +YES DHCP +up +up$", q["snippet"], re.M)
    assert answer(q) == interface
    q = item("25-06")
    local, = re.findall(r"^L (\S+)", q["snippet"], re.M)
    assert network(local).prefixlen == 32 and answer(q) == local
    q = item("26-05")
    port, = re.findall(r"^ +20 +001a[.]2b03[.]04c5 +DYNAMIC +(\S+)$", q["snippet"], re.M)
    assert answer(q) == port


def check_app(paths, questions):
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        data = root / "ccna-network-ops"
        inbox = data / "inbox"
        inbox.mkdir(parents=True)
        cli = [sys.executable, str(REPO / "ops.py"), "--feed"]
        env = {**os.environ, "XDG_DATA_HOME": tmp, "XDG_CONFIG_HOME": tmp}
        starter_paths = sorted((REPO / "content").glob("*.json"))
        starter_ids = {qid for path in starter_paths for qid in parse_pack(path.read_text())[3]}
        for path in [*starter_paths, *paths[:-1]]:
            result = subprocess.run([*cli, str(path)], env=env, check=True, capture_output=True, text=True)
            assert result.stdout.startswith("Imported ")
        shutil.copyfile(paths[-1], inbox / paths[-1].name)
        db = data / "learning.sqlite3"
        with closing(Learning(db)) as engine:
            app = Dashboard(root / "theme", engine, inbox)
            for key in ("f", "t", "ENTER"):
                app.key(key)
            assert app.notice == f"Imported {paths[-1].name}"
            sources = engine.sources()
            packs = {parse_pack(path.read_text())[0] for path in paths}
            assert sum(s["question_count"] for s in sources if s["id"][5:] in packs) == 260
            assert {q["topic"] for q in questions.values()} <= engine.summary()["topics"].keys()
            try:
                engine.ingest(paths[0])
            except LearningError as error:
                assert "already imported" in str(error)
            else:
                raise AssertionError("Duplicate pack was accepted")
            app.key("ESC")
            rng = Random(42)
            with patch("learning.expovariate", rng.expovariate):
                app.key("x")
            attempts = 0
            modes = set()
            while len(modes) < 2 and attempts < 270:
                q = engine.session()["data"]
                assert q["id"] in questions or q["id"] in starter_ids
                frame = app.frame(140, 45)
                assert "QUIZ MODE" in frame and "Correct:" not in frame
                for key in q["correct_answers"]:
                    app.key(key.lower())
                app.key("ENTER")
                assert engine.session()["correct"] == 1
                feedback = app.frame(140, 45)
                assert "Correct:" in feedback and "ANSWER REVIEW" in feedback
                for key, reason in q["option_explanations"].items():
                    state = "Correct" if key in q["correct_answers"] else "Incorrect"
                    assert f"{key}. {state}" in feedback
                    assert reason[:30] in feedback
                if q["id"] in questions:
                    modes.add(q["type"])
                attempts += 1
                if len(modes) < 2:
                    app.key("n")
                    if app.mode == "practice_result":
                        with patch("learning.expovariate", rng.expovariate):
                            app.key("ENTER")
            assert modes == {"single_choice", "multiple_choice"}
            expected = engine.session()["question"]
        with closing(Learning(db)) as engine:
            app = Dashboard(root / "theme", engine, inbox)
            app.key("x")
            assert engine.session()["question"] == expected
            assert "Correct:" in app.frame(140, 45)
    print(f"App smoke passed: CLI and Feed imports, duplicate gate, both answer types, feedback and restart ({attempts} submissions).")


if __name__ == "__main__":
    paths = sorted(BANK.glob("[0-9][0-9]-*.json"))
    questions = check_packs(paths)
    check_calculations(questions)
    check_exhibits(questions)
    check_app(paths, questions)
