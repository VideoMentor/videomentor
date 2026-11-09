# Set up VideoMentor

About 30 minutes, once. Everything runs on your own Mac with your own accounts.

## 1. Install the tools
1. **Python tools:** install [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 for you).
2. **Node 20 or later**, for building the web app (for example `brew install node`).
3. **Claude Code**: [install guide](https://docs.anthropic.com/en/docs/claude-code). Run `claude` once in Terminal to sign in, and check that `which claude` prints a path. VideoMentor calls the `claude` command for tags, scores, notes and training, on your own Claude plan.
4. **Tailscale**, to use the app on your phone: [download](https://tailscale.com/download) for your Mac and your phone, signed in to the same account. The app only listens on your Mac itself, so without Tailscale it works in the Mac's browser only.
5. **Optional, for rendered training videos:** `brew install ffmpeg`, and Google Chrome.

## 2. Get the app
```sh
git clone https://github.com/videomentor/videomentor.git
cd videomentor
uv sync
cd web && npm install && npm run build && cd ..
```
Run commands as `uv run vm ...` (or activate `.venv` and use `vm`).

## 3. Choose your browser profile
VideoMentor reads Watch Later and private playlists with your browser's YouTube login, so be signed in to YouTube in Chrome. If you use more than one Chrome profile, find the one signed in to the YouTube account you want (Chrome menu > Profiles; the folder names are `Default`, `Profile 1`, `Profile 2`, ...), then set it in `~/VideoMentor/config.toml`:

```toml
watch_later_profile = "Profile 1"
```
The file is created the first time you run any `vm` command.

**Safari bookmarks:** YouTube links in Safari bookmarks are read too. macOS only allows that if your Terminal app has **Full Disk Access** (System Settings > Privacy & Security > Full Disk Access). Without it, Safari bookmarks are skipped. To turn them off, set `bookmark_safari = false`.

## 4. YouTube Data API (read-only)
Needed for playlist dates and channel pulls. Free: the daily quota is 10,000 units and normal use takes a few hundred.

1. Open the [Google Cloud console](https://console.cloud.google.com/) with your Google account and create a project (for example "VideoMentor").
2. **APIs & Services > Library:** search for **YouTube Data API v3** and click **Enable**.
3. **Google Auth Platform** (or **OAuth consent screen**) > **Get started:**
   - App name: anything you like; support email: yours.
   - Audience: **External**. Contact email: yours.
   - Under **Audience**, add your own address as a **test user**.
   - Leave the status as **Testing** to start. In Testing, Google ends the sign-in every 7 days and you run `vm youtube-login` again. To avoid that, set the status to **In production**: Google then shows an "unverified app" warning when you sign in, which is expected for your own private client.
4. **Clients** (or **Credentials > Create credentials > OAuth client ID**): type **Desktop app**, then **Create** and **Download JSON**.
5. Save the file as `~/VideoMentor/secrets/youtube-oauth-client.json`.
6. Run `uv run vm youtube-login`. A browser opens: pick your YouTube account and allow read-only access. When Google says "Google hasn't verified this app", choose **Advanced > Go to (your app name)**.

The sign-in token stays in `~/VideoMentor/secrets/` and never leaves your Mac.

## 5. First sync
```sh
uv run vm sync
```
Run this from Terminal. It reads Watch Later and your bookmarks, and saves a copy of your YouTube login for the background service (which can't read browser data on its own) at `~/VideoMentor/secrets/youtube-cookies.txt`. Delete that file to remove it. macOS may ask to allow access to "Chrome Safe Storage": allow it.

If the app later says syncing lost its YouTube login, run `uv run vm sync` again.

## 6. Run it and pair your phone
```sh
uv run vm serve                  # runs until you stop it (Ctrl+C)
tailscale serve --bg 8791        # once: share the app with your own devices over Tailscale
uv run vm pair                   # shows the pairing link
```
Open the pairing link on your phone (it starts with `https://` and your Mac's Tailscale name), then add the page to your home screen (Safari: Share > Add to Home Screen). The link works anywhere your phone is on Tailscale, and only on your own devices.

Each device gets its own sign-in, which ends after 90 days without use. See and sign out devices in **Status > Paired devices** or with `vm devices`. After 10 wrong pairing codes, pairing pauses for 15 minutes; devices already paired keep working. `vm pair --new` makes a new code.

On the Mac itself, `http://127.0.0.1:8791` works without Tailscale.

**Start at login:** `uv run vm install-service` installs the app as a tool and adds a login item (LaunchAgent `com.videomentor.serve`) that runs `vm serve`. Logs go to `~/VideoMentor/logs/serve.log`. `uv` must be on your PATH, and the cloned folder must stay where it is. Run it again after updating; `vm uninstall-service` removes it.

## 6b. Optional: the Mac app
Instead of running `vm serve` in Terminal, you can use the menu bar app. Run `mac/scripts/build-app.sh` to build `mac/build/VideoMentor.app`, then move it to Applications and open it. It starts the engine, shows status and the pairing link, and can start at login (a switch in its menu). Quitting the app stops its engine, so don't also run `vm serve` or the login service at the same time.

## 7. Turn on playlists
Open the **Playlists** tab and switch on the playlists you want synced. Watch Later is always on.

## Coming from an older install
If you already have a library from an earlier version in another folder, copy it in before your first sync:
```sh
# 1. Stop the older app first, using that version's own command (for example its
#    `uninstall-service`), so nothing changes in the old folder while it's copied.
uv run vm import-library ~/OldLibraryFolder
uv run vm install-service
```
It refuses to run while the older app is still serving. It copies the database, notes, training, settings and tokens into `~/VideoMentor` and updates stored paths; if anything fails, it leaves nothing behind. The original folder is never changed, so it stays your backup. Devices pair once more with `vm pair`.

## Where things live
| What | Where |
|---|---|
| Library, notes, tokens, settings | `~/VideoMentor/` (set `VM_HOME` to move it) |
| Settings file | `~/VideoMentor/config.toml` |
| Training modules and rendered videos | `~/VideoMentor/training/` |
| App server | `http://127.0.0.1:8791` (change `port` in the settings file) |
