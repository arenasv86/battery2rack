"""Build Ableton Live Drum Racks (.adg) from Battery kits.

An .adg file is gzip-compressed XML. Templates are read from the user's own
Live installation (Core Library):
  - Defaults/Slicing/Default.adg            -> a Drum Rack with a single pad
  - Defaults/Instruments/<Device>.adv       -> the instrument with factory defaults
  - a factory Drum Rack with Simpler pads   -> a MultiSamplePart (Simpler/Sampler)
Each Battery cell becomes one pad (DrumBranchPreset).
"""
from __future__ import annotations

import copy
import glob
import gzip
import math
import os
import xml.etree.ElementTree as ET

from .nbkt import Cell, Kit, Zone

RACK_TEMPLATE = "Defaults/Slicing/Default.adg"
PART_TEMPLATES = ["Racks/Drum Racks/Sampled/Coral Kit.adg", "Racks/Drum Racks/**/*.adg"]

# device key -> (label, .adv preset, XML tag)
DEVICES = {
    "drum-sampler": ("Drum Sampler", "Defaults/Instruments/Drum Sampler.adv", "DrumCell"),
    "simpler": ("Simpler", "Defaults/Instruments/Simpler.adv", "OriginalSimpler"),
    "sampler": ("Sampler", "Defaults/Instruments/Sampler.adv", "MultiSampler"),
}
DEFAULT_DEVICE = "drum-sampler"

# Battery leaves cells at -0.1 dB and whole kits clip (even at -6 dB): every pad
# starts at -12 dB and gets balanced by hand.
DEFAULT_VOLUME_DB = -12.0


def _load(path: str) -> ET.ElementTree:
    with gzip.open(path) as f:
        return ET.parse(f)


def _set(el: ET.Element, path: str, value) -> None:
    node = el.find(path)
    if node is None:
        raise KeyError(path)
    if isinstance(value, bool):
        value = "true" if value else "false"
    node.set("Value", str(value))


def _param(el: ET.Element, name: str, value) -> None:
    _set(el, f"{name}/Manual", value)


def _param_clamped(el: ET.Element, name: str, value: float) -> None:
    rng = el.find(f"{name}/MidiControllerRange")
    if rng is not None:
        value = max(float(rng.find("Min").get("Value")), min(float(rng.find("Max").get("Value")), value))
    _param(el, name, round(value, 4))


def _clear(el: ET.Element | None) -> None:
    if el is not None:
        for c in list(el):
            el.remove(c)


def _default_preset_ref(device_id: str) -> ET.Element:
    """Reference to a device's default preset; Live requires it on every pad."""
    ref = ET.Element("AbletonDefaultPresetRef", Id="0")
    fr = ET.SubElement(ref, "FileRef")
    for tag, val in (("RelativePathType", 0), ("RelativePath", ""), ("Path", ""), ("Type", 2),
                     ("LivePackName", ""), ("LivePackId", ""), ("OriginalFileSize", 0),
                     ("OriginalCrc", 0), ("SourceHint", "")):
        ET.SubElement(fr, tag, Value=str(val))
    ET.SubElement(ref, "DeviceId", Name=device_id)
    return ref


def _file_ref(fr: ET.Element, path: str) -> None:
    exists = os.path.exists(path)
    for tag, val in (("RelativePathType", 0), ("RelativePath", ""), ("Path", path), ("Type", 1),
                     ("LivePackName", ""), ("LivePackId", ""),
                     ("OriginalFileSize", os.path.getsize(path) if exists else 0),
                     ("OriginalCrc", 0), ("SourceHint", "")):
        node = fr.find(tag)
        if node is None:
            node = ET.SubElement(fr, tag)
        node.set("Value", str(val))


def _sample_ref(zone: Zone, path: str) -> ET.Element:
    ref = ET.Element("SampleRef", Id="0")
    _file_ref(ET.SubElement(ref, "FileRef"), path)
    mtime = int(os.path.getmtime(path)) if os.path.exists(path) else 0
    ET.SubElement(ref, "LastModDate", Value=str(mtime))
    ET.SubElement(ref, "SourceContext")
    for tag, val in (("SampleUsageHint", 0), ("DefaultDuration", zone.frames),
                     ("DefaultSampleRate", zone.sample_rate), ("SamplesToAutoWarp", 1)):
        ET.SubElement(ref, tag, Value=str(val))
    return ref


