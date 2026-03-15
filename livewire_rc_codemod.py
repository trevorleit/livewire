from __future__ import annotations

import os
import re
import sys
import shutil
from pathlib import Path
from datetime import datetime, UTC

ROOT_EXCLUDES = {
    '.git', '__pycache__', 'venv', '.venv', 'node_modules', 'instance',
    'dist', 'build', '.mypy_cache', '.pytest_cache'
}
TEXT_EXTS = {'.py', '.html', '.jinja', '.j2', '.txt', '.md'}

CANONICAL_NOTIFICATION_SQL = '''rows = conn.execute("""
    SELECT
        id,
        created_at,
        notification_type,
        channel,
        status,
        recipient,
        subject,
        message,
        related_alert_id,
        related_rule_id,
        details_json
    FROM notification_logs
    ORDER BY datetime(created_at) DESC, id DESC
    LIMIT 100
""").fetchall()'''

CANONICAL_REMEDIATION_SQL = '''rows = conn.execute("""
    SELECT
        id,
        name,
        description,
        enabled,
        machine_role,
        trigger_type,
        severity,
        metric_name,
        comparison_operator,
        threshold_value,
        cooldown_seconds,
        action_type,
        action_payload_json,
        auto_approve,
        created_at,
        updated_at
    FROM remediation_rules
    ORDER BY name ASC, id DESC
""").fetchall()'''

FIELD_RENAMES = [
    # notifications
    (r'\bnotification_kind\b', 'notification_type'),
    (r'\bkind\b', 'notification_type'),
    (r'\balert_id\b', 'related_alert_id'),
    (r'\brule_id\b', 'related_rule_id'),
    (r'\bmeta_json\b', 'details_json'),
    (r'\bmetadata_json\b', 'details_json'),
    (r'\bsent_at\b', 'created_at'),
    (r'\bcreated_on\b', 'created_at'),
    (r'\bdelivery_channel\b', 'channel'),
    (r'\bdelivery_status\b', 'status'),
    # remediation
    (r'\bis_enabled\b', 'enabled'),
    (r'\bcooldown_minutes\b', 'cooldown_seconds'),
    (r'\bupdated_on\b', 'updated_at'),
    (r'\brule_name\b', 'name'),
    (r'\bhost_role\b', 'machine_role'),
]

REPORT_HEADERS = [
    'FILE', 'CHANGED', 'NOTES'
]


def utc_stamp() -> str:
    return datetime.now(UTC).strftime('%Y%m%d_%H%M%S')


def should_skip(path: Path) -> bool:
    return any(part in ROOT_EXCLUDES for part in path.parts)



def iter_text_files(root: Path):
    for path in root.rglob('*'):
        if path.is_file() and path.suffix.lower() in TEXT_EXTS and not should_skip(path):
            yield path



def read_text(path: Path) -> str:
    return path.read_text(encoding='utf-8', errors='ignore')



def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding='utf-8', newline='')



def backup_file(root: Path, path: Path, backup_root: Path) -> None:
    rel = path.relative_to(root)
    dest = backup_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)



def patch_app_py(content: str) -> tuple[str, list[str], bool]:
    notes: list[str] = []
    changed = False

    if 'from database import ensure_rc_schema' not in content:
        lines = content.splitlines()
        insert_at = 0
        for i, line in enumerate(lines):
            if line.startswith('import ') or line.startswith('from '):
                insert_at = i + 1
        lines.insert(insert_at, 'from database import ensure_rc_schema')
        content = '\n'.join(lines) + ('\n' if content.endswith('\n') else '')
        notes.append('added ensure_rc_schema import')
        changed = True

    if 'ensure_rc_schema()' not in content:
        patterns = [
            r'(^\s*app\s*=\s*Flask\([^\n]*\)\s*$)',
            r'(^\s*def\s+create_app\s*\([^\)]*\):\s*$)',
        ]
        inserted = False

        # Insert after app = Flask(...)
        m = re.search(patterns[0], content, flags=re.M)
        if m:
            insert_pos = m.end()
            content = content[:insert_pos] + '\nensure_rc_schema()' + content[insert_pos:]
            notes.append('inserted ensure_rc_schema() after app initialization')
            changed = True
            inserted = True
        else:
            # If app factory, inject before return app
            factory_match = re.search(patterns[1], content, flags=re.M)
            return_match = re.search(r'^(\s*)return\s+app\s*$', content, flags=re.M)
            if factory_match and return_match:
                indent = return_match.group(1)
                insert_pos = return_match.start()
                content = content[:insert_pos] + f'{indent}ensure_rc_schema()\n' + content[insert_pos:]
                notes.append('inserted ensure_rc_schema() in app factory before return app')
                changed = True
                inserted = True

        if not inserted:
            notes.append('TODO: could not place ensure_rc_schema() automatically')

    return content, notes, changed



