"""
suggest_rings.py
================
Propose rings for insert magnets that have none (PLAN_insert_rings.md).

Each gap between consecutive helices (a *slot*) gets a ring from the ring
JSON files when one fits and the sharing rule allows it, otherwise a
placeholder ring. As few placeholders as possible are created.

  fit       every radius within ±tolerance of helix i's ``r`` followed by
            helix i+1's ``r``, and the same drawing number (revision letter
            ignored) as the closest ``Ring-*.yaml``
  sharing   a ring never goes to two magnets whose lifetimes overlap;
            lifetime = assembled_at → first retired/dead event, an end equal
            to the next start is a handover and is allowed
  excluded  rings held by EXCLUDED_HOLDERS are never used

Without ``--write`` only a report is printed. With ``--write`` the chosen
rings are inserted after the last helix of each target magnet JSON, and the
placeholder ring files are created, named ``R<YYMMDD><NN>.json`` with today's
date like the other ring files and marked "IA guessed" in their description.
The database is never written.

Usage
-----
    python suggest_rings.py --db ../magnetdb-scratch --json-dir ../../hifimagnet-projects/magnetdb.json
    python suggest_rings.py --db ../magnetdb-scratch --json-dir ../../hifimagnet-projects/magnetdb.json --write
"""

import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import date
from itertools import combinations
from pathlib import Path

import duckdb
import yaml

from config import DEFAULT_DB

EXCLUDED_HOLDERS = ("M25032101",)
DEFAULT_TOLERANCE = 0.1
FALLBACK_MATERIAL = "MA26021002"
PLACEHOLDER_DESCRIPTION = "IA guessed: placeholder ring created by suggest_rings.py, no real ring known."
_EPS = 1e-9


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Lifetime:
    """Period a magnet holds its parts.

    Attributes
    ----------
    start : datetime.date
        ``assembled_at``.
    end : datetime.date or None
        Date of the earliest ``retired``/``dead`` event; ``None`` if still held.
    dead : bool
        True if the magnet died at *end*: its parts died with it.
    """

    start: date
    end: date | None = None
    dead: bool = False

    def overlaps(self, other: "Lifetime") -> bool:
        """Return True if the two periods overlap.

        Parameters
        ----------
        other : Lifetime
            Period to compare with.

        Returns
        -------
        bool
            True when they share more than a handover day (one ends the day
            the other starts).
        """
        return self.start < (other.end or date.max) and other.start < (self.end or date.max)


@dataclass(frozen=True)
class Slot:
    """Gap between helix *index* and helix *index* + 1 of a target magnet.

    Attributes
    ----------
    magnet : str
        Target magnet name.
    index : int
        1-based rank of the first helix.
    helices : tuple of str
        Names of the two helices.
    r : tuple of float
        Required ring radii [mm]: helix i's ``r`` then helix i+1's ``r``.
    family : str
        Design family folder of helix i's geometry, e.g. ``"HL-34"``.
    """

    magnet: str
    index: int
    helices: tuple[str, str]
    r: tuple[float, ...]
    family: str

    @property
    def key(self) -> tuple[str, int]:
        """Return ``(magnet, index)``."""
        return (self.magnet, self.index)

    @property
    def label(self) -> str:
        """Return the slot name, e.g. ``"H1H2"``."""
        return f"H{self.index}H{self.index + 1}"


@dataclass
class RingInfo:
    """A ring JSON file and the magnets currently holding it.

    Attributes
    ----------
    name : str
        Ring name.
    r : tuple of float
        Radii of its geometry [mm].
    drawing : str or None
        ``design_office_reference``, else the geometry's ``cad``.
    geometry : str
        Path of its ``Ring-*.yaml``.
    data : dict
        Content of the ring JSON file.
    holders : tuple of str
        Magnets linked to it in the database.
    """

    name: str
    r: tuple[float, ...]
    drawing: str | None
    geometry: str
    data: dict = field(repr=False)
    holders: tuple[str, ...] = ()


