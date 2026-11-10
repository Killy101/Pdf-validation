"""Identify source access barriers before PDF discovery or comparison."""
from html import unescape
import re


CAPTCHA_MESSAGE = ("The website requires CAPTCHA or browser verification. Its document could not be accessed automatically. "
                   "Open the website to review the source manually, or use an accessible direct PDF URL.")


class SourceAccessError(ValueError):
    def __init__(self, issue: str, message: str):
        super().__init__(message)
        self.issue = issue


def access_issue(data: bytes):
    if data.startswith(b"%PDF-"):
        return None
    html = data[:131072].decode("utf-8", errors="replace").casefold()
    headings = re.findall(r"<(?:title|h1)\b[^>]*>(.*?)</(?:title|h1)>", html, re.S)
    headings = [" ".join(unescape(re.sub(r"<[^>]+>", " ", item)).split()) for item in headings]
    challenge = r"^(?:just a moment[.!\s\u2026]*|(?:please )?(?:verify|confirm|prove).{0,40}(?:human|not a robot).*|captcha(?: challenge| verification| required)?|human verification|security (?:check|verification)|checking (?:your )?browser.*|attention required(?:!|\s*\|.*)?)$"
    if any(re.search(challenge, item) for item in headings):
        return "captcha"
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", html, flags=re.S)
    text = " ".join(unescape(re.sub(r"<[^>]+>", " ", text)).split())
    widget = re.search(r"g-recaptcha|h-captcha|cf-turnstile|recaptcha/api|challenges\.cloudflare\.com/turnstile", html)
    prompt = re.search(r"(?:complete|solve) (?:the |this )?captcha|verify (?:that )?you (?:are|are not) (?:a )?(?:human|robot)", text)
    if widget and prompt and len(text) < 1500:
        return "captcha"
    if any(re.fullmatch(r"access denied|request (?:blocked|rejected)|forbidden|sign in|log in|login required|authentication required", item) for item in headings):
        return "access_denied"
    if any(re.fullmatch(r"too many requests|rate limit(?: exceeded)?", item) for item in headings):
        return "rate_limited"
    return None


def ensure_source_access(snapshot):
    if snapshot.kind != "html":
        return
    issue = access_issue(snapshot.data)
    if issue:
        message = CAPTCHA_MESSAGE if issue == "captcha" else (
            "The website is limiting automated requests. Wait and try again, or use an accessible direct PDF URL."
            if issue == "rate_limited" else
            "The website returned an access restriction or sign-in page. Open the website to check your access, or use an accessible direct PDF URL.")
        raise SourceAccessError(issue, message)


def http_access_error(error):
    headers = error.headers or {}
    if headers.get("cf-mitigated") == "challenge":
        error.close()
        return SourceAccessError("captcha", CAPTCHA_MESSAGE)
    try:
        data = error.read(131072) if error.fp and not getattr(error.fp, "closed", False) else b""
        issue = access_issue(data)
        if issue == "captcha":
            return SourceAccessError("captcha", CAPTCHA_MESSAGE)
        if issue == "access_denied":
            return SourceAccessError("access_denied", "The website returned an access restriction or sign-in page. Open the website to check your access, or use an accessible direct PDF URL.")
    except OSError:
        pass
    finally:
        error.close()
    if error.code in {401, 403}:
        return SourceAccessError("access_denied", f"The website denied access (HTTP {error.code}). It may require sign-in, CAPTCHA, or permission. Open the website to review it manually, or use an accessible direct PDF URL.")
    if error.code == 429:
        return SourceAccessError("rate_limited", "The website is limiting requests (HTTP 429). Wait and try again, or use an accessible direct PDF URL.")
    return SourceAccessError("unavailable", f"The website returned HTTP {error.code}. Its document could not be accessed. Check the URL or try again later.")