def patch_common_imports(content: str) -> tuple[str, list[str], bool]:
    notes: list[str] = []
    changed = False

    needed = {
        'insert_notification_log': 'from database import insert_notification_log',
        'list_notification_logs': 'from database import list_notification_logs, get_notification_log',
        'insert_remediation_rule': 'from database import remediation_rule_from_form, validate_remediation_rule_payload, insert_remediation_rule, update_remediation_rule, list_remediation_rules, get_remediation_rule',
    }

    for marker, import_line in needed.items():
        if marker in content and import_line not in content and 'from database import' not in content:
            lines = content.splitlines()
            insert_at = 0
            for i, line in enumerate(lines):
                if line.startswith('import ') or line.startswith('from '):
                    insert_at = i + 1
            lines.insert(insert_at, import_line)
            content = '\n'.join(lines) + ('\n' if content.endswith('\n') else '')
            notes.append(f'added database import for {marker}')
            changed = True
            break

    return content, notes, changed



def patch_notification_insert_blocks(content: str) -> tuple[str, list[str], bool]:
    notes: list[str] = []
    changed = False

    patterns = [
        re.compile(
            r'''conn\.execute\(\s*[ru]?(["\']){3}\s*INSERT\s+INTO\s+notification_logs\s*\((?P<cols>.*?)\)\s*VALUES\s*\((?P<vals>.*?)\)\s*\1{3}\s*,\s*\((?P<args>.*?)\)\s*\)''',
            re.I | re.S,
        ),
    ]

    def repl(match: re.Match) -> str:
        nonlocal changed
        changed = True
        notes.append('replaced direct notification_logs INSERT with helper call')
        args = match.group('args').strip()
        return (
            'insert_notification_log(\n'
            '    notification_type=notification_type if \"notification_type\" in locals() else \"alert\",\n'
            '    channel=channel if \"channel\" in locals() else \"ui\",\n'
            '    status=status if \"status\" in locals() else \"sent\",\n'
            '    recipient=recipient if \"recipient\" in locals() else None,\n'
            '    subject=subject if \"subject\" in locals() else None,\n'
            '    message=message if \"message\" in locals() else None,\n'
            '    related_alert_id=related_alert_id if \"related_alert_id\" in locals() else None,\n'
            '    related_rule_id=related_rule_id if \"related_rule_id\" in locals() else None,\n'
            '    details=details if \"details\" in locals() else None,\n'
            ')' 
            f'  # TODO verify removed SQL args: ({args})'
        )

    for pattern in patterns:
        content = pattern.sub(repl, content)

    return content, notes, changed



def patch_notification_reads(content: str) -> tuple[str, list[str], bool]:
    notes: list[str] = []
    changed = False

    if 'FROM notification_logs' in content and 'list_notification_logs(' not in content:
        # Replace only simple known assignment patterns.
        content_new, n = re.subn(
            r'\b\w+\s*=\s*conn\.execute\(\s*[ru]?(["\']){3}.*?FROM\s+notification_logs.*?fetchall\(\)\s*',
            'logs = list_notification_logs(limit=100)',
            content,
            flags=re.I | re.S,
        )
        if n:
            content = content_new
            notes.append('replaced notification_logs SELECT with list_notification_logs()')
            changed = True

    return content, notes, changed



def patch_remediation_reads(content: str) -> tuple[str, list[str], bool]:
    notes: list[str] = []
    changed = False

    if 'FROM remediation_rules' in content and 'list_remediation_rules(' not in content:
        content_new, n = re.subn(
            r'\b\w+\s*=\s*conn\.execute\(\s*[ru]?(["\']){3}.*?FROM\s+remediation_rules.*?fetchall\(\)\s*',
            'rules = list_remediation_rules()',
            content,
            flags=re.I | re.S,
        )
        if n:
            content = content_new
            notes.append('replaced remediation_rules SELECT with list_remediation_rules()')
            changed = True

    return content, notes, changed



def patch_form_patterns(content: str) -> tuple[str, list[str], bool]:
    notes: list[str] = []
    changed = False

    create_pattern = re.compile(
        r'(?P<indent>\s*)(?P<var>\w+)\s*=\s*request\.form.*?(?=\n\S|\Z)',
        re.S,
    )

    if 'request.form' in content and 'insert_remediation_rule(**data)' not in content and 'update_remediation_rule(related_rule_id=related_rule_id, **data)' not in content:
        if 'remediation_rules' in content or 'Response Center' in content or 'Automation' in content:
            # Add a helper snippet instead of risky full rewrite.
            snippet = (
                '\n# RC schema helper pattern\n'
                'data = remediation_rule_from_form(request.form)\n'
                'errors = validate_remediation_rule_payload(data)\n'
                'if errors:\n'
                '    return {"ok": False, "errors": errors}, 400\n'
                '# For create:\n'
                '# related_rule_id = insert_remediation_rule(**data)\n'
                '# return {"ok": True, "related_rule_id": related_rule_id}\n'
                '# For update:\n'
                '# update_remediation_rule(related_rule_id=related_rule_id, **data)\n'
                '# return {"ok": True, "related_rule_id": related_rule_id}\n'
            )
            if '# RC schema helper pattern' not in content:
                content += '\n' + snippet
                notes.append('appended remediation helper snippet for manual route swap')
                changed = True

    return content, notes, changed



