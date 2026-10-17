# AWR6843ISK experimental ice surface comparison

This is a calibration and testing tool, not a validated ice detector. It compares
your measured range profile with labeled dry, wet and icy samples. It ships with
NO trained samples, NO claimed accuracy and NO universal ice threshold. Ice may
not be separable from wet or dry pavement using this profile. Do not use its output
to decide whether a road is safe to drive on.

## Windows quick start

1. Extract the entire ZIP into a normal folder, for example C:\Senior design\IceRadar.
2. Open PowerShell in that folder and run:

   python -m pip install -r requirements.txt
   python ice_radar.py

   After installing dependencies you can also double-click START_WINDOWS.bat;
   this keeps the terminal open if Python reports an error.
3. Close TI Visualizer, Tera Term and other programs using either radar port.
4. Select the CLI and DATA ports from Windows Device Manager. Defaults are COM4
   (CLI, 115200) and COM3 (DATA, 921600); these must match your computer.
5. Set the range interval to surround the actual surface return, then Connect.
   Defaults of 0.5–1.5 m are an example, not a measurement of your setup.
   The yellow lines bound the bins used by the model. Distance is slant range
   from the radar, not vertical mounting height. At least 3 bins are required.
6. Record known DRY, WET and ICE samples as described below, then select
   Build / validate model. The program updates its result about once a second
   and requires three matching consecutive results before displaying a class.

Optional command:

   python ice_radar.py --cli COM4 --data COM3 --samples experiment2.json

Python must include Tkinter (included by the usual Windows Python installer).
The radar must already run compatible TI mmWave SDK 3.x out-of-box firmware,
matching the SDK 3.6 configuration. This program does not flash firmware. People
tracking, gesture or other lab firmware may use different commands or packets.

## What is special about your configuration?

road_profile.cfg is an exact copy of your uploaded configuration. The program
sends it as provided and checks for Done after each command. It stops on errors
instead of pretending a failed configuration succeeded. The original includes a
second chirp entry with TX enable zero; if your firmware rejects that command,
cli_log.txt will show the exact failure. Regenerate a matching OOB configuration
with TI Visualizer for that firmware rather than ignoring the error.

Your guiMonitor enables detected points, the range profile and statistics.
The classifier uses TLV type 2 (range profile), so stationary surfaces can be
observed even when CFAR outputs no detected points. Static clutter removal is
disabled in the supplied file. Keep it disabled for this experiment.

The 256 samples, 12499 ksps sampling rate and 30 MHz/us chirp slope give a range
bin spacing of about 0.244 m (the FFT size is 256). This long-range configuration
does not resolve millimeter ice thickness. It measures changes in the aggregate
reflected profile. One TX and two RX are enabled by channelCfg 3 1 0.

The SDK 3.x OOB decoder uses the 40-byte little-endian header, 8-byte TLV headers
and payload-only TLV lengths. It checks lengths, handles split packets and
resynchronizes after garbage. Each range profile must contain 256 unsigned
16-bit values. Values are kept in RAW FIRMWARE UNITS: the UI does not claim
absolute dB, received power, calibrated reflectivity or dielectric constant.

## Collect samples that mean something

- Mount the radar rigidly and point it at a pavement sample. Keep the same radar,
  substrate, sample holder, angle, distance and surrounding scene for all classes.
  Keep the electronics dry and use a sample area large enough to dominate the beam.
- First confirm a visible, repeatable surface return. Change the range interval
  before collecting samples if needed. The range plot is auto-scaled: an apparent
  similar curve does not imply equal amplitude. Values at the top show its scale.
- Collect the same substrate dry, with water, and with confirmed ice. Use a
  thermometer and direct inspection for ground truth if available; the radar
  cannot verify its own training labels. Record temperature, water/ice thickness,
  angle and distance in your experiment notes.
- Keep hands, tools and moving people out of the beam during each 15-second
  recording. Do not hold an ice cube in front of a dry road sample and call that
  road ice: the classifier could learn the cube's shape or your hand.
