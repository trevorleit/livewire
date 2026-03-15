# LiveWire Stabilization Test Plan

## Phase 9 done checklist
- Dashboard loads with accurate machine, alert, group, and scheduled job counters
- Header and navigation are visually stable across all pages
- Group creation works
- Group membership add and remove works
- Machine-targeted scheduled jobs work
- Group-targeted scheduled jobs work
- Auto-approve works
- Only-when-online works
- Scheduler run history records properly
- No schema mismatches appear on startup
- Testing notes are written down as issues are found

## Scheduler behavior for testing
- Scheduler ticks are now manual during testing
- Due jobs should only run when the operator clicks **Run Scheduler Tick**
- Normal page loads should not queue scheduler-created remote commands
- Manual **Run Now** should only execute the selected scheduled job

## Core checks
- Agent check-in updates machine `last_seen` and online state
- Offline threshold flips machine to offline and creates alert
- Recovery flips machine back online and resolves alert
- Scheduler can create, run, enable, and disable jobs
- Response rules can queue commands for matching alerts
- Notification test writes a notification log row
- Service restart commands accept friendly names like Apache and MySQL

## Manual scenarios
1. Start Flask app and agent
2. Confirm dashboard cards update
3. Confirm dashboard group counter and job counters display correctly
4. Confirm nav active state is correct on Dashboard, Alerts, Response Center, Events, Actions, Automation, Inventory, and Settings
5. Create a machine group
6. Add a machine to the group
7. Remove the machine from the group
8. Create a scheduled job for one machine
9. Confirm the job target label is readable, such as `Machine: DEV-SRV-01`
10. Click **Run Now** and confirm one command queue entry is created
11. Create a scheduled job for a group
12. Confirm the job target label is readable, such as `Group: Web Servers`
13. Click **Run Scheduler Tick** and confirm only due jobs are queued
14. Confirm disabled jobs do not run
15. Confirm offline targets are skipped when `only_when_online` is enabled
16. Confirm scheduler run history records queued vs skipped counts
17. Create a remediation rule for `service_down`
18. Stop a watched service or simulate `not_found`
19. Confirm alert, remediation run, and queued command
20. Send a test notification from Settings and Response Center

## Notes
- Use a test machine or safe command targets when validating scheduler behavior
- Record any duplicate command creation immediately, since that would indicate a scheduler execution bug
- Record any mismatched target labels immediately, since that would indicate an automation display bug