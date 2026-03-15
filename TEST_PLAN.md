# LiveWire Stabilization Test Plan

## Core checks
- Agent check-in updates machine last_seen and online state
- Offline threshold flips machine to offline and creates alert
- Recovery flips machine back online and resolves alert
- Scheduler can create, run, enable, and disable jobs
- Response rules can queue commands for matching alerts
- Notification test writes a notification log row
- Service restart commands accept friendly names like Apache and MySQL

## Manual scenarios
1. Start Flask app and agent
2. Confirm dashboard cards update
3. Disable agent to trigger offline
4. Re-enable agent to confirm recovery
5. Create a scheduler rule for a test machine
6. Run job now and confirm command queue entry
7. Create a remediation rule for `service_down`
8. Stop a watched service or simulate `not_found`
9. Confirm alert, remediation run, and queued command
10. Send a test notification from Settings and Response Center
