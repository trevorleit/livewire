LiveWire Phase 9 Patch

This phase adds:
- Machine groups
- Scheduled automation jobs
- Scheduler run history
- Automation page and nav
- Group badges on dashboard and machine detail
- Scheduler-driven command creation

Apply by copying these files into your existing LiveWire project root.
Restart Flask after copying.

Notes:
- On first app startup, init_db() will create the new tables automatically.
- Scheduled jobs are processed during page loads on dashboard, actions, automation, and machine detail routes.
- This avoids adding a separate background worker for now.
