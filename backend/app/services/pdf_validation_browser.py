"""Render public document controls with Scrapling and guarded cached HTTP resources."""
from datetime import datetime, timezone
from html import escape
import sys
import time
from urllib.parse import urldefrag, urlsplit

from app.config import settings
from app.services.pdf_validation_navigation import navigation
from app.services.pdf_validation_source import SourceSnapshot
from reflink.url.evidence import validate_source_uri


MENU_TRIGGERS = ('nav li, [role="menubar"] > *, [aria-haspopup="true"], [aria-haspopup="menu"], .dropdown, '
                 '.dropdown-toggle, .menu-item-has-children, .has-submenu, .has-dropdown')
EXPANDERS = 'button[aria-expanded="false"], [role="button"][aria-expanded="false"], summary'


def render_navigation(url, hosts, timeout):
    """Open a page in a read-only browser, reveal hover and dropdown menus, and return the resulting HTML."""
    try:
        from scrapling.fetchers import DynamicFetcher
    except ImportError as exc:
        raise ValueError("Browser navigation dependencies are unavailable.") from exc
    deadline = time.monotonic() + min(timeout, settings.PDF_VALIDATION_TIMEOUT_SECONDS, 60)
    captured = {}

    def remaining():
        return max(1, min(30000, (deadline - time.monotonic()) * 1000))

    def setup(page):
        def guard(route):
            request = route.request
            try:
                if request.resource_type in {"image", "font", "media"} or request.method not in {"GET", "HEAD"}:
                    raise ValueError("blocked")
                # Opening a menu must not take the page somewhere else; links are read, not followed.
                if request.is_navigation_request() and request.frame == page.main_frame and captured.get("loaded"):
                    raise ValueError("navigation")
                validate_source_uri(request.url, hosts)
            except Exception:
                route.abort()
                return
            route.continue_()
        page.context.route("**/*", guard)
        page.context.route_web_socket("**/*", lambda socket: socket.close())
        page.context.on("page", lambda popup: popup.close() if popup != page else None)

    def action(page):
        captured["loaded"] = True
        page.set_default_timeout(remaining())
        for locator, limit, act in ((MENU_TRIGGERS, 60, "hover"), (EXPANDERS, 40, "click")):
            controls = page.locator(locator)
            for control in controls.all()[:limit]:
                if time.monotonic() >= deadline:
                    break
                try:
                    if control.is_visible():
                        getattr(control, act)(timeout=1500)
                        page.wait_for_timeout(80)
                except Exception:
                    continue
        captured["html"] = page.content()
        captured["url"] = page.url

    try:
        DynamicFetcher.fetch(url, headless=True, page_setup=setup, page_action=action, timeout=remaining(), retries=1,
            google_search=False, load_dom=True, network_idle=True,
            additional_args={"service_workers": "block", "accept_downloads": False,
                "channel": settings.PDF_VALIDATION_BROWSER_CHANNEL or ("msedge" if sys.platform == "win32" else "chromium")},
            selector_config={"adaptive": False}, extra_flags=["--disable-background-networking"])
    except Exception as exc:
        raise ValueError("The page's interactive navigation could not be opened in the browser.") from exc
    if not captured.get("html"):
        raise ValueError("The browser returned no page content.")
    data = captured["html"].encode("utf-8")
    if len(data) > settings.PDF_VALIDATION_MAX_HTML_BYTES:
        raise ValueError("The rendered page exceeds the HTML size limit.")
    final = urldefrag(captured.get("url") or url)[0]
    validate_source_uri(final, hosts)
    return SourceSnapshot(data, final, "html", "text/html; charset=utf-8", datetime.now(timezone.utc).isoformat())


