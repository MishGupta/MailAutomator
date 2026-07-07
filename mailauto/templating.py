def parse_template(text: str) -> tuple:
    lines = text.splitlines()
    if not lines or not lines[0].lower().startswith("subject:"):
        raise ValueError("Template must start with 'Subject: ...' on the first line")
    subject_template = lines[0].split(":", 1)[1].strip()
    rest = lines[1:]
    i = 0
    while i < len(rest) and rest[i].strip() == "":
        i += 1
    body_template = "\n".join(rest[i:])
    return subject_template, body_template


def _fill(template: str, contact) -> str:
    return (template
            .replace("{name}", contact.name)
            .replace("{company}", contact.company)
            .replace("{title}", contact.title)
            .replace("{email}", contact.email))


def render(subject_template: str, body_template: str, contact) -> tuple:
    return _fill(subject_template, contact), _fill(body_template, contact)
