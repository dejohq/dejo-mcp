# Security

Dejo runs a real, signed-in browser on your machine, so we take security reports seriously.

## Reporting a problem

**Please do not open a public issue for a security problem.**

Report it privately through GitHub:
[**Report a vulnerability**](https://github.com/dejohq/dejo-mcp/security/advisories/new).
If that does not work for you, email **rohitkashyapmrt@gmail.com** with "Dejo security" in the
subject.

Please include:

- the version (`pip show dejo-mcp`) and your operating system
- what an attacker could do, and what they would need first
- the steps to reproduce it, as small as you can make them

You will hear back within three days. Once the problem is confirmed, we will agree a date to
publish the fix and the advisory, and credit you unless you would rather not be named.

## Supported versions

Only the latest release gets security fixes. Upgrade with `pip install -U dejo-mcp`.

| version | supported |
|---|---|
| 0.1.x | yes |
| older | no |

## What we especially want to hear about

Dejo keeps sensitive things on your machine, and these are the promises that matter most:

- **Passwords never reach memory.** A saved step records only that a password goes there; the
  value is read at run time from an environment variable or `~/.dejo/secrets.json`. Anything
  that writes a typed value into `~/.dejo/memory.db`, into history, or into a shared route is
  a security bug.
- **Sharing never carries an identity.** A route shared with another agent must contain no
  typed value and no account name.
- **Signed-in profiles stay local.** Anything that sends cookies, sessions or profile data off
  the machine, other than to the website being visited, is a security bug.
- **Replay never reaches the network on its own.** Replay talks only to the website in the
  route.
- **The MCP server only speaks stdio.** It opens no port.

## Things that are not a vulnerability

- The `evaluate` action runs JavaScript the agent asks for, in the page it is on. That is its
  job. It is never saved into a route.
- Anyone who can already read your home folder can read `~/.dejo`, exactly as they could read
  your own browser's profile.
