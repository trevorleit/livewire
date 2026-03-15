import re

SERVICE_ALIASES = {
    "apache": ["apache2.4", "apache24", "apache", "httpd"],
    "mysql": ["mysql", "mysql80", "mariadb", "mysqld"],
    "spooler": ["spooler", "print spooler", "printspooler"],
}


def normalize_service_label(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").strip().lower())



def candidate_service_names(name: str):
    raw = (name or "").strip()
    norm = normalize_service_label(raw)
    if not norm:
        return []

    candidates = [raw]
    seen = {normalize_service_label(raw)}

    for values in SERVICE_ALIASES.values():
        normalized_values = {normalize_service_label(v) for v in values}
        if norm in normalized_values:
            for value in values:
                n = normalize_service_label(value)
                if n not in seen:
                    seen.add(n)
                    candidates.append(value)
            break

    return candidates
