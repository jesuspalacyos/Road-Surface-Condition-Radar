# RoadMonitor — Firebase recording and saved-trip playback

Your Firebase web configuration is already in `firebase-config.js`, copied from
provided screenshot. Project: **roadmonitor-16c51**. Your existing ESP32 firmware
and wiring stay the same. No firmware upload is required for this dashboard update.

## 1. Finish these Firebase Console settings

Use https://console.firebase.google.com/ and select RoadMonitor.

- **Security → Authentication → Sign-in method:** enable Google and select a support email.
- **Authentication → Settings → Authorized domains:** add `localhost` if missing.
- **Databases & Storage → Firestore Database:** create the **default** database,
  Standard edition, if not already created. This code uses Cloud Firestore, not
  Realtime Database and not a Cloud Storage bucket.
- In **Firestore Database → Rules**, replace the editor contents with the contents
  of `firestore.rules` from this folder and click Publish. Rules limit each signed-in
  user to their own `/users/{uid}/...` data. These are prototype owner-only rules,
  not a schema-validation policy for a public multi-user service.

The screenshot of a configuration does not confirm these settings or published rules;
this update has not changed your Firebase Console settings for you.

## 2. Start the updated dashboard

Extract this updated ZIP into a fresh folder to avoid mixing old and new JavaScript.
The folder inside the ZIP is still called `RoadMonitor_BLE_Mac_v2`.
Stop any older dashboard server with Control+C in its Terminal window. In the updated folder:

```bash
python3 start_dashboard.py
```

Visit http://localhost:8000/dashboard.html in desktop Google Chrome on your Mac.
If the old page appears, use Command+Shift+R to refresh without cached assets.
No npm installation is required on your Mac. Python serves local files only; the
browser connects directly to Firebase with the Firebase JavaScript SDK.

## 3. First cloud test (use simulation before a real road survey)

1. Scroll to **Save your road surveys** and click **Enable cloud**. This loads the
   Firebase SDK from Google's CDN and opens the local save queue on this Mac.
2. Click **Sign in with Google** and choose your account. Sign in from the dashboard,
   even if you are already signed in to Firebase Console in another tab.
3. Click **Try simulated data** in the top toolbar and wait for readings.
4. Enter a trip name such as `Cloud test`, then click **Start recording**.
5. Wait about 15 seconds, then click **Stop & save**.
6. Wait until the cloud status says **All uploaded**. “Saved locally” alone does
   NOT mean the data has reached Firebase.
7. Under **Saved trips**, click **Find trips**, select `Cloud test`, and click **Open trip**.
8. Move the slider or click **Play** to see the saved readings and route. Simulation
   trips are labeled `[SIM]` in the selector and `SIMULATED` in the history status.
9. Refresh the page, enable cloud, sign in with the same account if needed, and find
   the trip again. This is the important end-to-end persistence check on your project.

For a real survey, stop simulation, connect your ESP32, calibrate over flat ground,
and then Start recording. Stop & save at the end. Disconnecting BLE automatically
stops the current recording. Missing GPS does not block saving sensor readings.

## 4. How recording and uploads work

ESP32 → BLE → Chrome on Mac → Mac internet connection → Firebase Firestore.
ESP32 Wi-Fi is not used. A Mac internet connection is required for Google sign-in,
initial SDK loading, uploading, and fetching historical trips. Live BLE still works
with cloud disabled. Keep the page open and the Mac awake throughout recording;
closing the page or suspending the Mac stops reception of new BLE readings.

While recording, each received sensor/GPS packet is put into a durable **IndexedDB**
queue on the Mac. About every five seconds the current group is sealed and offered
to Firestore as one document. A retry writes to the same document ID, avoiding
additional copies. Local queue entries are removed only after Firebase acknowledges
that write. No automatic deletion or expiry of uploaded trips is configured.

A network outage can leave readings queued locally. After internet returns, uploads
resume while this page remains open. After a browser restart, open this same updated
page at **the same localhost address/port**, enable cloud and sign in with the same
Google account to recover queued data. An interrupted session is marked `interrupted`;
its exact end time is unknown, and its last readings have their own timestamps.
Starting again creates a new trip rather than silently appending to an old trip.

Use your own Mac and a normal browser profile. Clearing website data, using private
browsing, changing origin/port, disk failure, browser eviction, or a crash before an
IndexedDB transaction commits can lose access to unsent readings. A local storage
failure stops recording and shows an explicit error. Keep the page open until All
uploaded, and export important recordings. One cloud-enabled tab is allowed at a time
using a browser lock. Another tab may still run the BLE-only dashboard.