def patch_canonical_sql_snippets(content: str) -> tuple[str, list[str], bool]:
    notes: list[str] = []
    changed = False

    if 'notification_logs' in content and 'details_json' not in content and 'FROM notification_logs' in content:
        content += '\n\n# Canonical notification_logs query\n' + CANONICAL_NOTIFICATION_SQL + '\n'
        notes.append('appended canonical notification_logs SQL snippet')
        changed = True

    if 'remediation_rules' in content and 'action_payload_json' not in content and 'FROM remediation_rules' in content:
        content += '\n\n# Canonical remediation_rules query\n' + CANONICAL_REMEDIATION_SQL + '\n'
        notes.append('appended canonical remediation_rules SQL snippet')
        changed = True

    return content, notes, changed



def apply_field_renames(content: str) -> tuple[str, list[str], bool]:
    notes: list[str] = []
    changed = False
    original = content

    # Careful: don't blindly replace generic "type"/"state"/"metric"/"operator"/"threshold" everywhere.
    for pattern, repl in FIELD_RENAMES:
        content, n = re.subn(pattern, repl, content)
        if n:
            notes.append(f'renamed {pattern} -> {repl} ({n})')
            changed = True

    # SQL-specific safer replacements for generic legacy names.
    sql_pairs = [
        (' notification_type,', ' notification_type,'),
        (' type\n', ' notification_type\n'),
        (' metric_name,', ' metric_name,'),
        (' comparison_operator,', ' comparison_operator,'),
        (' threshold_value,', ' threshold_value,'),
        (' action_payload_json', ' action_payload_json'),
    ]
    for old, new in sql_pairs:
        content, n = re.subn(re.escape(old), new, content)
        if n:
            notes.append(f'replaced SQL token {old.strip()} -> {new.strip()} ({n})')
            changed = True

    return content, notes, changed



def patch_file(root: Path, path: Path) -> tuple[bool, list[str], str]:
    original = read_text(path)
    content = original
    notes: list[str] = []
    changed = False

    if path.name == 'app.py':
        content, n, c = patch_app_py(content)
        notes.extend(n)
        changed = changed or c

    content, n, c = patch_common_imports(content)
    notes.extend(n)
    changed = changed or c

    content, n, c = patch_notification_insert_blocks(content)
    notes.extend(n)
    changed = changed or c

    content, n, c = patch_notification_reads(content)
    notes.extend(n)
    changed = changed or c

    content, n, c = patch_remediation_reads(content)
    notes.extend(n)
    changed = changed or c

    content, n, c = patch_form_patterns(content)
    notes.extend(n)
    changed = changed or c

    content, n, c = patch_canonical_sql_snippets(content)
    notes.extend(n)
    changed = changed or c

    content, n, c = apply_field_renames(content)
    notes.extend(n)
    changed = changed or c

    # Flag remaining suspicious legacy terms for manual review.
    suspects = [
        'type', 'related_alert_id', 'related_rule_id', 'payload_json', 'metric', 'operator', 'threshold',
        'cooldown_seconds', 'enabled', 'request.form', 'INSERT INTO notification_logs',
        'FROM notification_logs', 'FROM remediation_rules'
    ]
    remaining = [s for s in suspects if s in content]
    if remaining:
        notes.append('manual review remaining tokens: ' + ', '.join(sorted(set(remaining))))

    if changed and content != original:
        return True, notes, content
    return False, notes, original



def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd().resolve()
    if not root.exists():
        print(f'[error] Root not found: {root}')
        return 1

    backup_root = root / f'_rc_codemod_backup_{utc_stamp()}'
    report_lines = []
    changed_count = 0
    reviewed_count = 0

    for path in iter_text_files(root):
        reviewed_count += 1
        changed, notes, content = patch_file(root, path)
        if changed:
            backup_file(root, path, backup_root)
            write_text(path, content)
            changed_count += 1
        if notes:
            report_lines.append((str(path.relative_to(root)), 'yes' if changed else 'no', ' | '.join(notes)))

    report_path = root / f'_rc_codemod_report_{utc_stamp()}.txt'
    with report_path.open('w', encoding='utf-8') as f:
        f.write(f'LiveWire RC codemod report\n')
        f.write(f'Root: {root}\n')
        f.write(f'Backups: {backup_root}\n')
        f.write(f'Files reviewed: {reviewed_count}\n')
        f.write(f'Files changed: {changed_count}\n\n')
        f.write('FILE | CHANGED | NOTES\n')
        f.write('-' * 120 + '\n')
        for row in report_lines:
            f.write(' | '.join(row) + '\n')

    print(f'[done] Reviewed {reviewed_count} files')
    print(f'[done] Changed {changed_count} files')
    print(f'[done] Backups saved to: {backup_root}')
    print(f'[done] Report saved to: {report_path}')
    print('[note] This codemod is best-effort. Review the report and grep for remaining legacy tokens before commit.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
