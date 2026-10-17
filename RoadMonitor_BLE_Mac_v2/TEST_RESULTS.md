# Firebase dashboard verification

Checks performed for this update:

- JavaScript syntax: app.js, cloud.js, recorder.js and firebase-config.js.
- Original dashboard DOM logic regression: simulation dip/raised-surface events,
  mocked BLE connection/subscription/calibration/disconnection, little-endian
  signed GPS decoding, lost GPS fix, invalid distance, stale readings, and bad
  packet/version handling.
- Recorder with an IndexedDB test implementation: 123 of 123 records retained
  across grouping; failed uploads remain queued; successful retry removes only
  acknowledged rows; interrupted unsealed group recovered; another account cannot
  drain a user's local queue; acknowledging an old session revision does not
  delete a newer stopped-session record; disk error stops recording explicitly.
- Cloud UI in a DOM test environment with a mocked Firebase SDK: enable, sign-in,
  simulation recording, stop/upload confirmation, session list, history frame/GPS
  display, and clearing history on sign-out.
- ZIP contents and Python launcher syntax checked. Firmware compared byte-for-byte
  with the previously delivered package: unchanged.

Not verified here:

- A real Google sign-in or write/read to your Firebase project. No live project
  data was written, and your Console settings were not changed.
- Physical BLE/sensor operation (the user reported the original version works).
- Browser-engine rendering. The earlier browser download failed in this runtime;
  DOM tests do not replace an actual visual/browser compatibility check.
- Firestore Security Rules emulator: the included owner-only rules follow the
  documented syntax but must be published and verified using your account.

Run the 15-second simulation test in CLOUD_START_HERE.md before a real survey.
