"""Jinja2-based rendering for outbound email templates."""
from jinja2 import Environment, FileSystemLoader, select_autoescape

from config import TEMPLATES_DIR

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(disabled_extensions=("txt",)),
)


def render_template(name: str, context: dict) -> dict:
    """Renders templates/<name>.txt. First line is treated as the subject
    (prefixed with 'Subject: '), the rest as the body."""
    template = _env.get_template(f"{name}.txt")
    rendered = template.render(**context)
    lines = rendered.splitlines()
    subject = ""
    body_lines = lines
    if lines and lines[0].lower().startswith("subject:"):
        subject = lines[0].split(":", 1)[1].strip()
        body_lines = lines[1:]
        if body_lines and not body_lines[0].strip():
            body_lines = body_lines[1:]
    return {"subject": subject, "body": "\n".join(body_lines)}