def _part_template(core: str) -> ET.Element:
    """A MultiSamplePart with a sample loaded, taken from a factory Drum Rack."""
    xpath = ".//Player/MultiSampleMap/SampleParts/MultiSamplePart"
    for pattern in PART_TEMPLATES:
        for f in sorted(glob.glob(os.path.join(core, pattern), recursive=True)):
            try:
                part = _load(f).getroot().find(xpath)
            except (OSError, ET.ParseError):
                continue
            if part is not None:
                return part
    raise FileNotFoundError("No factory Drum Rack with a Simpler pad found in Live's Core Library")


def _sample_part(template: ET.Element, name: str, zone: Zone, path: str) -> ET.Element:
    part = copy.deepcopy(template)
    _set(part, "Name", name)
    for rng, (lo, hi) in (("KeyRange", (0, 127)), ("VelocityRange", (1, 127))):
        _set(part, f"{rng}/Min", lo); _set(part, f"{rng}/Max", hi)
        _set(part, f"{rng}/CrossfadeMin", lo); _set(part, f"{rng}/CrossfadeMax", hi)
    _set(part, "RootKey", 60)  # the pad sends C3 (60): plays at original pitch
    _set(part, "Detune", 0)
    _set(part, "Panorama", 0)
    _set(part, "Volume", 1)
    end = max(zone.frames - 1, 0)
    start = zone.start if zone.start < end else 0
    _set(part, "SampleStart", start)
    _set(part, "SampleEnd", end)
    for loop in ("SustainLoop", "ReleaseLoop"):
        _set(part, f"{loop}/Start", start)
        _set(part, f"{loop}/End", end)
    # Edit the template's SampleRef in place: it differs slightly from the Drum Sampler one.
    ref = part.find("SampleRef")
    _file_ref(ref.find("FileRef"), path)
    _set(ref, "LastModDate", int(os.path.getmtime(path)) if os.path.exists(path) else 0)
    _clear(ref.find("SourceContext"))
    _set(ref, "DefaultDuration", zone.frames)
    _set(ref, "DefaultSampleRate", zone.sample_rate)
    _clear(part.find("SlicePoints"))
    return part


def _tune(cell: Cell) -> tuple[int, float]:
    """Battery stores tune as a pitch ratio: return (semitones, fraction of a semitone)."""
    semis = 12 * math.log2(cell.tune) if cell.tune > 0 else 0.0
    coarse = max(-48, min(48, round(semis)))
    return coarse, semis - coarse


def _setup_drum_sampler(dev: ET.Element, cell: Cell, zone: Zone, path: str, volume_db: float, _part) -> None:
    user_sample = dev.find("UserSample/Value")
    _clear(user_sample)
    user_sample.append(_sample_ref(zone, path))
    coarse, fine = _tune(cell)
    _param(dev, "Voice_Transpose", coarse)
    _param_clamped(dev, "Voice_Detune", fine)  # in semitones (-0.5..0.5)
    _param_clamped(dev, "Volume", volume_db)
    _param_clamped(dev, "Pan", cell.pan)
    if zone.frames and 0 < zone.start < zone.frames:
        _param(dev, "Voice_PlaybackStart", round(zone.start / zone.frames, 6))
    # Play the whole sample, like Battery: hold = sample length.
    seconds = zone.frames / zone.sample_rate if zone.sample_rate else 60.0
    _param_clamped(dev, "Voice_Envelope_Hold", seconds + 0.05)
    _param(dev, "Effect_On", False)


def _setup_multisample(dev: ET.Element, cell: Cell, zone: Zone, path: str, volume_db: float, part) -> None:
    """Simpler and Sampler share the same Player/VolumeAndPan/Pitch layout."""
    parts = dev.find("Player/MultiSampleMap/SampleParts")
    _clear(parts)
    parts.append(part)
    coarse, fine = _tune(cell)
    _param(dev, "Pitch/TransposeKey", coarse)
    _param_clamped(dev, "Pitch/TransposeFine", fine * 100)  # in cents
    _param_clamped(dev, "VolumeAndPan/Volume", volume_db)
    _param_clamped(dev, "VolumeAndPan/Panorama", cell.pan)
    if dev.tag == "OriginalSimpler":
        _set(dev, "Globals/PlaybackMode", 1)  # One-Shot: plays the whole sample
    else:
        # Sampler has no one-shot mode: a long release keeps short notes from cutting the sample.
        seconds = zone.frames / zone.sample_rate if zone.sample_rate else 60.0
        _param_clamped(dev, "VolumeAndPan/Envelope/ReleaseTime", seconds * 1000)


