# Rules for Island Pill (Python + GTK3 + Cairo, Linux Mint Cinnamon X11)
- Keep it light: no new dependencies, no web views, no new polling timers. Memory must stay near 22 MB.
- Make only the change I ask for. No unrelated refactors or renames.
- After every change run `python3 -m pytest -q` and show me the result. All tests must pass.
- Never edit `island_pill.py.opencode-bridge-backup`, `install-opencode.sh` or `island-pill-notify.js` unless I ask.
- To see a change on screen, run `bash install.sh`.
- Coucou is only a visual inspiration. Do not copy its code, artwork or sounds.
- After changing island-pill-notify.js also run: node --check island-pill-notify.js && node --test
