# openfinger

A production-tested Python fingerprint enrollment & identification toolkit
for **DigitalPersona U.are.U** readers (4500, 5100, 5300).

Ships with everything you need to go from a fresh Windows machine + a
plugged-in reader to a working 1:N fingerprint identification system:

* **Capture bridge** — a small .NET exe that streams scans from the reader as
  JSON events over a named pipe or stdout.
* **Image pipeline** — grayscale → CLAHE → Gabor enhancement → quality gating.
* **Two matcher backends** — NIST NBIS (bozorth3, biometric-grade) and a
  from-scratch edge-based BFS matcher inspired by SourceAFIS.
* **Adaptive decision layer** — three-tier thresholding with gap-to-runner-up
  guards to keep the false-accept rate low even with a noisy sensor.

No cloud APIs. No accounts. No telemetry. Pure Python + a Windows exe you
can inspect and rebuild in one command.

---

## Why does this exist?

Fingerprint SDKs are usually either
1. locked behind vendor accounts (Neurotechnology, Innovatrics, HID),
2. web-service APIs with per-scan pricing,
3. or reference implementations that assume you already have a matcher.

If all you have is a **~$70 U.are.U 4500 off eBay** and you want a
self-hosted "verify this finger against 200 enrolled people" library, none
of the above are great. This repo is the pipeline I built while shipping an
attendance system on that exact hardware, extracted and cleaned up so anyone
else can start where I left off.

Two things that were surprisingly hard and are already done here:

* **The DPFP → Python bridge.** The U.are.U 4500 is *not* a Windows
  Biometric Framework device, so it can't be driven by `winbio`. The DPFP
  managed SDK is the only route, and it's a .NET-only API. `bridge/` has a
  tiny C# exe (~200 LOC) that turns capture events into a JSON stream any
  language can read.
* **The scoring logic.** Naive minutiae matchers score sparse probes at 80%
  against dense galleries — false accept rate near 100%. The homebrew
  matcher in `pipeline/minutiae.py` uses rotation-invariant edge triples
  and BFS propagation to reject impostors while still catching genuine
  matches from partial finger presses. There's a longer explanation
  further down.

---

## Hardware supported

| Reader                     | Status  | Notes |
|----------------------------|---------|-------|
| DigitalPersona U.are.U 4500 | ✅ Primary | Development / test target |
| DigitalPersona U.are.U 5100 | ✅ Same SDK | Should work unchanged |
| DigitalPersona U.are.U 5300 | ✅ Same SDK | Should work unchanged |
| HID DigitalPersona 4500 USB | ✅ | Rebrand of U.are.U 4500 |
| Anything WBF-compatible     | ⚠️ | Replace the bridge with a `winbio` wrapper — pipeline is unchanged |
| libfprint-supported readers | ⚠️ | Replace the bridge with a `libfprint` wrapper |

The pipeline itself is reader-agnostic. Only `bridge/FingerprintBridge.cs`
and `scanner/bridge_client.py` are Windows/DPFP-specific.

---

## Quick start

### 1. Prerequisites

* Windows 10 or 11 (for the reader capture bridge).
* Python 3.10+.
* A DigitalPersona U.are.U 4500 (or compatible) reader.
* The DigitalPersona driver installed. See [`bridge/README.md`](bridge/README.md)
  for the download link and setup steps.

### 2. Install

```powershell
git clone https://github.com/Tresorbana/Openfinger.git
cd openfinger
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Confirm the reader works

```powershell
python -m scanner.bridge_client
```

Place your finger on the reader three times. You should see:

```
Place your finger on the reader. Capturing 3 scans...
  saved capture_0.png (11274 bytes)
  saved capture_1.png (11311 bytes)
  saved capture_2.png (11348 bytes)
Done.
```

If nothing happens, jump to the [troubleshooting](#troubleshooting) section.

### 4. Enroll and identify

```powershell
# Enroll Alice (5 scans, live capture)
python examples/enroll_cli.py alice --live --count 5

# Enroll Bob
python examples/enroll_cli.py bob --live --count 5

# Identify — is this Alice or Bob?
python examples/identify_cli.py --live
```

Output on a genuine match:

```
Result:  matched=True
         flag=confirmed
         person_id=alice
         confidence_score=87.42
         second_score=6.10
         probe_clarity=0.78
```

That's it. You now have a working 1:N fingerprint system on your desk.

---

## Using it as a library

```python
from pipeline import enroll, identify

# ── Enrollment ────────────────────────────────────────────────────────
scans = [open(f"scan_{i}.png", "rb").read() for i in range(5)]
result = enroll(scans)
template_bytes = result["template_bytes"]
raw_templates  = result["raw_templates"]  # list[bytes], one per accepted scan

# Persist however you like — pickle, database blob, S3, etc.
with open("gallery/alice.pkl", "wb") as f:
    import pickle
    pickle.dump(("alice", template_bytes, raw_templates), f)

