# ⚡ LiveWire

<p align="center">
  <img src="static/img/LiveWire_logo.png" width="260" alt="LiveWire Logo">
</p>

<p align="center">
<b>Lightweight Infrastructure Monitoring & Automated Response Platform</b>
</p>

<p align="center">
Real-time telemetry • alert detection • automation • remote command execution
</p>

<p align="center">

![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![Flask](https://img.shields.io/badge/framework-flask-lightgrey)
![Status](https://img.shields.io/badge/status-active%20development-orange)
![License](https://img.shields.io/badge/license-learning%20project-green)

</p>

---

# Overview

**LiveWire** is a lightweight infrastructure monitoring and response platform designed for internal networks, homelabs, and small operational environments.

It provides a centralized dashboard that monitors machines running a lightweight agent and enables administrators to:

* Monitor system health
* Detect operational issues
* Trigger automated remediation
* Execute remote commands
* Track events and alerts in real time

LiveWire is designed to be:

• Simple to deploy
• Lightweight and fast
• Automation-focused
• Easy to extend

---

# 🚧 Project Status

**LiveWire is currently under active development.**

Features are continuously being improved and expanded.
Expect frequent updates, new capabilities, and architectural refinements.

This repository represents a **working development build**.

---

# Dashboard Preview

<p align="center">
  <img src="static/images/dashboardview.jpg" width="900">
</p>

The dashboard provides real-time operational visibility including:

* machine health
* system telemetry
* alerts
* command activity
* automation status
* event history

---

# Architecture

<p align="center">
  <img src="static/images/workflow.png" width="800">
</p>

LiveWire follows a simple service architecture built around lightweight agents reporting telemetry to a centralized Flask application.

Core system flow:

```
Agent
  ↓
API
  ↓
Database
  ↓
Alert Engine
  ↓
Automation Engine
  ↓
Command Center
  ↓
Dashboard
```

---

# Key Features

### Infrastructure Monitoring

LiveWire agents collect telemetry including:

* CPU usage
* Memory usage
* Disk utilization
* Network throughput
* Running processes
* Service states
* System uptime
* Machine connectivity status

Telemetry updates automatically appear in the dashboard.

---

### Alert Detection

Incoming telemetry is evaluated against configurable thresholds.

When thresholds are exceeded LiveWire can:

* generate alerts
* log events
* trigger automation rules
* queue remediation commands

---

### Automation Engine

Automation rules allow the system to automatically respond to issues.

Example:

```
IF CPU > 95% for 5 minutes
THEN restart_service
```

Automation enables environments to **self-correct common operational problems**.

---

### Remote Command Center

Administrators can issue commands directly to monitored machines.

Examples:

```
restart_service
stop_process
reboot_machine
```

Commands are queued and executed by the LiveWire agent.

---

# Project Structure

```
livewire/
│
├── app.py
├── config.py
├── database.py
├── requirements.txt
├── README.md
│
├── agents/
│   └── agent.py
│
├── routes/
│   ├── dashboard.py
│   ├── machines.py
│   ├── alerts.py
│   ├── actions.py
│   ├── automation.py
│   └── api.py
│
├── services/
│   ├── alert_engine.py
│   ├── command_center.py
│   ├── group_service.py
│   ├── runtime_settings.py
│   └── helpers.py
│
├── templates/
├── static/
└── instance/
```

---

# Installation

### Clone the Repository

```
git clone https://github.com/YOURUSERNAME/livewire.git
cd livewire
```

---

### Create Virtual Environment

Windows

```
python -m venv venv
venv\Scripts\activate
```

Linux / Mac

```
python3 -m venv venv
source venv/bin/activate
```

---

### Install Dependencies

```
pip install -r requirements.txt
```

---

### Start the LiveWire Server

```
python app.py
```

The dashboard will start at:

```
http://localhost:5000
```

---

# Running the LiveWire Agent

The agent collects telemetry from machines and sends it to the LiveWire server.

Open:

```
agents/agent.py
```

Set the server and API key:

```python
SERVER_URL = "http://your-server-ip:5000"
API_KEY = "your-api-key"
```

Then start the agent:

```
python agents/agent.py
```

The machine will automatically appear in the LiveWire dashboard.

---

# Security

Agents authenticate using an API key.

All telemetry and command requests require valid authentication.

---

# Database

LiveWire uses SQLite by default.

Database location:

```
instance/dashboard.db
```

Future versions may support additional database backends.

---

# Development

Run LiveWire in development mode:

```
python app.py
```

Flask automatically reloads when code changes.

---

# Future Development

Planned improvements include:

* WebSocket real-time updates
* notification integrations
* advanced alert rules
* role-based authentication
* automation workflow builder
* historical metrics visualization
* agent auto-update capability
* plugin architecture

---

# Author

**Trevor Elliott**
Green Tee Design

---

# License

This project is provided as a learning and experimentation platform for infrastructure automation and monitoring systems.
