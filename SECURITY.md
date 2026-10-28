# Security

## Report a vulnerability or a leak

⛔ **Do not put the detail in a public issue.** A public issue shows the detail to every reader, and a copy
stays in notifications and in archives after the issue is edited.

Use the private report form of this repository:
<https://github.com/Azathothas/fshy.ajam.dev/security/advisories/new>. Only the maintainers of the repository
can read the report. Give the file, the page or the API route, and what you found.

If the form is not available, open an issue with the title "Private report" and no other text. A maintainer
then opens a private advisory and adds you to it.

## What to report here

- A secret, a key or a token in a file of this repository, in `data/`, or on the site.
- A personal detail about a person: a name, an email address, an address, an IP address or a device name.
- A way to change the data through the API or the MCP endpoint, or to read a file that the site does not serve.
- A request that makes the Worker use its full CPU limit, or that makes it fail for other users.

## What to report with a public issue

- An error in a record. Use the **Correction** form.
- An offer that the catalogue does not have. Use the **New offer** form.
- A page, a route or a tool that does not work as documented. Use the **Site or tool problem** form.

See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## What happens to a report

A maintainer reads the report, confirms it, and fixes it. If the problem is in `data/`, the fix is in the
research repository, and the next publish removes the value. The advisory closes when the fix is published.