# ── Identification (1:N) ──────────────────────────────────────────────
import pickle
gallery = []
for person_id in ["alice", "bob"]:
    pid, comp, raws = pickle.load(open(f"gallery/{person_id}.pkl", "rb"))
    gallery.append((pid, pickle.loads(comp), [pickle.loads(r) for r in raws]))

probe = open("probe.png", "rb").read()
result = identify(probe, gallery)

if result["matched"]:
    print("Match:", result["person_id"], "score:", result["confidence_score"])
else:
    print("No match. Flag:", result["flag"])
```

The `identify()` return shape:

```python
{
  "matched":            bool,   # True only when flag == "confirmed"
  "person_id":          str,    # None if no confirmed match
  "confidence_score":   float,  # top score (0–200 for NBIS, 0–100 for BFS)
  "second_score":       float,  # runner-up score
  "effective_threshold": float, # threshold after clarity adjustment
  "clarity":            float,  # probe image clarity 0–1
  "flag":               str,    # "confirmed" | "low_confidence" | "no_match" | "poor_scan_quality"
  "all_scores":         dict,   # {person_id: score, ...}
}
```

---

## Architecture

```
       ┌───────────────────┐
       │ U.are.U 4500      │
       │ (USB reader)      │
       └──────┬────────────┘
              │ DigitalPersona driver
              ▼
       ┌───────────────────────────┐
       │ FingerprintBridge.exe     │  bridge/
       │ (.NET DPFP SDK wrapper)   │
       └──────┬────────────────────┘
              │ JSON over pipe/stdout
              ▼
       ┌───────────────────────────┐
       │ scanner/bridge_client.py  │
       │ (Python event stream)     │
       └──────┬────────────────────┘
              │ raw PNG bytes
              ▼
       ┌───────────────────────────┐
       │ pipeline/                 │
       │   preprocess (CLAHE+Gabor)│
       │   quality gate            │
       │   template (NBIS or BFS)  │
       │   match / identify        │
       └──────┬────────────────────┘
              ▼
        matched / no-match
```

---

## The matching algorithm

Two matcher backends are shipped. The default is NBIS (best accuracy); the
BFS matcher is what runs when NBIS isn't available.

### Default: NBIS (bozorth3) — biometric-grade

`mindtct` extracts minutiae into an `.xyt` file; `bozorth3` scores two `.xyt`
files against each other. Both are wrapped by `pipeline/nbis.py` in a
subprocess call — no Python bindings needed.

* Score range on genuine same-finger pairs: **40–200+**
* Score range on impostor pairs:              **0–15**
* NIST-recommended decision threshold:         **40**
* Deployed operationally by AFIS systems for decades.

### Fallback: edge-based BFS matcher (SourceAFIS-inspired)

`pipeline/minutiae.py` is a from-scratch matcher I wrote when NBIS wasn't
available. It's not as accurate as bozorth3, but it's pure Python, fast
enough for small galleries, and rejects impostors far better than the naive
"count matched minutiae" approach.

**Core idea:** for each minutia, describe its geometric relationship to its
K nearest neighbours as a triple `(edge length, angle at source, angle at
neighbour)`. All three values are rotation-invariant — they encode geometry
relative to each minutia's own ridge direction, not the image axes.

**Matching:** for each candidate anchor pair `(probe minutia p, gallery
minutia c)`, grow the matched set via BFS: if `p` is matched to `c`, and
`p` has an edge to `p'` that geometrically matches an edge from `c` to
some `c'`, then `p' ↔ c'` is also a match — continue.

For a genuine match, one correct anchor triggers transitive propagation
through the consistent geometric graph, typically accumulating **35–55
matched pairs (score 58–92)**. For an impostor, each edge triple must
agree simultaneously on three independent values — P(random match) ≈ 0.2%
per pair, so accumulating 6 false pairs has P ≈ 10⁻⁹. False accepts stay
below 0.01%.

**Decision layer** (`pipeline/match.py`) adds three cross-cutting guards:

1. **Quality-scaled threshold** — low probe clarity raises the confirm bar.
2. **Gap-to-runner-up** — the winner must beat the second-best by both an
   absolute margin *and* a ratio. Impostor scores cluster near each other,
   so this alone kills most false accepts.
3. **Three-tier adaptive threshold** — a probe is confirmed when
   *any* of `(absolute strong)`, `(clear winner)`, or `(dominant leader)`
   fires. Genuine users pass in one press; impostors fail all three.

Read `pipeline/minutiae.py` and `pipeline/match.py` for the full detail —
they're heavily commented.

---

## Configuration

All tuning knobs live in `pipeline/pipeline_config.py`. Notable ones:

