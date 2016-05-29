This repository contains the configuration files for pdfjs.robwu.nl. This site
collects anonymous statistics from the [PDF Viewer Chrome extension](https://github.com/mozilla/pdf.js/wiki/PDF-Viewer-%28Chrome-extension%29)
("telemetry").

## Privacy policy

### What information is collected?

The PDF Viewer extension sends at most two pings a day to the server,
and the following data is saved:

- The server's local time (year, month, day).
- User agent string (browser version, Operating System).
- PDF Viewer extension version.
- A random constant identifier. The value is refreshed at every major browser
  update (roughly every six weeks). When the identifier is refreshed, it is not
  possible to relate the ID to any previously generated ID.

The exact time and IP address is *not* saved, so the collected information
cannot be traced back to an individual.


### Why is the information being collected?

The user agent string is used to determine how many users are still using an
old version of Chrome. This data guides decisions about updating the extension
to replace old technologies (APIs) with new ones.

The random identifier is only used to remove duplicate entries when the log data
is aggregated. The identifier is not included in any public log data.


### Who can access the data?

The server is operated by [Rob Wu](https://robwu.nl) (the main developer of the
PDF Viewer Chrome extension) and hosted in The Netherlands on servers from a
Dutch provider (https://www.liteserver.nl).

The data is automatically erased after one year.


### How can I disable telemetry?

Telemetry is enabled by default. Visit the options page of the extension and
tick the "Disable telemetry" checkbox. This value can also be set through
enterprise policies via the "disableTelemetry" setting.