- Record at least THREE independent sessions for EACH class. Five to ten or more
  are preferable. Reprepare or replace the specimen between sessions; simply
  clicking Record again produces near-duplicate data and optimistic validation.
- Vary specimen preparation and repeat on different days; keep geometry fixed
  within this initial experiment. Melting ice is a mixed condition; do not label
  it pure ice without documenting that choice.
- After building, test on new known dry, wet and icy specimens that were never
  recorded. Track false ice alarms AND missed ice. If wet and ice overlap, the
  data do not establish a useful detector, even when the training display looks good.

## Model and saved files

The program forms one-second median profiles over the selected range bins.
At least five frames per window and ten windows per recorded session are needed.
Each session's median contributes equally to the class centroid. Feature scales
come from the session medians, with a 32-raw-unit floor. These choices are simple
engineering heuristics, not optimized or validated ice physics.

A sample is UNKNOWN if its standardized distance exceeds the learned class
envelope or its separation from the second-closest class is below 25%. The
envelope is 1.5 times the class's 95th-percentile training-window distance, with
a 0.35 minimum. These are rejection heuristics, NOT a probability or confidence
percentage. They cannot guarantee rejection of every unfamiliar surface.

ICE-LIKE SAMPLE MATCH means resemblance to your ice recordings, not confirmed
ice. DRY and WET likewise mean sample matches. No temperature sensor, camera,
thin-film model, phase measurement or pretrained material model is included.

- surface_samples.json: labeled one-second ROI profiles, timestamps, configuration
  fingerprint and range-bin selection. Automatically saved after recording.
- surface_samples.validation.json: leave-one-session-out prediction counts.
  Each held-out session is completely excluded from its fold's training. Rows
  are true classes; columns are predicted dry/wet/ice/unknown. Unknowns are retained,
  not hidden to increase apparent accuracy. Neighboring windows remain correlated;
  these counts are a lab diagnostic, not independent field trials.
- cli_log.txt: commands and firmware replies for the latest connection.

Saved samples are loaded on Connect only when the configuration and selected bins
match exactly. Click Build / validate model to rebuild after reopening the app.
To start a different mount, interval or configuration, use --samples with a new
filename. Even if the software allows old samples, do not reuse them after moving
the radar. To start entirely over, back up and remove surface_samples.json.

## Troubleshooting

- No window / missing modules: run from PowerShell and install requirements.
- Access denied: close other serial applications; verify both port assignments.
- Configuration rejected: inspect cli_log.txt; check the firmware/config pairing.
  Do not skip rejected commands. The configuration must succeed completely.
- No valid range profile: check the DATA port and 921600 baud. Bytes alone do not
  prove the expected packet format. This decoder is specifically for SDK 3.x OOB.
- No detected points: not necessarily a failure; this tool uses the range profile.
- UNKNOWN: collect better independent samples, check surface range and geometry,
  and inspect wet/ice confusion. Do not lower thresholds just to force ICE.
- Data stops: the UI clears the prediction after two seconds, aborts an active
  recording and reports a serial/data failure after ten seconds. Reconnect after
  resolving the issue. Already-completed samples remain saved.

## Verification and references

The included test script exercises fragmented packets, malformed lengths,
configuration geometry, clear synthetic class separation, ambiguity and outlier
rejection. Run: py test_core.py

All seven synthetic core checks passed. In the build environment the serial
module was stubbed for importing the core functions because pyserial was not
available; no serial communication was simulated or verified by those checks.
The graphical interface and Windows launch require testing on your computer.
Software checks cannot establish physical ice detectability. No physical board
or dry/wet/ice measurements were available when this package was created.

TI mmWave SDK (firmware and local OOB packet-format documentation):
https://www.ti.com/tool/MMWAVE-SDK

TI mmWave Demo Visualizer User's Guide, range profile section 2.9.2:
https://www.ti.com/lit/ug/swru529c/swru529c.pdf

TI explanation of range resolution vs accuracy:
https://www.ti.com/document-viewer/lit/html/SWRA841
