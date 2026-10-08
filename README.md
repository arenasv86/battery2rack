# battery2rack

Convert **Native Instruments Battery 4** kits (`.nbkt`) into **Ableton Live Drum Racks** (`.adg`).

Each Battery cell becomes a Drum Rack pad with the same name, sample, note, tuning and pan, played by **Drum Sampler** (default), **Simpler** or **Sampler**. Batch-convert a whole folder of kits in seconds with one command.

## Install

You need Python 3.9+ (already on macOS) and Ableton Live 12 (12.1+ for Drum Sampler).

```bash
pipx install git+https://github.com/arenasv86/battery2rack
```

No `pipx`? `pip3 install --user git+https://github.com/arenasv86/battery2rack` works too. No other dependencies.

## Use

Point it at a kit or a folder of kits (tip: type `battery2rack ` and drag the folder from Finder onto the terminal):

```bash
battery2rack "/Users/Shared/Lone Forest Library"                 # Drum Sampler, -12 dB
battery2rack ~/Kits -o ~/Desktop/Racks --device simpler --volume -9
```

| Option | Default | |
|---|---|---|
| `-o, --output` | `User Library/Presets/Instruments/Drum Rack/Battery Kits` | Output folder (they show up in Live's browser) |
| `-d, --device` | `drum-sampler` | `drum-sampler`, `simpler` or `sampler` |
| `--volume` | `-12` | Volume of every pad, in dB |
| `--live` | auto-detected | Ableton Live location, if it isn't found |
| `--choke` | off | Map Battery's cell group to Choke Group (experimental) |

Folders are searched recursively. Native Instruments expansions install their kits in `/Users/Shared/<Name> Library/Sounds/Battery Kits` on macOS.

### Windows

Install Python from [python.org](https://www.python.org/downloads/) (tick *Add python.exe to PATH*), then `pip install pipx` and the same `pipx install` line. Paths with spaces go in quotes:

```bat
battery2rack "C:\Users\Public\Documents\Native Instruments" --volume -12
```

Live is found in `C:\ProgramData\Ableton\Live …`; the racks go to `Documents\Ableton\User Library\Presets\Instruments\Drum Rack\Battery Kits`.

## What gets converted

| Battery cell | Drum Rack pad |
|---|---|
| Name | Pad name |
| Sample and sample start | Sample and start of the instrument |
| Cell key | Pad note |
| Tune | Transpose + detune |
| Pan | Pan |

- **Volume**: every pad starts at **−12 dB**. Battery leaves cells at −0.1 dB and a full kit clips, so you balance by ear afterwards.
- **Whole samples**: Drum Sampler's hold matches the sample length, Simpler runs in One-Shot mode, and Sampler gets a release as long as the sample, so short MIDI notes never cut a hit.
- **Clean racks**: the Drum Sampler effect is off, macros are empty and hidden, there are no macro variations, and **Auto Select** is off (otherwise, during playback, each pad that sounds steals the selection from the one you are editing). All pads use the same output.
- Samples are referenced where they are (not copied).

### Not yet

- Battery's envelopes, filters, effects, modulation and buses.
- Choke groups: there is a per-cell group field that could be the choke group or the output bus, so it is only applied with `--choke`.
- Melodic cells spanning many keys (e.g. 51–127) become a single pad, so you can't play them chromatically.
- Two cells on the same note (Drum Rack allows only one pad per note: the first is kept).

Tested with 498 kits from Native Instruments expansions on macOS with Live 12.4. Windows support (Live detection, paths, file names) is in place but hasn't been tested on a real Windows machine yet: reports welcome.

## How it works

Ableton's presets are not included. The tool reads the factory presets of **your own Live installation** (`Core Library/Defaults`) and uses them as templates, so the racks always match your Live version.

### The `.nbkt` format (reverse engineered)

1. **Container**: the Native Instruments `hsin`/`DSIN` container also used by Kontakt 5+. Battery 4 runs on the Kontakt engine (the header says `KontaktInstrument`).
2. **Payload compressed with FastLZ level 2**: `[u32 decompressed size][u32 compressed size][data]`. The decompressed stream starts by repeating its own size.
3. **Inside the decompressed payload** (~680 KB):
   - **128 cells** (8×16 grid) with a fixed layout.
     - Each cell has a marker `ffffffff 00000100 00000000 00000000 ffffffff`, followed by `[u32 block length][u32 name length][UTF-16 name]`.
     - Right after the name come `f32 volume` (linear gain), `f32 pan` (−1..1) and `f32 tune` (pitch ratio). An `i32 group` sits at `+0x16`.
     - The cell's key range comes *before* the marker.
   - **Kontakt-style zones**.
     - Layout: `[u32 index][u32 length 0x4c|0x52][u32 sample start][u32][ffffffff][u16 vel_lo, vel_hi, key_lo, key_hi]…[u16 root][f32×3]…[u32 sample index][u32 bytes/sample][u32 sample rate][u8 channels][u32 frames]`.
     - Newer kits (length `0x52`) have 6 extra bytes before the sample index.
     - The owning cell comes right before the zone, as a `u32` followed by `01 98|9a 00 53|57 000000 ffffffff`.
   - **File pool**: `[u32 n]` and n segmented paths relative to the `.nbkt`. Segment types are `02` folder, `03` `..` and `04` file, each a length-prefixed UTF-16 string.

Prior work on the container: [ni-file](https://github.com/gitter-badger/ni-file) and [lz77](https://lib.rs/crates/lz77).

## License

MIT. Battery and Native Instruments are trademarks of Native Instruments GmbH; Ableton and Live are trademarks of Ableton AG. This project is not affiliated with either.
