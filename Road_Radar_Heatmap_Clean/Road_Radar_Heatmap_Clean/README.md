# Road Radar Heatmap — AWR6843ISK / TI SDK 3.x

Windows: extract this folder, open a terminal inside it, then run:

    py -m pip install -r requirements.txt
    py radar_heatmap.py --cli COM4 --data COM3

Close mmWave Demo Visualizer and Tera Term first; only one program can own a COM port.
COM4/COM3 are your earlier port assignments. Confirm Enhanced/CLI and Standard/DATA in Device Manager.
Requires the standard xWR68xx SDK 3.x out-of-box firmware compatible with your SDK 3.6 configuration, not Small Obstacle Detection firmware or another lab's protocol.
The included configuration is an unchanged copy of your upload. CLI baud: 115200; DATA: 921600.
If your Visualizer already configured the board, close it and add --no-config.

Try the interface without hardware:

    py radar_heatmap.py --demo

Click Calibrate to see the simulated positive and negative changes. Demo data is deliberately synthetic and proves no classification accuracy.

## Use

1. Secure the radar at a fixed height/angle, aimed toward the road surface. Keep it stationary.
2. Start with a clean road patch in view, then click Calibrate. It collects 40 frames (~4 seconds).
3. Compare changes with the same view and mount. Stronger returns can suggest debris; weaker returns can suggest a depression/pothole. Both labels are experimental and may be wrong.
4. White circles mark the strongest persistent change for each sign. Three consecutive frames are required. Default threshold is 8 dB and four times baseline variation.
5. Tune the region or threshold, for example:

    py radar_heatmap.py --cli COM4 --data COM3 --min-range 0.5 --max-range 4 --threshold 10

The left panel displays static range-angle return amplitude (relative, not calibrated power). The right displays change from baseline. Range means radar slant range, not depth below road or forward ground distance. Angular FFT interpolation does not improve physical antenna resolution. Two RX antennas in this profile give coarse angular discrimination. Peak locations and labels should not be treated as precise obstacle geometry.

## What it can and cannot determine

This is an anomaly viewer, not a trained pothole classifier. Return strength depends on material, moisture, aspect angle, shadowing, and multipath. A pothole can increase OR decrease return strength; debris can also cause either. Empty space or weak reflection alone is not evidence of a pothole. Multiple anomalies of one sign are summarized by the strongest cell, not individually tracked.

A moving vehicle changes the baseline view and makes these labels unreliable; this implementation is for stationary bench/road experiments. Static heatmap TLV 4 uses zero-Doppler data, so it is unsuitable for interpreting an uncompensated moving-platform scene as a road map. No reliable ice, speed-bump, object-size, depth, or material classification is implemented.

For actual classification, collect labeled examples of clean road, potholes, debris, and bumps at representative mounting positions and speeds. Validate on separate roads. Fuse measured road height (ToF/depth sensor), vehicle motion, and radar features; use a trained classifier with an unknown class. Do not invent confidence percentages from amplitude thresholds.

## Troubleshooting

- Configuration errors are printed in the terminal; check firmware compatibility and CLI port.
- No heatmap: confirm `guiMonitor -1 0 1 0 1 0 1`, correct DATA baud, and sensorStart accepted.
- The app expects the legacy 40-byte header, little-endian TLVs, and TLV 4 imaginary/real int16 antenna samples. Different firmware needs a different parser.
- Do not change antenna/TX settings without adapting antenna ordering and validating against the TI Visualizer. This version intentionally supports the supplied single azimuth TX profile.
- Recalibrate after changing the mount, scene, or surface. Do not calibrate with the anomaly present.

Technical references:
https://dr-download.ti.com/software-development/software-development-kit-sdk/MD-PIrUeCYr3X/03.06.00.00-LTS/mmwave_sdk_user_guide.pdf
https://e2e.ti.com/support/sensors-group/sensors/f/sensors-forum/813923/iwr6843isk-range-azimuth-heat-map-how-to-parse-tlv-and-compute-data

Validation: synthetic packet parsing, heatmap dimensions, positive/negative anomaly persistence, and Python compilation. Physical hardware operation and classification accuracy have not been validated.

## Cleaner display update
Smoothed display with interpolated colors, stable return color limits, simplified dark layout and clearer status text. Temporal smoothing affects the return display only; anomaly calculations still use original frames. Interpolation does not add sensor resolution.
