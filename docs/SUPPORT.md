# Support

Publisher and copyright owner: Alpha Makuza.

Support and troubleshooting page:
https://event-based-studio-alpha-makuza.luxedance1.chatgpt.site/#support

The website is private staging until release testing is complete. It provides
self-service guidance; direct email support and a ticket-submission service
are not available yet. No response time or individual assistance is promised.

Before reporting a problem, note the application version, Windows version,
steps to reproduce, expected/actual behavior, and whether optional camera or
conversion software was installed. Logs are under the application's user
storage folder in `logs/application.log`. Review them before sharing. Use a
small synthetic recording if possible; do not send private data by default.

Closing the editor saves the project automatically. Ctrl+S saves during longer
sessions. If saving fails, the editor stays open with an error. If recording
relocation is requested, select the identical CSV. Preserve original recordings.

Do not publish credentials, signing keys, private recordings, or personal data
in a public bug report. A private security-reporting contact has not yet been
established. Do not post sensitive security details on public channels.

## Recording formats

Open DAT, CSV, H5 or HDF5 through File > Open recording. File import uses bundled
readers and does not require WSL/OpenEB. Supported DAT files contain 8-byte CD
events (versions 1/2). HDF5 files need a one-dimensional CD/events or events
dataset with integer microsecond t,x,y,p fields. Standard HDF5 compression and
Prophesee ECF are supported. Precomputed event cubes, histograms and time
surfaces do not contain the original event tuples; obtain the event recording.

Live cameras still require a compatible native Metavision SDK and driver.