def render_document(snapshot, hosts, fetch, timeout):
    try:
        from scrapling.fetchers import DynamicFetcher
    except ImportError as exc:
        raise ValueError("Browser collection dependencies are unavailable. Install the backend requirements and a supported browser.") from exc
    deadline = time.monotonic() + min(timeout, settings.PDF_VALIDATION_TIMEOUT_SECONDS)
    rules = settings.PDF_VALIDATION_BROWSER_RULES.get(urlsplit(snapshot.url).hostname or "", {})
    document_nav = navigation(snapshot)
    identity = document_nav["identity"]
    selector = rules.get("content_selector") or (document_nav["content_selector"] if not rules.get("frame_selector") else None) or 'main, article, [data-document-content], #document-content'
    if document_nav["ambiguous_content"] and not (rules.get("content_selector") or rules.get("frame_selector")):
        raise ValueError("Multiple document bodies require an explicit publisher content selector.")
    failures, captures = [], []
    resources = {snapshot.url: snapshot}
    navigation_urls = {snapshot.url}
    requests = size = 0

    def remaining():
        if time.monotonic() >= deadline:
            raise ValueError("Document browser collection timed out.")
        return max(1, min(30000, (deadline - time.monotonic()) * 1000))

    def configure(page):
        def guard(route):
            nonlocal requests, size
            request = route.request
            if request.resource_type in {"image", "font", "media"}:
                route.abort()
                return
            requests += 1
            try:
                if request.method not in {"GET", "HEAD"} or requests > settings.PDF_VALIDATION_BROWSER_MAX_REQUESTS:
                    raise ValueError("A browser request exceeded the read-only request limit.")
                if request.is_navigation_request() and request.frame == page.main_frame and urldefrag(request.url)[0] not in navigation_urls:
                    raise ValueError("The document control navigated to another page; select that document URL directly.")
                validate_source_uri(request.url, hosts)
                resource = resources.get(request.url)
                if resource is None:
                    resource = fetch(request.url, hosts, min(settings.PDF_VALIDATION_MAX_HTML_BYTES,
                        settings.PDF_VALIDATION_CRAWL_MAX_BYTES - size), max(0.001, deadline - time.monotonic()))
                    resources[request.url] = resource
                    resources[resource.url] = resource
                size += len(resource.data)
                if size > settings.PDF_VALIDATION_CRAWL_MAX_BYTES:
                    raise ValueError("Browser response byte limit reached.")
                validate_source_uri(resource.url, hosts)
                if resource.url != request.url:
                    navigation_urls.add(resource.url)
                    route.fulfill(status=302, headers={"location": resource.url})
                else:
                    route.fulfill(status=200, body=resource.data, headers={"content-type": resource.content_type or "text/html"})
            except (ValueError, OSError) as exc:
                failures.append(str(exc)[:200])
                route.abort()
        page.context.route("**/*", guard)
        page.context.route_web_socket("**/*", lambda socket: socket.close())
        page.context.clear_permissions()
        page.context.on("page", lambda popup: popup.close() if popup != page else None)

    def setup(page):
        try:
            configure(page)
        except Exception:
            page.close()
            raise

    def collect(page):
        page.set_default_timeout(remaining())
        scope = page.frame_locator(rules["frame_selector"]) if rules.get("frame_selector") else page
        root = scope.locator(selector).first
        root.wait_for(state="visible", timeout=remaining())
        if root.locator("iframe, embed, object").count():
            raise ValueError("An embedded document requires a configured publisher frame selector.")
        for extra in rules.get("expand_selectors", []):
            controls = root.locator(extra)
            if controls.count() > settings.PDF_VALIDATION_CRAWL_MAX_PAGES:
                raise ValueError("Document expansion limit reached.")
            for control in controls.all():
                if control.is_visible():
                    control.click(timeout=remaining())
        controls = root.locator('details:not([open]) > summary, [data-document-expand][aria-expanded="false"]')
        if controls.count() > settings.PDF_VALIDATION_CRAWL_MAX_PAGES:
            raise ValueError("Document expansion limit reached.")
        for control in controls.all():
            if control.is_visible():
                control.click(timeout=remaining())
        wait = rules.get("ready_selector", 'h1, h2, p, [data-document-section]')
        root.locator(wait).first.wait_for(state="visible", timeout=remaining())
        tabs = root.locator(rules.get("tab_selector", '[role="tab"][aria-controls]'))
        def capture(element, omit_panels=False):
            return element.evaluate("""(element, omitPanels) => {
                const copy = element.cloneNode(true);
                const language = element.closest('[lang]')?.getAttribute('lang');
                if (language) copy.setAttribute('lang', language);
                const sourceLinks = element.querySelectorAll('a[href]');
                copy.querySelectorAll('a[href]').forEach((link, i) => link.setAttribute('href', sourceLinks[i].href));
                if (omitPanels) copy.querySelectorAll('[role="tabpanel"]').forEach(node => node.remove());
                copy.querySelectorAll('button,select,form,script,style,[role="tablist"],[role="tab"]').forEach(node => node.remove());
                return copy.outerHTML;
            }""", omit_panels)
        if tabs.count() > settings.PDF_VALIDATION_CRAWL_MAX_PAGES:
            raise ValueError("Document tab limit reached.")
        if tabs.count():
            captures.append(capture(root, True))
            for tab in tabs.all():
                panel_id = tab.get_attribute("aria-controls")
                if not panel_id or not tab.is_visible():
                    failures.append("A document tab could not be identified.")
                    continue
                tab.click(timeout=remaining())
                panel = scope.locator('[id="' + panel_id.replace('"', '\\"') + '"]').first
                panel.wait_for(state="visible", timeout=remaining())
                panel.locator(rules.get("panel_ready_selector", 'p, h1, h2, [data-document-section]')).first.wait_for(state="visible", timeout=remaining())
                captures.append(capture(panel))
        else:
            captures.append(capture(root))
        if root.locator('select, canvas, iframe, [aria-expanded="false"]').count():
            failures.append("Some document controls require a configured publisher adapter.")
        if sum(len(item.encode()) for item in captures) > settings.PDF_VALIDATION_MAX_HTML_BYTES:
            raise ValueError("Rendered document exceeds the HTML size limit.")

    def action(page):
        try:
            collect(page)
        except Exception as exc:
            failures.append(str(exc)[:200] if isinstance(exc, ValueError) else "Document navigation or readiness checks did not complete.")

    try:
        DynamicFetcher.fetch(snapshot.url, headless=True, page_setup=setup, page_action=action,
            timeout=remaining(), retries=1, google_search=False, load_dom=True, network_idle=False,
            additional_args={"service_workers": "block", "accept_downloads": False,
                "channel": settings.PDF_VALIDATION_BROWSER_CHANNEL or ("msedge" if sys.platform == "win32" else "chromium")},
            selector_config={"adaptive": False},
            executable_path=rules.get("executable_path") if rules.get("executable_path") else None,
            extra_flags=["--disable-background-networking"])
    except Exception as exc:
        raise ValueError("The interactive document could not be fully collected. Check browser installation and publisher navigation settings.") from exc
    if not captures:
        raise ValueError("The browser returned no document sections.")
    metadata = ''.join(f'<meta name="{name}" content="{escape(identity[key], quote=True)}">'
        for name, key in (("document-id", "document_id"), ("document-version", "edition")) if identity.get(key))
    html = ('<html lang="' + escape(identity.get("language", ""), quote=True) + '"><head>' + metadata
        + '</head><body><main data-document-content>' + "\n".join(captures) + '</main></body></html>').encode()
    return SourceSnapshot(html, snapshot.url, "html", "text/html; charset=utf-8",
        datetime.now(timezone.utc).isoformat()), not failures, list(dict.fromkeys(failures))
