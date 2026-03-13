LiveWire - Phase 7.5 fixed additive patch

Built specifically around your current Hotfix 6.1 machine detail layout.

What this adds:
- Quick Actions panel at the top of the machine detail page
- Recent Commands panel at the top of the machine detail page
- better command output display on /actions
- redirect back to the machine page after queuing quick actions
- CSS for quick action cards and result boxes

Files included:
- routes/actions.py
- templates/actions.html
- templates/machine_detail.html
- static/phase75_actions.css
- base_head_snippet.txt

Apply:
1. Back up C:\xampp\htdocs\livewire
2. Copy these files into the project
3. Add the stylesheet line from base_head_snippet.txt into templates/base.html inside <head>
4. Restart python app.py

This patch preserves your current Hotfix 6.1 stats layout and only adds the new command center panels.