@dataclass
class Placeholder:
    """A placeholder ring and the slots it fills.

    Attributes
    ----------
    name : str
        ``R<YYMMDD><NN>`` with the creation date, like the other ring files.
    geometry : str
        Path of the ``Ring-*.yaml`` it uses.
    cad : str or None
        Drawing reference from that yaml.
    material : dict
        Material copied from a real ring.
    slots : list of Slot
        Slots it fills, oldest magnet first.
    manufactured_at : datetime.date
        ``assembled_at`` of the first magnet it goes to.
    """

    name: str
    geometry: str
    cad: str | None
    material: dict
    slots: list[Slot]
    manufactured_at: date

    def to_json(self) -> dict:
        """Return the content of the placeholder ring JSON file.

        Returns
        -------
        dict
            Ring JSON in the format of ``magnetdb.json/R*.json``.
        """
        return {
            "name": self.name,
            "description": PLACEHOLDER_DESCRIPTION,
            "status": "in_stock",
            "type": "ring",
            "design_office_reference": self.cad or "",
            "material": self.material,
            "manufactured_at": self.manufactured_at.isoformat(),
            "geometry": self.geometry,
        }


@dataclass
class Suggestion:
    """Result of :func:`suggest`.

    Attributes
    ----------
    slots : list of Slot
        All target slots, in magnet then slot order.
    rings : dict
        Ring name → :class:`RingInfo`.
    lifetimes : dict
        Magnet name → :class:`Lifetime`.
    tolerance : float
        Radius tolerance used [mm].
    candidates : dict
        Slot key → names of all fitting rings, excluded ones included.
    chosen : dict
        Slot key → chosen ring or placeholder name; empty slots are absent.
    placeholders : list of Placeholder
        Placeholders to create.
    empty : dict
        Slot key → reason the slot gets nothing.
    excluded : dict
        Ring name → holders, for rings held by an excluded magnet.
    violations : list of tuple
        ``(ring, magnet_a, magnet_b)`` for existing overlapping holders.
    """

    slots: list[Slot]
    rings: dict[str, RingInfo]
    lifetimes: dict[str, Lifetime]
    tolerance: float
    candidates: dict[tuple[str, int], list[str]]
    chosen: dict[tuple[str, int], str]
    placeholders: list[Placeholder]
    empty: dict[tuple[str, int], str]
    excluded: dict[str, tuple[str, ...]]
    violations: list[tuple[str, str, str]]


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


class _TagLoader(yaml.SafeLoader):
    """SafeLoader that reads python_magnetgeo tags (``!<Ring>``) as plain data."""


def _construct_any(loader, _suffix, node):
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_scalar(node)


_TagLoader.add_multi_constructor("", _construct_any)


