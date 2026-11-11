# Event-Based Studio privacy information

Publisher: Alpha Makuza. Applies to desktop version 2.0.0rc1.

The desktop application processes recordings locally. It has no publisher-run
account, analytics, telemetry, crash-upload, cloud-storage, or automatic-update
service. This describes the application code; your operating system and any
separately installed camera SDK or conversion tools have their own behavior.

Files you open, project/session metadata, legacy recovery files, thumbnails,
converted recordings, and diagnostic logs remain on your computer unless you
choose to share them. Camera use is initiated through the Live Camera controls.
Camera drivers and conversion software are optional and installed separately.

Packaged builds store application files under `%LOCALAPPDATA%/Event-Based Studio`,
unless `EVENT_STUDIO_HOME` overrides that location. Interface preferences also
use the current user's Qt settings store. Closing the editor saves the project,
thumbnail and animated preview. No periodic recovery snapshots are created.
Logs rotate locally. Projects persist until you delete them.

Exported `.ebs` bundles can contain the recording, annotations, original file
paths and provenance metadata. Review before sharing. Project deletion removes
files in that project folder, including a recording imported into that folder;
external original recordings are separate. Keep backups.

Removing the application folder does not remove your projects or preferences.
To remove local data, back up anything you need, close the app, and remove its
storage folder and the Event-Based Studio preference entries from your user
settings. Changing the storage override does not migrate or erase old data.

If you voluntarily send support information, review it first and omit private
recordings, paths, and annotation text you do not want to share. A support
page provides troubleshooting; direct email or ticket submission is not yet
available. No support-submission information is collected by this site.

The download website is a separate service. Its hosting provider receives
ordinary HTTP request information. The prepared site uses no application
accounts, analytics scripts, advertising, or contact forms. This desktop notice
does not promise that hosting providers or operating systems collect no data.
