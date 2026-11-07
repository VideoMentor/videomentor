# Security

## Reporting a problem
Please report security problems **privately**, not in a public issue:

- On GitHub, open the repository's **Security** tab and choose **Report a vulnerability**.

Include what you found, how to reproduce it, and the version (`vm --version`). You'll get a reply within a week. Please give us a reasonable time to fix it before you talk about it publicly.

## Supported versions
Only the latest release gets security fixes.

## How VideoMentor protects your library
- The app runs on your own computer and listens only on `127.0.0.1` by default. Phone access goes through your own Tailscale network.
- A device pairs once with a 12-digit code. Each paired device gets its own random sign-in, stored only as a fingerprint, which ends after 90 days without use. You can sign devices out in **Status > Paired devices** or with `vm devices`.
- After 10 wrong pairing codes in 15 minutes, pairing pauses. Pairing codes are kept out of the server log.
- Your library, tokens and settings stay in `~/VideoMentor/` on your computer. YouTube access is read-only.