def build_rack(kit: Kit, core: str, device: str = DEFAULT_DEVICE, choke: bool = False,
               volume_db: float = DEFAULT_VOLUME_DB) -> ET.ElementTree:
    """Build the Drum Rack. `core` is Live's Core Library folder (see live.py)."""
    if device not in DEVICES:
        raise ValueError(f"Unknown device '{device}'. Options: {', '.join(DEVICES)}")
    label, adv, tag = DEVICES[device]
    adv_path = os.path.join(core, adv)
    if not os.path.exists(adv_path):
        raise FileNotFoundError(f"{label} is not available in this Live installation ({adv_path})")

    tree = _load(os.path.join(core, RACK_TEMPLATE))
    gp = tree.getroot().find("GroupDevicePreset")
    branches = gp.find("BranchPresets")
    pad_template = branches.find("DrumBranchPreset")
    branches.remove(pad_template)

    # Replace the template's instrument with the chosen one, at factory defaults.
    instrument = _load(adv_path).getroot().find(f".//{tag}")
    instrument.set("Id", "0")  # .adv presets lack it and Live won't load the pad without it
    _clear(instrument.find("LastPresetRef/Value"))
    dev_preset = pad_template.find("DevicePresets/AbletonDevicePreset")
    _clear(dev_preset.find("Device"))
    dev_preset.find("Device").append(instrument)
    preset_ref = dev_preset.find("PresetRef")
    _clear(preset_ref)
    preset_ref.append(_default_preset_ref(tag))

    # Rack: name, empty and hidden macros, no macro variations (scenes).
    rack = gp.find("Device/DrumGroupDevice")
    _set(rack, "UserName", kit.name)
    for i in range(16):
        _set(rack, f"MacroDisplayNames.{i}", f"Macro {i + 1}")
        _set(rack, f"MacroDefaults.{i}", 0)
        _param(rack, f"MacroControls.{i}", 0)
    _clear(rack.find("MacroVariations/MacroSnapshots"))
    _set(rack, "AreMacroControlsVisible", False)
    _set(rack, "AreMacroVariationsControlsVisible", False)
    # No Auto Select: otherwise, during playback, every pad that sounds steals
    # the selection from the pad you are editing.
    _set(rack, "IsAutoSelectEnabled", False)
    _clear(rack.find("LastPresetRef/Value"))
    _clear(gp.find("PresetRef"))

    setup = _setup_drum_sampler if device == "drum-sampler" else _setup_multisample
    part_template = None if device == "drum-sampler" else _part_template(core)

    used = sorted((c for c in kit.cells if c.zones), key=lambda c: c.zones[0].pad_note)
    seen_notes: set[int] = set()
    for n, cell in enumerate(used):
        zone = cell.zones[0]
        note = zone.pad_note
        if note in seen_notes:  # Drum Rack can't hold two pads on the same note
            continue
        seen_notes.add(note)

        path = kit.resolve(zone.sample)
        name = cell.name.strip() or os.path.splitext(os.path.basename(path))[0]
        pad = copy.deepcopy(pad_template)
        pad.set("Id", str(n))
        _set(pad, "Name", name)
        _set(pad, "ZoneSettings/ReceivingNote", 128 - note)
        _set(pad, "ZoneSettings/SendingNote", 60)
        # Unconfirmed whether this field is the choke group or the output bus: opt-in only.
        group = 0 if not choke or cell.choke < 0 else min(cell.choke + 1, 16)
        _set(pad, "ZoneSettings/ChokeGroup", group)

        part = _sample_part(part_template, name, zone, path) if part_template is not None else None
        setup(pad.find(f".//{tag}"), cell, zone, path, volume_db, part)
        branches.append(pad)
    return tree


def write_adg(tree: ET.ElementTree, out_path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    data = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(tree.getroot(), encoding="utf-8")
    with gzip.open(out_path, "wb") as f:
        f.write(data)
