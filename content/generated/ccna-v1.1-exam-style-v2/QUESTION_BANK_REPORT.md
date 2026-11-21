# CCNA question bank validation report

The v2 bank contains 260 original English questions across the 26 supplied study areas. It uses the CCNA 200-301 v1.1 blueprint to calibrate terminology and task style. The bank includes 258 single-answer questions, two Select TWO questions, and 17 illustrative exhibits. Each question has four choices and feedback after submission. Cisco lists February 2, 2027 as the last day for v1.1 and February 3 as the first day for v2.0. [Cisco exam topics](https://learningnetwork.cisco.com/s/ccna-exam-topics)

An editorial count classified 161 questions (61.9%) as requiring application, calculation, interpretation, comparison or troubleshooting. It counted straightforward command or port recall as recall even when framed as a short scenario.

## Pack index

Difficulty columns show the counts for levels 1, 2 and 3. The app accepts levels 1–5. This bank uses those three levels for foundational, intermediate and advanced work within the supplied scope.

| Pack | Study area | Category | Questions | Difficulty 1 / 2 / 3 |
| --- | --- | --- | ---: | --- |
| [01-cisco-systems.json](01-cisco-systems.json) | Cisco systems | `networking_theory` | 10 | 3 / 4 / 3 |
| [02-cli-navigation.json](02-cli-navigation.json) | CLI navigation | `ios_commands` | 10 | 3 / 5 / 2 |
| [03-cli-help-and-editing.json](03-cli-help-and-editing.json) | CLI help and editing | `ios_commands` | 10 | 3 / 4 / 3 |
| [04-configurations-and-backups.json](04-configurations-and-backups.json) | Configurations and backups | `ios_commands` | 10 | 3 / 4 / 3 |
| [05-output-filters.json](05-output-filters.json) | Output filters | `ios_output` | 10 | 2 / 5 / 3 |
| [06-osi-and-tcp-ip.json](06-osi-and-tcp-ip.json) | OSI and TCP/IP | `networking_theory` | 10 | 3 / 4 / 3 |
| [07-tcp-and-udp.json](07-tcp-and-udp.json) | TCP and UDP | `networking_theory` | 10 | 3 / 4 / 3 |
| [08-protocols-and-ports.json](08-protocols-and-ports.json) | Protocols and ports | `networking_theory` | 10 | 3 / 4 / 3 |
| [09-ipv4.json](09-ipv4.json) | IPv4 | `networking_theory` | 10 | 3 / 5 / 2 |
| [10-traffic-types.json](10-traffic-types.json) | Traffic types | `networking_theory` | 10 | 3 / 4 / 3 |
| [11-binary.json](11-binary.json) | Binary | `subnetting` | 10 | 2 / 5 / 3 |
| [12-masks-and-prefixes.json](12-masks-and-prefixes.json) | Masks and prefixes | `subnetting` | 10 | 2 / 5 / 3 |
| [13-address-classes-and-special-addresses.json](13-address-classes-and-special-addresses.json) | Address classes and special addresses | `subnetting` | 10 | 2 / 5 / 3 |
| [14-subnetting.json](14-subnetting.json) | Subnetting | `subnetting` | 10 | 2 / 5 / 3 |
| [15-vlsm-and-cidr.json](15-vlsm-and-cidr.json) | VLSM and CIDR | `subnetting` | 10 | 2 / 5 / 3 |
| [16-special-prefixes.json](16-special-prefixes.json) | Special prefixes | `subnetting` | 10 | 2 / 5 / 3 |
| [17-private-ipv4-and-nat.json](17-private-ipv4-and-nat.json) | Private IPv4 and NAT | `networking_theory` | 10 | 2 / 5 / 3 |
| [18-ethernet-and-mac.json](18-ethernet-and-mac.json) | Ethernet and MAC | `networking_theory` | 10 | 2 / 5 / 3 |
| [19-switching-and-arp.json](19-switching-and-arp.json) | Switching and ARP | `networking_theory` | 10 | 2 / 5 / 3 |
| [20-hubs-and-duplex.json](20-hubs-and-duplex.json) | Hubs and duplex | `networking_theory` | 10 | 2 / 5 / 3 |
| [21-physical-media.json](21-physical-media.json) | Physical media | `networking_theory` | 10 | 2 / 5 / 3 |
| [22-poe.json](22-poe.json) | PoE | `networking_theory` | 10 | 2 / 5 / 3 |
| [23-network-device-roles.json](23-network-device-roles.json) | Network device roles | `networking_theory` | 10 | 2 / 5 / 3 |
| [24-ios-interfaces.json](24-ios-interfaces.json) | IOS interfaces | `ios_output` | 10 | 2 / 5 / 3 |
| [25-basic-routing.json](25-basic-routing.json) | Basic routing | `ios_output` | 10 | 2 / 5 / 3 |
| [26-basic-troubleshooting.json](26-basic-troubleshooting.json) | Basic troubleshooting | `troubleshooting` | 10 | 2 / 5 / 3 |
| **Total** | **26 areas** | | **260** | **61 / 123 / 76** |

Category totals are `networking_theory` 130, `ios_commands` 30, `ios_output` 30, `troubleshooting` 10 and `subnetting` 60. Single-answer key counts are A 65, B 65, C 65 and D 63.

## Import and practice

Run from the repository root. The CLI imports each pack and activates its topic. To choose individual topics, pass their paths to `--feed` one at a time.

```sh
for pack in content/generated/ccna-v1.1-exam-style-v2/[0-9][0-9]-*.json; do
    python3 ops.py --feed "$pack" || break
done
python3 ops.py
```

For TUI import, copy the desired JSON files into `${XDG_DATA_HOME:-$HOME/.local/share}/ccna-network-ops/inbox/`. Press **F**, then **T**, select the file and press **Enter**. Press **Esc** to return to the dashboard and **X** to open the quiz. Use **A–D** to select or toggle choices, **Enter** to submit and **N** to advance. An existing quiz resumes first. New questions join the existing active pool and use the app's normal scheduling. Each pack has its own unique `ccna-exam-v2-` identifiers. Import each pack once. Existing imports and saved progress are preserved alongside the new content.

## Verification

```sh
python3 content/generated/ccna-v1.1-exam-style-v2/validate_bank.py
python3 -m unittest
python3 verify.py
```

- The bank validator parsed all 26 packs as JSON, checked their fields and enums against the repository schema and validated every question through `parse_pack`. The pack requires `pack_id`, `version`, `topic` and `questions`. Questions use `single_choice` or `multiple_choice`, with predefined option keys and an optional `snippet`. The loader enforces category membership, option uniqueness and answer-key membership.
- The bank audit checked IDs against the starter packs, compared normalized stems for duplicates and close wording, counted difficulty and answer positions, and verified selected binary, mask, subnet, CIDR, /31, /32 and RFC 1918 calculations using Python. It also checked selected route, interface and MAC-table answers against the exhibits. [RFC 3021](https://www.rfc-editor.org/rfc/rfc3021.html) · [RFC 1918](https://www.rfc-editor.org/rfc/rfc1918.html)
- An isolated run imported the four starter packs and all 26 generated packs using the CLI and the TUI Feed handler. It checked that every topic was introduced, verified duplicate import rejection, submitted both new answer types, checked rendered feedback and reopened the database to verify resume. The independent pseudoterminal smoke test passed at 140×45, 110×35 and 80×24. All seven existing unit tests passed.
- Draft review replaced items with overlapping wording, including a repeated longest-prefix lookup and a case-only option collision flagged by the loader. The final validation run passed with 260 items. CLI behavior and port terminology were reviewed against public references. [Cisco IOS XE CLI guide](https://www.cisco.com/c/en/us/td/docs/routers/ios-xe/system-management/system-management/m_cf-cli-basics.html) · [IANA port registry](https://www.iana.org/assignments/service-names-port-numbers/service-names-port-numbers.xhtml) · [RFC 9293](https://www.rfc-editor.org/rfc/rfc9293.html)

## Scope and limitations

This independent practice bank follows the 26-area outline. Exhibits are authored examples and can vary by platform and release. Relative difficulty is an editorial rating, and the wording similarity check cannot establish conceptual uniqueness on its own. The choice-only interface trains recognition and interpretation. Examples of objectives outside the supplied scope include IPv6, detailed campus topology, VLAN and trunk configuration, LACP, Rapid PVST+, OSPF, wireless configuration, ACLs, device hardening and automation. [Full Cisco v1.1 blueprint](https://learningcontent.cisco.com/documents/marketing/exam-topics/200-301-CCNA-v1.1.pdf)
