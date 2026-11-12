import re


def upsert_marked_block(original: str, begin: str, end: str, body: str) -> str:
    """Insert or replace a tagged block. Leaves every other line alone."""
    block = f"{begin}\n{body.rstrip()}\n{end}\n"
    if begin in original and end in original:
        pre, rest = original.split(begin, 1)
        _, post = rest.split(end, 1)
        if post.startswith("\n"):
            post = post[1:]
        return pre + block + post
    if original and not original.endswith("\n"):
        original += "\n"
    return original + block


def read_or_empty(host, path: str) -> str:
    if not host.exists(path):
        return ""
    return host.read_file(path)


def normalize_labwc_rc_xml(original: str) -> str:
    """Convert Pi OS's legacy openbox root to labwc so later inserts stay valid XML."""
    if "<labwc_config" in original:
        return original

    converted = re.sub(r"<openbox_config(\b[^>]*)>", r"<labwc_config\1>", original, count=1)
    if converted != original:
        return converted.replace("</openbox_config>", "</labwc_config>", 1)

    self_closing = re.sub(
        r"<openbox_config(\b[^>]*)/\s*>",
        r"<labwc_config\1>\n</labwc_config>",
        original,
        count=1,
    )
    return self_closing


_RC_XML_HEADER = '<?xml version="1.0"?>\n<labwc_config>\n'
_RC_XML_FOOTER = "</labwc_config>\n"


def upsert_labwc_rc_block(original: str, begin: str, end: str, body: str) -> str:
    """Insert or replace a tagged block inside labwc's rc.xml, creating the file if empty."""
    original = normalize_labwc_rc_xml(original)
    block = f"{begin}\n{body}\n{end}"
    if not original.strip():
        return f"{_RC_XML_HEADER}{block}\n{_RC_XML_FOOTER}"
    if begin in original and end in original:
        pre, rest = original.split(begin, 1)
        _, post = rest.split(end, 1)
        if post.startswith("\n"):
            post = post[1:]
        return f"{pre}{block}\n{post}"
    closing = "</labwc_config>"
    if closing in original:
        before, after = original.rsplit(closing, 1)
        if before and not before.endswith("\n"):
            before += "\n"
        return f"{before}{block}\n{closing}{after}"
    if original and not original.endswith("\n"):
        original += "\n"
    return f"{original}{block}\n"


def remove_marked_lines(original: str, begin: str, end: str) -> str:
    """Drop every line from the one with `begin` through the one with `end`."""
    kept: list[str] = []
    inside = False
    for line in original.splitlines(keepends=True):
        if begin in line:
            inside = True
        if not inside:
            kept.append(line)
        if end in line:
            inside = False
    return "".join(kept)