No system can recover packets that never arrived over BLE, or readings generated
while the dashboard was closed. “All data” means all packets received while recording.
The existing firmware already summarizes acceleration as interval peaks, so this is
not a 100 Hz raw accelerometer logger. Real packets include raw 20-byte payloads,
device uptime, nominal X/Y/Z g, range/baseline/validity/calibration, GPS/speed/HDOP,
Mac receipt times, and the dashboard assessment/thresholds for sensor packets.
Simulation records have generated values and no raw BLE payload.

## 5. Later review

You can reopen the dashboard and sign in with the same Google account without
connecting the ESP32. Find trips uses the selected date range (trip START date,
interpreted in the Mac's local time zone). Use **More trips** to load another 25 trips.

Open trip loads up to 100 data-group documents at once, usually about eight minutes
of recording. **Next portion** replaces that view with the following portion. This
bounds browser memory and avoids automatically reading an entire long trip. Portions
are independently displayed; at their start, sensor or GPS information may remain
unavailable until that packet type first appears. The history map is an offline,
north-up route plot, not an online street-map replay.

**Download portion JSON** exports all readings in the currently loaded portion.
For a long trip, advance through portions and export each as needed. It does not
export the entire trip in one click. The original top-level Export events CSV
still exports the current live tab's observations, not historical Firebase data.

History is loaded on demand, not through a continuous Firestore listener. If a trip
is still uploading, finish uploading and click Find trips/Open trip again to refresh.
Historical observations do not establish the road's current condition. Ice remains
`not_measured`, and dip/raised-surface labels remain unconfirmed indicators.

## 6. Where to find data in Firebase Console

In Firestore Database → Data:

`users / your-authentication-UID / sessions / session-ID`

The session document contains name, start/end times, status, simulation flag, and
initial thresholds. Its `chunks` subcollection contains timestamped arrays of sensor
and GPS records, plus assessments in the sensor records. Observations are stored
with readings, not in a separate events collection in this implementation.

Do not manually create user IDs or sample documents. Google sign-in and recording
create the actual paths automatically. Parent user documents may appear without
fields; data lives in their session subcollections.

## 7. Troubleshooting

- **auth/unauthorized-domain:** add localhost in Authentication → Settings → Authorized domains.
- **auth/operation-not-allowed:** enable Google sign-in.
- **Popup blocked/closed:** allow the popup and click Sign in again.
- **permission-denied:** verify the default Firestore database exists and publish
  the included rules in FIRESTORE's Rules tab. Realtime Database rules are different.
- **API key invalid:** compare firebase-config.js with the Console's Config block;
  copy the exact text if a screenshot character was misread.
- **Cloud could not start:** ensure your Mac has internet and can reach Google's
  Firebase CDN. Check Chrome's JavaScript console for blocked network requests.
- **Cloud open in another tab:** close the other cloud-enabled RoadMonitor tab and retry.
- **Start recording disabled:** enable cloud, sign in, connect BLE or start simulation,
  and wait for fresh readings. A local storage error requires fixing storage/reloading.
- **Saved locally / uploading indefinitely:** restore internet; check Firestore
  permissions/quota. Leave the page open or reopen at the same origin with the same
  account later. Do not erase website data while uploads are pending.
- **No trips:** use the same Google account that recorded them, clear date filters,
  and wait for successful upload before clicking Find trips.
- **Sign out disabled:** stop recording and wait for active uploads to finish.

## 8. Usage and validation

Five-second grouping is about 720 chunk writes/hour, plus session writes and any
retries. Storage grows with every trip. Check Firebase's Usage tab; batching does
not make storage unlimited. This package does not enable billing or deploy Hosting.

The JavaScript SDK version is pinned to 12.19.0. Authentication and Firestore load
only after Enable cloud; Analytics is not initialized. Cloud data is protected by
Firebase Authentication plus the rules you publish. Config values identify the web
app and are not a service-account private key.

See TEST_RESULTS.md for checks and limits. Real Firebase sign-in/upload and physical
BLE must be verified on your Mac using the first cloud test above.

Primary documentation:
https://firebase.google.com/docs/web/alt-setup
https://firebase.google.com/docs/auth/web/google-signin
https://firebase.google.com/docs/firestore/security/get-started
https://firebase.google.com/docs/firestore/quotas
