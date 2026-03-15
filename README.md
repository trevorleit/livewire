# LiveWire

**LiveWire** is a lightweight internal infrastructure monitoring and
response platform designed to monitor machines, detect system issues,
generate alerts, and execute automated remediation or remote commands.

LiveWire is built for **small‑to‑medium internal environments, labs, and
homelabs** where large monitoring stacks such as Nagios, Zabbix, or
Datadog are unnecessary.

It combines:

-   Machine telemetry monitoring
-   Alert detection
-   Automated remediation
-   Remote command execution
-   Notification delivery
-   Operational visibility dashboards

All inside a **single Python Flask application**.

------------------------------------------------------------------------

# Overview

LiveWire monitors machines running the LiveWire agent and collects:

-   CPU usage
-   RAM usage
-   Disk usage
-   Network throughput
-   Running processes
-   Service states
-   System uptime
-   Machine connectivity status

Incoming telemetry is evaluated against configurable thresholds. When a
threshold is exceeded LiveWire can:

1.  Generate an alert
2.  Notify operators
3.  Execute remediation rules
4.  Queue remote commands
5.  Record events and metrics

------------------------------------------------------------------------

# Core Architecture

Agent → API → Database → Alert Engine → Remediation → Notifications →
Dashboard

### Agent

A lightweight monitoring agent runs on each machine and periodically
sends telemetry data to the LiveWire server.

### API

Flask REST endpoints accept telemetry data and provide queued commands
to agents.

### Database

SQLite is currently used for persistence.

Tables include:

-   machines
-   alerts
-   events
-   telemetry
-   commands
-   automation_jobs
-   remediation_rules
-   notification_logs
-   settings

### Alert Engine

The alert engine evaluates system state against configured thresholds.

Example triggers:

-   CPU above threshold
-   RAM above threshold
-   Disk above threshold
-   Service stopped
-   Machine offline

### Remediation Engine

Automated rules can respond to alerts.

Example:

If `service_down` → restart service.

### Command Queue

Operators can manually queue commands to machines. Agents periodically
poll the server and execute approved commands.

### Notification System

Alerts can trigger notifications through:

-   Discord webhook
-   Email (SMTP)

------------------------------------------------------------------------

# Features

## Dashboard

Provides a real‑time overview of infrastructure.

Displays:

-   Total machines
-   Online machines
-   Offline machines
-   Active alerts
-   Automation job status

Machine cards display:

-   Hostname
-   IP address
-   Logged‑in user
-   CPU usage
-   RAM usage
-   Network throughput
-   GPU information
-   Temperature
-   Last seen timestamp

Usage metrics are displayed with **meter bars** and charts.

------------------------------------------------------------------------

## Alerts

Alerts are generated automatically when thresholds are exceeded.

Each alert includes:

-   Status (OPEN / RESOLVED)
-   Severity
-   Machine
-   Alert notification_type
-   Message
-   Notification count
-   Remediation count
-   Timestamps

Common alert types:

-   cpu_high
-   ram_high
-   disk_high
-   service_down
-   machine_offline

------------------------------------------------------------------------

## Events

The Events page provides a detailed activity log of system events
including:

-   Service monitoring events
-   Automation runs
-   Agent telemetry changes
-   System alerts

This serves as a system audit trail.

------------------------------------------------------------------------

## Remote Actions

Operators can queue commands to machines.

Supported actions include:

-   Restart service
-   Stop service
-   Kill process
-   Reboot system

Commands enter a **pending queue** until approved and executed by
agents.

------------------------------------------------------------------------

## Automation

Automation allows scheduled operational tasks.

Components:

### Machine Groups

Machines can be grouped for easier automation targeting.

### Scheduled Jobs

Jobs can execute commands automatically.

Example tasks:

-   Restart services nightly
-   Clean temporary files
-   Rotate logs

------------------------------------------------------------------------

## Response Center

The Response Center manages automated remediation rules triggered by
alerts.

Example rule:

Alert Type: `service_down`\
Action: `restart service Apache2.4`

Rules may include execution delays and conditions.

------------------------------------------------------------------------

## Inventory

The inventory system provides machine metadata.

Fields include:

-   Display name
-   Role
-   Location
-   Notes

This allows better organization of monitored machines.

------------------------------------------------------------------------

## Settings

System behavior is configurable through the Settings panel.

### Monitoring Thresholds

-   CPU alert threshold
-   RAM alert threshold
-   Disk alert threshold
-   Temperature alert threshold
-   Offline detection timeout

### Dashboard Behavior

-   Auto refresh interval
-   Top processes displayed

### Notification Settings

-   Discord webhook
-   Email recipients
-   SMTP server configuration

Test notifications can be sent from the interface.

------------------------------------------------------------------------

# User Interface

LiveWire uses a **dark monitoring dashboard theme** designed for
operational environments.

UI features:

-   Card‑based layout
-   Real‑time metrics
-   Meter bars for percentage metrics
-   Color‑coded alerts
-   Responsive layout

Primary accent color:

`#00cc66`

Used across:

-   charts
-   meter bars
-   highlights
-   buttons

------------------------------------------------------------------------

# Technology Stack

Backend

-   Python
-   Flask
-   SQLite

Frontend

-   HTML
-   CSS
-   Jinja Templates
-   JavaScript

Communication

-   REST API
-   JSON telemetry payloads

------------------------------------------------------------------------

# Project Structure

    livewire/
    │
    ├── app.py
    ├── database.py
    │
    ├── routes/
    │   ├── dashboard.py
    │   ├── alerts.py
    │   ├── events.py
    │   ├── machines.py
    │   ├── inventory.py
    │   ├── automation.py
    │   ├── actions.py
    │   ├── response_center.py
    │   ├── settings.py
    │   └── api.py
    │
    ├── services/
    │   ├── alert_engine.py
    │   ├── remediation_service.py
    │   ├── notification_service.py
    │   ├── scheduler_service.py
    │   ├── runtime_settings.py
    │   ├── helpers.py
    │   └── phase10_migrations.py
    │
    ├── templates/
    ├── static/
    └── README.md

------------------------------------------------------------------------

# Running LiveWire

### Install dependencies

    pip install flask requests

### Run the server

    python app.py

Default server address:

    http://localhost:5000

------------------------------------------------------------------------

# Development Status

Current phase:

**Feature complete -- entering stabilization and testing phase**

Working modules:

-   Dashboard
-   Alerts
-   Events
-   Remote Actions
-   Automation framework
-   Response Center
-   Notifications
-   Inventory management
-   Runtime settings

------------------------------------------------------------------------

# Upcoming Work

## Final Development

-   UI polish across pages
-   Scheduler UX improvements
-   Service detection improvements
-   Additional automation rule options

## Testing Phase

Testing will include:

-   Agent connectivity tests
-   Alert generation validation
-   Notification delivery verification
-   Remediation execution validation
-   Command queue behavior
-   Offline detection reliability
-   Performance tests

------------------------------------------------------------------------

# Long Term Vision

Possible future improvements:

-   Role‑based access control
-   Multi‑tenant support
-   Plugin monitoring modules
-   Container monitoring
-   Advanced alert escalation
-   Distributed monitoring nodes
-   Agent auto‑updates

------------------------------------------------------------------------

# License

Internal / private project.
