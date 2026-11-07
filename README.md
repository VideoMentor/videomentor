<p align="center"><img src="docs/brand/videomentor-banner.png" alt="VideoMentor: turn the videos you save into skills you use" width="100%"></p>

# VideoMentor

**Turn the videos you save into skills you use.** VideoMentor is a private app you run on your own computer. It collects the YouTube videos you've saved, lets you triage them one card at a time on your phone, writes notes you can act on for the keepers, and builds short training lessons out of exact clips from many videos.

Free and open source under the [GNU AGPL-3.0](LICENSE).

## What it does
| Stage | What happens |
|---|---|
| **Collect** | Syncs Watch Later, the playlists you choose and YouTube links in your browser bookmarks. Read-only: it never changes anything on YouTube. |
| **Triage** | One card at a time: keep, archive, analyze first, or group related videos. Undo up to 20 steps. Pull extra videos from any channel (newest, oldest or a date range, with Shorts and live streams as switches). |
| **Understand** | Kept videos get notes from their transcripts: the core idea, frameworks, one to three "try this week" actions, and a key moment with a timestamp checked against the real captions. |
| **Apply** | An actions checklist, and training modules made of clips with exercises and a quiz. Play a module as one lesson in the app, or render it as a narrated video for your own use. |

It runs as a web app on your computer and installs on your phone's home screen. It works on iPhone, iPad and Mac, in portrait or landscape.

## What you need
- macOS (Linux and Windows support is not there yet: the background service, Safari bookmarks and the narration voice are macOS-only).
- Python 3.12 and [uv](https://docs.astral.sh/uv/), Node 20 or later.
- A Google account with YouTube, signed in to YouTube in Chrome.
- The [Claude Code](https://docs.anthropic.com/en/docs/claude-code) command-line tool, signed in. VideoMentor uses it for tags, scores, notes and training, on your own Claude plan.
- Optional: ffmpeg and Google Chrome, for rendered training videos.
- [Tailscale](https://tailscale.com/) on your Mac and phone, to use the app on your phone (without it, it works in the Mac's browser only).

Setup takes about 30 minutes: see **[docs/setup.md](docs/setup.md)**.

## Quick start
```sh
uv sync
cd web && npm install && npm run build && cd ..
uv run vm sync      # first sync, from Terminal (reads your browser's YouTube login)
uv run vm serve     # then open http://127.0.0.1:8791 on the Mac; for your phone see docs/setup.md
```

## Commands (`vm`)
| Command | Does |
|---|---|
| `vm sync` | Pull Watch Later, playlists that are on and bookmarked YouTube links, then fetch details. Run it from Terminal: the background service can't read browser data, so this also saves a login copy for it. |
| `vm prep` | Write card summaries, topics, tags and a signal score for new videos. |
| `vm analyze` | Write notes for queued videos. |
| `vm status` | Library counts and last sync. |
| `vm playlists` | List playlists; turn syncing on or off. |
| `vm youtube-login` | Sign in to the YouTube Data API (read-only) for playlist dates and channel pulls. |
| `vm train "<tag>"` | Build a training module from kept videos with that tag. |
| `vm render <module>` | Render a module as one narrated video (personal use only, see below). |
| `vm tags` | Review proposed tag merges; `--draft` suggests new ones. |
| `vm transcripts` | Keep transcripts for analyzed videos that don't have one. |
| `vm export` | Rewrite every video's Markdown notes. |
| `vm pair [--new]` | Show the pairing link and 12-digit code for a phone; `--new` makes a new code. |
| `vm devices [--sign-out ID \| --sign-out-all]` | List paired devices, or sign one or all out (also on Status > Paired devices). |
| `vm serve` | Run the app and its background worker. |
| `vm install-service` / `uninstall-service` | Start `vm serve` at login (macOS). |
| `vm --version` | Version and build. |

Your library lives in `~/VideoMentor/` (set `VM_HOME` to move it). Nothing in it is ever sent anywhere except the YouTube and Claude requests the features need.

## Please read: YouTube and your own use
- VideoMentor reads YouTube two ways: the official YouTube Data API (read-only) with your own Google Cloud client, and [yt-dlp](https://github.com/yt-dlp/yt-dlp) using your browser's YouTube login. yt-dlp access is common in open-source tools but sits outside YouTube's API terms. You run VideoMentor on your own account, at your own risk.
- **Rendered training videos download clips. They are for your personal use only. Don't share or publish them:** the clips belong to their creators. The in-app lesson player plays clips in YouTube's own player and downloads nothing.
- VideoMentor is not affiliated with or endorsed by YouTube or Google.

## Develop
```sh
uv sync
uv run pytest
uv run ruff check src tests
cd web && npm install && npm test && npx tsc --noEmit && npm run build
```
See [CONTRIBUTING.md](CONTRIBUTING.md).

## License and name
Code: [GNU Affero General Public License v3.0](LICENSE). You may use, study, change and share VideoMentor, including commercially. If you distribute a changed version, or run one as a service for others, you must publish your changes under the same license.

The VideoMentor name and logo are not covered by the code license: see [TRADEMARKS.md](TRADEMARKS.md).

Copyright 2026 Christopher Larkin.
