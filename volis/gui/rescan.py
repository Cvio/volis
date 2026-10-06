"""Rescan (P13): what is in models\\ and which audio devices exist, read again
without restarting, and said in plain words what changed.

No Qt here. The window takes a `Snapshot` before and after reading the
folders and devices again, and shows the lines `compare` and
`selection_line` return.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import models

# The kinds of thing a rescan lists, with the words used for each.
KINDS = {
    "recognizer": ("recognizer", "recognizers"),
    "translator": ("translator", "translators"),
    "voice": ("voice", "voices"),
    "microphone": ("microphone", "microphones"),
    "speakers": ("speakers", "speakers"),
}


@dataclass(frozen=True)
class Item:
    id: str  # what the settings store: a folder name, a translator id, a device name
    name: str  # what the window shows
    usable: bool = True
    reason: str = ""  # why not, as --report says it


Snapshot = dict[str, list[Item]]


def engine_items(entries: list) -> list[Item]:
    """Recognizers or voices, as discovery returned them: understood folders
    and the ones that could not be read."""
    items = []
    for e in entries:
        if isinstance(e, models.Failed):
            items.append(Item(e.dir_name, e.dir_name, False, e.error))
        else:
            reason = "" if e.enabled() else (e.unusable or "missing: " + ", ".join(e.missing_files()))
            items.append(Item(e.dir_name, e.name, e.enabled(), reason))
    return items


def translator_items(entries: list) -> list[Item]:
    items = []
    for t in entries:
        if isinstance(t, models.Failed):
            items.append(Item(t.dir_name, t.dir_name, False, t.error))
        else:
            reason = "" if t.enabled() else (t.unusable or "missing: " + ", ".join(t.missing))
            items.append(Item(t.id, t.name, t.enabled(), reason))
    return items


def device_items(devices: list) -> list[Item]:
    return [Item(d.name, d.name) for d in devices]


def compare(before: Snapshot, after: Snapshot) -> list[str]:
    """What a rescan found, one plain line each: what is new, what is gone,
    what stopped working (with the reason) and what works again."""
    lines = []
    for kind, (one, _many) in KINDS.items():
        old = {i.id: i for i in before.get(kind, [])}
        new = {i.id: i for i in after.get(kind, [])}
        for item in new.values():
            if item.id not in old:
                if item.usable:
                    lines.append(f"New {one}: {item.name}.")
                else:
                    lines.append(f"New {one}, but it can't be used: {item.name} ({item.reason}).")
        for item in old.values():
            if item.id not in new:
                lines.append(f"No longer there: the {one} {item.name}.")
        for item in new.values():
            was = old.get(item.id)
            if was is None or was.usable == item.usable:
                continue
            if item.usable:
                lines.append(f"Works now: the {one} {item.name}.")
            else:
                lines.append(f"Can't be used any more: the {one} {item.name} ({item.reason}).")
    return lines


def selection_line(kind: str, was: str, now: str, why: str = "", running: bool = False) -> str:
    """The line for a choice the rescan had to change: the chosen model or
    device is gone, and this is what is chosen in its place."""
    one = KINDS[kind][0]
    line = f"The {one} you had chosen ({was}) {'are' if kind == 'speakers' else 'is'} gone"
    line += (f"; now using {now}" + (f" ({why})" if why else "") + ".") if now else "; nothing else can take its place."
    if running:
        line += " The conversation that is running keeps what it loaded; the change applies at the next Start."
    return line


def first_usable(items: list[Item], prefer: str = "") -> str:
    """The id to fall back to when a translator's choice is gone: `prefer`
    if it is there and works, else the first that works, else ""."""
    usable = [i.id for i in items if i.usable]
    return prefer if prefer in usable else (usable[0] if usable else "")