def _load_yaml(path) -> dict | None:
    """Load a geometry yaml as plain data, or None if it cannot be read."""
    try:
        with open(path) as f:
            data = yaml.load(f, Loader=_TagLoader)
    except (OSError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else None


def _radii(data: dict | None) -> tuple[float, ...] | None:
    """Return the ``r`` list of a geometry as floats, or None."""
    if not data or not isinstance(data.get("r"), list):
        return None
    return tuple(float(x) for x in data["r"])


def drawing_number(ref: str | None) -> str | None:
    """Strip the revision letter from a drawing reference.

    Parameters
    ----------
    ref : str or None
        Drawing reference, e.g. ``"HL-27-041-D"`` (also ``"HL-27-041D"``).

    Returns
    -------
    str or None
        Drawing number, e.g. ``"HL-27-041"``; None for an empty reference.
    """
    if not ref:
        return None
    return re.sub(r"-?[A-Z]$", "", ref.strip())


def max_deviation(a, b) -> float:
    """Return the largest radius difference [mm], or infinity if lengths differ."""
    if len(a) != len(b):
        return float("inf")
    return max(abs(x - y) for x, y in zip(a, b))


def load_ring_geometries(root: Path) -> dict[str, tuple[tuple[float, ...], str | None]]:
    """Read every ``Ring-*.yaml`` under *root*.

    Parameters
    ----------
    root : :class:`~pathlib.Path`
        Project directory, e.g. ``hifimagnet-projects``.

    Returns
    -------
    dict
        Absolute path → ``(r, cad)``; files without 4 radii are skipped.
    """
    geometries = {}
    for path in sorted(Path(root).resolve().glob("**/Ring-*.yaml")):
        data = _load_yaml(path)
        r = _radii(data)
        if r and len(r) == 4:
            geometries[str(path)] = (r, data.get("cad"))
    return geometries


def closest_geometries(slot_r, geometries: dict, tolerance: float) -> list[str]:
    """Return the ring geometry paths closest to *slot_r*.

    Parameters
    ----------
    slot_r : tuple of float
        Required radii [mm].
    geometries : dict
        Output of :func:`load_ring_geometries`.
    tolerance : float
        Radius tolerance [mm].

    Returns
    -------
    list of str
        Paths at the smallest maximum deviation, sorted; empty if none is
        within *tolerance*.
    """
    deviations = {path: max_deviation(r, slot_r) for path, (r, _) in geometries.items()}
    if not deviations:
        return []
    best = min(deviations.values())
    if best > tolerance + _EPS:
        return []
    return sorted(p for p, d in deviations.items() if d <= best + _EPS)


def slot_drawings(slot_r, geometries: dict, tolerance: float) -> set[str]:
    """Return the drawing numbers a slot calls for.

    Parameters
    ----------
    slot_r : tuple of float
        Required radii [mm].
    geometries : dict
        Output of :func:`load_ring_geometries`.
    tolerance : float
        Radius tolerance [mm].

    Returns
    -------
    set of str
        Drawing numbers of the closest ring geometries; empty when unknown.
    """
    paths = closest_geometries(slot_r, geometries, tolerance)
    return {drawing_number(geometries[p][1]) for p in paths if geometries[p][1]}


def ring_fits(ring_r, ring_drawing, slot_r, drawings: set[str], tolerance: float) -> bool:
    """Return True if a ring fits a slot (rule 2 of PLAN_insert_rings.md).

    Parameters
    ----------
    ring_r : tuple of float
        Ring radii [mm].
    ring_drawing : str or None
        Ring drawing reference.
    slot_r : tuple of float
        Required radii [mm].
    drawings : set of str
        Drawing numbers the slot calls for (:func:`slot_drawings`).
    tolerance : float
        Radius tolerance [mm].

    Returns
    -------
    bool
        True when every radius is within *tolerance* and the drawing numbers
        match; an unknown drawing on either side skips the drawing check.
    """
    if max_deviation(ring_r, slot_r) > tolerance + _EPS:
        return False
    number = drawing_number(ring_drawing)
    return not drawings or number is None or number in drawings


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_lifetimes(con) -> dict[str, Lifetime]:
    """Read every magnet's lifetime from the database.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open connection.

    Returns
    -------
    dict
        Magnet name → :class:`Lifetime`, for magnets with an ``assembled_at``.
        In-stock periods are part of the lifetime; it ends at the earliest
        ``retired``/``dead`` event, and ``dead`` is set if a death is logged
        on that day.
    """
    lifetimes = {}
    rows = con.execute(
        "SELECT name, assembled_at, status_history FROM magnets WHERE assembled_at IS NOT NULL"
    ).fetchall()
    for name, assembled_at, history in rows:
        ends = [
            (date.fromisoformat(str(e["date"])[:10]), e["status"])
            for e in json.loads(history or "[]")
            if e.get("status") in ("retired", "dead")
        ]
        end = min(d for d, _ in ends) if ends else None
        dead = any(d == end and s == "dead" for d, s in ends)
        lifetimes[name] = Lifetime(assembled_at.date(), end, dead)
    return lifetimes


def load_ring_holders(con) -> dict[str, list[str]]:
    """Read which magnets hold each ring.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open connection.

    Returns
    -------
    dict
        Ring name → magnet names, sorted.
    """
    holders: dict[str, list[str]] = {}
    rows = con.execute(
        "SELECT p.name, mp.magnet_name FROM magnet_parts mp JOIN parts p ON p.name = mp.part_name "
        "WHERE p.type = 'ring' ORDER BY p.name, mp.magnet_name"
    ).fetchall()
    for ring, magnet in rows:
        holders.setdefault(ring, []).append(magnet)
    return holders


def _json_has_rings(path: Path) -> bool:
    """True if the magnet JSON at *path* already lists a ring part."""
    parts = json.loads(path.read_text()).get("parts", [])
    return any(isinstance(p, dict) and p.get("type") == "ring" for p in parts)


def find_targets(con, json_dir: Path, magnet: str | None = None) -> list[str]:
    """List the insert magnets that have no rings.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open connection.
    json_dir : :class:`~pathlib.Path`
        Directory of the magnet JSON files.
    magnet : str, optional
        Restrict to this magnet.

    Returns
    -------
    list of str
        Insert magnets with an ``assembled_at`` and no ring, neither in the
        database nor in their JSON file, oldest first.
    """
    rows = con.execute(
        "SELECT m.name FROM magnets m WHERE m.type = 'insert' AND m.assembled_at IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM magnet_parts mp JOIN parts p ON p.name = mp.part_name "
        "WHERE mp.magnet_name = m.name AND p.type = 'ring') ORDER BY m.assembled_at, m.name"
    ).fetchall()
    targets = []
    for (name,) in rows:
        path = Path(json_dir) / f"{name}.json"
        if (magnet is None or name == magnet) and path.exists() and not _json_has_rings(path):
            targets.append(name)
    return targets


def target_slots(magnet_data: dict) -> list[Slot]:
    """Build the slots of a magnet from its JSON content.

    Parameters
    ----------
    magnet_data : dict
        Magnet JSON content; helix parts must carry a ``geometry`` path.

    Returns
    -------
    list of Slot
        One slot per pair of consecutive helices, in part order.
    """
    helices = [p for p in magnet_data["parts"] if isinstance(p, dict) and p.get("type") == "helix"]
    radii = [_radii(_load_yaml(p["geometry"])) for p in helices]
    return [
        Slot(
            magnet=magnet_data["name"],
            index=i + 1,
            helices=(helices[i]["name"], helices[i + 1]["name"]),
            r=radii[i] + radii[i + 1],
            family=Path(helices[i]["geometry"]).parent.name,
        )
        for i in range(len(helices) - 1)
    ]


def load_rings(json_dir: Path, holders: dict[str, list[str]]) -> dict[str, RingInfo]:
    """Read the ring JSON files.

    Parameters
    ----------
    json_dir : :class:`~pathlib.Path`
        Directory of the JSON files.
    holders : dict
        Output of :func:`load_ring_holders`.

    Returns
    -------
    dict
        Ring name → :class:`RingInfo`; rings whose geometry has no 4 radii
        are skipped.
    """
    rings = {}
    for path in sorted(Path(json_dir).glob("*.json")):
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or data.get("type") != "ring":
            continue
        geometry = _load_yaml(data.get("geometry", ""))
        r = _radii(geometry)
        if not r or len(r) != 4:
            continue
        rings[data["name"]] = RingInfo(
            name=data["name"],
            r=r,
            drawing=data.get("design_office_reference") or geometry.get("cad"),
            geometry=data["geometry"],
            data=data,
            holders=tuple(holders.get(data["name"], [])),
        )
    return rings


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------


def existing_violations(holders: dict[str, list[str]], lifetimes: dict[str, Lifetime]) -> list[tuple[str, str, str]]:
    """Find rings already held by two magnets that cannot both have held them.

    Parameters
    ----------
    holders : dict
        Ring name → magnet names.
    lifetimes : dict
        Magnet name → :class:`Lifetime`.

    Returns
    -------
    list of tuple
        ``(ring, magnet_a, magnet_b)`` for each pair whose lifetimes overlap,
        or where one magnet died before the other was assembled.
    """
    found = []
    for ring, magnets in sorted(holders.items()):
        for a, b in combinations(magnets, 2):
            if a in lifetimes and b in lifetimes and _conflict(a, [b], lifetimes):
                found.append((ring, a, b))
    return found


def _conflict(magnet: str, others, lifetimes: dict[str, Lifetime]) -> str | None:
    """Why *magnet* cannot share a ring with *others* (rules 4 and 4b), or None."""
    life = lifetimes[magnet]
    for other in others:
        if other == magnet:
            return f"overlaps {other}"
        if other not in lifetimes:
            continue
        o = lifetimes[other]
        if life.overlaps(o):
            return f"overlaps {other}"
        if o.dead and o.end <= life.start:
            return f"died in {other}"
        if life.dead and life.end <= o.start:
            return f"would die in {magnet}"
    return None


def _handover(magnet: str, others, lifetimes: dict[str, Lifetime]) -> str | None:
    """First of *others* that ends when *magnet* starts or starts when it ends."""
    life = lifetimes[magnet]
    for other in others:
        if other in lifetimes and (lifetimes[other].end == life.start or lifetimes[other].start == life.end):
            return other
    return None


def _preference(magnet: str, others, lifetimes: dict[str, Lifetime]) -> int:
    """Tie-break score (rule 6): 2 handover, 1 ring in no magnet, 0 otherwise."""
    if _handover(magnet, others, lifetimes):
        return 2
    return 0 if others else 1


def _components(slots: list[Slot], usable: dict) -> list[list[Slot]]:
    """Group slots that share a candidate ring."""
    parent = {s.key: s.key for s in slots}

    def find(k):
        while parent[k] != k:
            k = parent[k]
        return k

    by_ring: dict[str, tuple] = {}
    for s in slots:
        for name in usable[s.key]:
            if name in by_ring:
                parent[find(s.key)] = find(by_ring[name])
            else:
                by_ring[name] = s.key
    groups: dict[tuple, list[Slot]] = {}
    for s in slots:
        groups.setdefault(find(s.key), []).append(s)
    return list(groups.values())


def _assign_component(slots: list[Slot], usable: dict, rings: dict, lifetimes: dict) -> dict:
    """Exact search: most real rings, then best tie-break score, then ring names."""
    slots = sorted(slots, key=lambda s: (lifetimes[s.magnet].start, s.magnet, s.index))
    users: dict[str, list[str]] = {name: [] for s in slots for name in usable[s.key]}
    current: dict = {}
    best = {"key": (-1, -1), "assign": {}}

    def signature(name):
        ring = rings[name]
        return (ring.r, drawing_number(ring.drawing), ring.holders)

    def search(k, real, score):
        remaining = len(slots) - k
        if (real + remaining, score + 2 * remaining) <= best["key"]:
            return
        if k == len(slots):
            best["key"], best["assign"] = (real, score), dict(current)
            return
        slot = slots[k]
        seen = set()
        for name in usable[slot.key]:
            others = rings[name].holders + tuple(users[name])
            if _conflict(slot.magnet, others, lifetimes):
                continue
            if not users[name]:  # unused rings with the same signature are interchangeable
                if signature(name) in seen:
                    continue
                seen.add(signature(name))
            users[name].append(slot.magnet)
            current[slot.key] = name
            search(k + 1, real + 1, score + _preference(slot.magnet, others, lifetimes))
            users[name].pop()
            del current[slot.key]
        search(k + 1, real, score)

    search(0, 0, 0)
    return best["assign"]


def _placeholder_name(created: date, taken: set[str]) -> str:
    """Return the first free ``R<YYMMDD><NN>`` for the *created* date."""
    stem = f"R{created:%y%m%d}"
    n = 1
    while f"{stem}{n:02d}" in taken:
        n += 1
    return f"{stem}{n:02d}"


def _placeholder_material(cad: str | None, rings: dict[str, RingInfo]) -> dict:
    """Material of a real ring with the same drawing, else the fallback material."""
    number = drawing_number(cad)
    ordered = sorted(rings.values(), key=lambda r: r.name)
    for ring in ordered:
        if number and drawing_number(ring.drawing) == number and ring.data.get("material"):
            return ring.data["material"]
    for ring in ordered:
        material = ring.data.get("material")
        if isinstance(material, dict) and material.get("name") == FALLBACK_MATERIAL:
            return material
    return {"name": FALLBACK_MATERIAL}


def _plan_placeholders(uncovered, rings, geometries, lifetimes, tolerance, taken, created):
    """Share placeholders per geometry class, oldest magnet first (rule 5.2)."""
    classes: dict[tuple, list[Slot]] = {}
    for s in sorted(uncovered, key=lambda s: (lifetimes[s.magnet].start, s.magnet, s.index)):
        classes.setdefault(tuple(round(x, 3) for x in s.r), []).append(s)
    placeholders, empty = [], {}
    for r, members in classes.items():
        paths = closest_geometries(r, geometries, tolerance)
        if not paths:
            for s in members:
                empty[s.key] = f"no ring geometry file within ±{tolerance} mm"
            continue
        same_family = [p for p in paths if Path(p).parent.name == members[0].family]
        geometry = (same_family or paths)[0]
        cad = geometries[geometry][1]
        material = _placeholder_material(cad, rings)
        group: list[Placeholder] = []
        for s in members:
            for ph in group:
                if not _conflict(s.magnet, [o.magnet for o in ph.slots], lifetimes):
                    ph.slots.append(s)
                    break
            else:
                name = _placeholder_name(created, taken)
                taken.add(name)
                group.append(Placeholder(name, geometry, cad, material, [s], lifetimes[s.magnet].start))
        placeholders.extend(group)
    return placeholders, empty


def suggest(
    slots: list[Slot],
    rings: dict[str, RingInfo],
    geometries: dict,
    lifetimes: dict[str, Lifetime],
    tolerance: float = DEFAULT_TOLERANCE,
    excluded_holders=EXCLUDED_HOLDERS,
    existing_names=(),
    created: date | None = None,
) -> Suggestion:
    """Choose a ring or placeholder for every slot.

    Parameters
    ----------
    slots : list of Slot
        Target slots (:func:`target_slots`).
    rings : dict
        Ring name → :class:`RingInfo` (:func:`load_rings`).
    geometries : dict
        Ring geometries (:func:`load_ring_geometries`).
    lifetimes : dict
        Magnet name → :class:`Lifetime`; must cover every target.
    tolerance : float, optional
        Radius tolerance [mm].
    excluded_holders : iterable of str, optional
        Magnets whose rings are never used.
    existing_names : iterable of str, optional
        Names already taken (existing JSON files).
    created : datetime.date, optional
        Date coded in the placeholder names; defaults to today.

    Returns
    -------
    Suggestion
        Chosen rings, placeholders and everything the report needs.
    """
    excluded_holders = set(excluded_holders)
    excluded = {n: r.holders for n, r in rings.items() if excluded_holders & set(r.holders)}
    candidates = {}
    for slot in slots:
        drawings = slot_drawings(slot.r, geometries, tolerance)
        candidates[slot.key] = sorted(
            n for n, r in rings.items() if ring_fits(r.r, r.drawing, slot.r, drawings, tolerance)
        )
    usable = {k: [n for n in names if n not in excluded] for k, names in candidates.items()}

    chosen: dict = {}
    for component in _components(slots, usable):
        chosen.update(_assign_component(component, usable, rings, lifetimes))

    uncovered = [s for s in slots if s.key not in chosen]
    placeholders, empty = _plan_placeholders(
        uncovered, rings, geometries, lifetimes, tolerance, set(existing_names), created or date.today()
    )
    for ph in placeholders:
        for s in ph.slots:
            chosen[s.key] = ph.name

    holders = {n: list(r.holders) for n, r in rings.items() if len(r.holders) > 1}
    return Suggestion(
        slots=slots,
        rings=rings,
        lifetimes=lifetimes,
        tolerance=tolerance,
        candidates=candidates,
        chosen=chosen,
        placeholders=placeholders,
        empty=empty,
        excluded=excluded,
        violations=existing_violations(holders, lifetimes),
    )


# ---------------------------------------------------------------------------
# Report and write
# ---------------------------------------------------------------------------


def format_report(s: Suggestion) -> str:
    """Render a suggestion as text.

    Parameters
    ----------
    s : Suggestion
        Output of :func:`suggest`.

    Returns
    -------
    str
        Per-slot choice and alternatives (each ring shown with the magnets
        holding it, e.g. ``R26021010 [M19071101]``), placeholders, excluded
        rings, existing violations and a summary.
    """

    def tag(name):
        return f"{name} [{', '.join(s.rings[name].holders) or '-'}]"

    users: dict[str, list[Slot]] = {}
    for slot in s.slots:
        if slot.key in s.chosen:
            users.setdefault(s.chosen[slot.key], []).append(slot)
    placeholder_names = {p.name for p in s.placeholders}
    magnets = list(dict.fromkeys(slot.magnet for slot in s.slots))

    lines = [f"Ring suggestions: {len(magnets)} target magnet(s), {len(s.slots)} slot(s), tolerance ±{s.tolerance} mm"]
    if s.excluded:
        lines.append("Excluded rings (never used): " + ", ".join(tag(n) for n in sorted(s.excluded)))

    current = None
    for slot in s.slots:
        if slot.magnet != current:
            current = slot.magnet
            life = s.lifetimes[slot.magnet]
            lines += ["", f"== {slot.magnet}  ({life.start} → {life.end or 'now'})"]
        name = s.chosen.get(slot.key)
        if name is None:
            choice = f"EMPTY: {s.empty.get(slot.key, 'no ring')}"
        elif name in placeholder_names:
            choice = f"{name} (placeholder: no usable real ring)"
        else:
            ring = s.rings[name]
            handover = _handover(slot.magnet, ring.holders, s.lifetimes)
            if handover:
                why = f"handover with {handover}"
            elif not ring.holders:
                why = "ring in no magnet"
            else:
                why = f"no overlap with {', '.join(ring.holders)}"
            choice = f"{tag(name)}  ({why})"
        lines.append(f"  {slot.label:<7} {slot.helices[0]}/{slot.helices[1]}  →  {choice}")

        alternatives = []
        for other in s.candidates[slot.key]:
            if other == name:
                continue
            ring = s.rings[other]
            blocker = _conflict(slot.magnet, ring.holders, s.lifetimes)
            given = [u for u in users.get(other, []) if _conflict(slot.magnet, [u.magnet], s.lifetimes)]
            if other in s.excluded:
                why = f"excluded (held by {', '.join(ring.holders)})"
            elif blocker:
                why = blocker
            elif given:
                why = f"given to {given[0].magnet} {given[0].label}"
            else:
                why = "not chosen (tie-break)"
            alternatives.append(f"{tag(other)} {why}")
        if alternatives:
            lines.append("            alternatives: " + "; ".join(alternatives))

    lines += ["", f"Placeholders ({len(s.placeholders)}):"]
    for ph in s.placeholders:
        lines.append(
            f"  {ph.name}  geometry {ph.geometry}  drawing {ph.cad or '-'}  "
            f"material {ph.material.get('name')}  manufactured_at {ph.manufactured_at}"
        )
        lines.append("      fills: " + ", ".join(f"{x.magnet} {x.label}" for x in ph.slots))

    lines += ["", "Existing rule violations:"]
    lines += [f"  {ring}: {a} and {b} overlap" for ring, a, b in s.violations] or ["  none"]

    real = sum(1 for n in s.chosen.values() if n not in placeholder_names)
    filled = sum(len(p.slots) for p in s.placeholders)
    lines += [
        "",
        f"Summary: {real} slot(s) with a real ring, {len(s.placeholders)} placeholder(s) "
        f"over {filled} slot(s), {len(s.slots) - len(s.chosen)} empty slot(s).",
    ]
    return "\n".join(lines)


def write_suggestion(s: Suggestion, json_dir: Path) -> list[Path]:
    """Insert the chosen rings into the magnet JSON files and create placeholders.

    Parameters
    ----------
    s : Suggestion
        Output of :func:`suggest`.
    json_dir : :class:`~pathlib.Path`
        Directory of the JSON files.

    Returns
    -------
    list of :class:`~pathlib.Path`
        Files written. Rings go right after the last helix, in slot order;
        an existing placeholder file is never overwritten.
    """
    json_dir = Path(json_dir)
    placeholders = {p.name: p for p in s.placeholders}
    by_magnet: dict[str, list[Slot]] = {}
    for slot in s.slots:
        if slot.key in s.chosen:
            by_magnet.setdefault(slot.magnet, []).append(slot)

    written = []
    for magnet, slots in by_magnet.items():
        path = json_dir / f"{magnet}.json"
        text = path.read_text()
        data = json.loads(text)
        parts = data["parts"]
        last = max(i for i, p in enumerate(parts) if isinstance(p, dict) and p.get("type") == "helix")
        new = []
        for slot in sorted(slots, key=lambda x: x.index):
            name = s.chosen[slot.key]
            new.append(placeholders[name].to_json() if name in placeholders else s.rings[name].data)
        parts[last + 1:last + 1] = new
        path.write_text(json.dumps(data, indent=4, ensure_ascii=False) + ("\n" if text.endswith("\n") else ""))
        written.append(path)

    for ph in s.placeholders:
        path = json_dir / f"{ph.name}.json"
        if not path.exists():
            path.write_text(json.dumps(ph.to_json(), indent=4, ensure_ascii=False) + "\n")
            written.append(path)
    return written


def main(argv=None) -> int:
    """Run the CLI.

    Parameters
    ----------
    argv : list of str, optional
        Arguments; defaults to ``sys.argv[1:]``.

    Returns
    -------
    int
        Exit code, 0 on success.
    """
    parser = argparse.ArgumentParser(
        description=__doc__.split("Usage")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db", default=DEFAULT_DB, help="DuckDB file path (read only)")
    parser.add_argument("--json-dir", required=True,
                        help="magnetdb.json directory; its parent is searched for Ring-*.yaml")
    parser.add_argument("--magnet", default=None, help="Only this target magnet")
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE, help="Radius tolerance [mm]")
    parser.add_argument("--write", action="store_true",
                        help="Insert the rings into the magnet JSON files and create the placeholder ring files")
    args = parser.parse_args(argv)

    json_dir = Path(args.json_dir).resolve()
    con = duckdb.connect(args.db, read_only=True)
    try:
        lifetimes = load_lifetimes(con)
        holders = load_ring_holders(con)
        targets = find_targets(con, json_dir, args.magnet)
    finally:
        con.close()
    if not targets:
        print("Nothing to do: no target magnet (insert magnet without rings in the database and its JSON).")
        return 0

    slots = [s for t in targets for s in target_slots(json.loads((json_dir / f"{t}.json").read_text()))]
    rings = load_rings(json_dir, holders)
    geometries = load_ring_geometries(json_dir.parent)
    existing = {p.stem for p in json_dir.glob("*.json")}
    s = suggest(slots, rings, geometries, lifetimes, args.tolerance, EXCLUDED_HOLDERS, existing)
    print(format_report(s))
    if args.write:
        for path in write_suggestion(s, json_dir):
            print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
