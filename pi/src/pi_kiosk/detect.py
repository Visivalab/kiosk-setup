def looks_like_raspberry_pi(*, model: str | None, has_rpi_issue: bool) -> bool:
    if has_rpi_issue:
        return True
    if model and "raspberry pi" in model.lower():
        return True
    return False