| Key                          | Default   | What it controls |
|------------------------------|-----------|------------------|
| `USE_NBIS_MATCHER`           | `True`    | Use NIST bozorth3. Set False to force the BFS matcher. |
| `USE_ADAPTIVE_THRESHOLD`     | `True`    | Three-tier decision. Set False for a legacy single threshold. |
| `MATCH_TIER1_STRONG`         | `50`      | Confirm if score >= this, regardless of runner-up. |
| `MATCH_TIER2_MIN`            | `15`      | Minimum score for the "clear winner" tier. |
| `MATCH_TIER2_RATIO`          | `2.0`     | Winner / runner-up ratio for the clear-winner tier. |
| `MATCH_TIER2_GAP`            | `10`      | Absolute gap for the clear-winner tier. |
| `QUALITY_MIN_CLARITY`        | `0.18`    | Reject blank-looking scans below this. |
| `MATCH_PARALLEL`             | `True`    | Multi-thread 1:N scoring. |

The defaults are what I ended up on after a few weeks of live use with ~200
enrolled people. If you're running a much larger gallery (thousands), raise
`MATCH_TIER1_STRONG` and `MATCH_TIER2_RATIO` to stay ahead of the growing
noise floor.

---

## Repository layout

```
openfinger/
├── bridge/                       # Windows capture bridge
│   ├── FingerprintBridge.cs      # C# source (~200 LOC)
│   ├── FingerprintBridge.exe     # Compiled bridge
│   ├── DPFPDevNET.dll            # DigitalPersona SDK (vendor)
│   ├── DPFPShrNET.dll            # DigitalPersona SDK (vendor)
│   ├── build.bat                 # Rebuild the exe
│   ├── README.md                 # Reader / driver setup
│   └── nbis/
│       ├── mindtct.exe           # NIST minutiae extractor (public domain)
│       ├── bozorth3.exe          # NIST matcher (public domain)
│       └── README.md
├── pipeline/                     # The algorithm
│   ├── preprocess.py             # CLAHE + Gabor + skeletonize
│   ├── quality.py                # Clarity / coverage gates
│   ├── minutiae.py               # BFS matcher (from-scratch)
│   ├── nbis.py                   # bozorth3 wrapper
│   ├── embedding.py              # DINOv2 alternative (optional)
│   ├── enroll.py                 # Multi-scan template builder
│   ├── match.py                  # 1:N identify with adaptive gates
│   ├── coverage.py               # Guided-enrollment coverage tracking
│   └── pipeline_config.py        # All tuning knobs
├── scanner/
│   └── bridge_client.py          # Python client for the bridge exe
├── examples/
│   ├── capture.py                # Save N raw scans as PNGs
│   ├── enroll_cli.py             # Enroll a person → gallery/*.pkl
│   └── identify_cli.py           # Identify against the gallery
├── requirements.txt
├── LICENSE                       # MIT (plus third-party notices)
└── README.md
```

---

## Troubleshooting

**`FingerprintBridge.exe not found`**  
Rebuild it: `cd bridge && .\build.bat`. Needs .NET Framework's `csc.exe`
(present on any modern Windows).

**`DPFP_INIT_ERROR — Failed to start fingerprint reader`**  
Almost always a missing driver. Install the HID DigitalPersona driver, then
check Device Manager for **DigitalPersona U.are.U** under a *Biometric* or
*DigitalPersona* node. Unplugging and replugging usually helps after
install.

**`NBIS binaries not found`**  
`mindtct.exe` and `bozorth3.exe` must be in `bridge/nbis/`. They ship in
this repo. If missing, see [`bridge/nbis/README.md`](bridge/nbis/README.md)
for rebuild instructions.

**Bridge status stays `disconnected`**  
Another process may already hold the reader. Look for a lingering
`FingerprintBridge.exe` in Task Manager and kill it.

**Scores look strange after tuning**  
Turn on the JSON log by leaving `LOG_ENABLED=True` in
`pipeline_config.py`. Every enroll/identify writes one line to
`fingerprint_log.txt` with timings, scores, and applied steps.

---

## Contributing

PRs welcome. Areas where help would be great:

* **Linux capture backend** — a `libfprint`-based drop-in replacement for
  the .NET bridge, keeping the JSON event shape.
* **More readers** — bindings for other cheap USB fingerprint scanners
  (Futronic, SecuGen, ZKTeco).
* **A fine-tuned fingerprint embedding** — the DINOv2 backend in
  `pipeline/embedding.py` uses natural-image weights. A fingerprint-specific
  fine-tune would beat NBIS on wide galleries.
* **A small labelled test set** — FVC-style so we can publish real EER
  numbers instead of "worked on my ~200-person gallery."

Please open an issue before large refactors so we can align on approach.

---

## License

MIT for original code. Bundled binaries have their own terms — see
[`LICENSE`](LICENSE). Short version:

* **openfinger code** — MIT, do whatever you want.
* **NBIS binaries** — NIST, public domain.
* **DPFP DLLs** — HID Global proprietary. Fine to *use*; if you plan to
  *redistribute* your fork, re-download them from HID as part of the SDK
  install so you're on their terms directly, not mine.
