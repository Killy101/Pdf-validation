"""Inspect ZIP members and collect declared HTML chapters without network access."""
import base64
from io import BytesIO
import json
from pathlib import PurePosixPath
import sys
import time
import unicodedata
from urllib.parse import quote, unquote, urldefrag, urlsplit
from zipfile import BadZipFile, ZIP_BZIP2, ZIP_DEFLATED, ZIP_LZMA, ZIP_STORED, ZipFile


ORIGIN = "https://archive.invalid/"


def inspect_archive(payload):
    from app.services.pdf_validation_source import SourceSnapshot
    deadline = time.monotonic() + payload["timeout"]
    data = base64.b64decode(payload["data"], validate=True)
    if len(data) > payload["max_bytes"]:
        raise ValueError("The ZIP download exceeds the configured size limit.")
    with ZipFile(BytesIO(data)) as archive:
        members = archive.infolist()
        if len(members) > payload["max_files"]:
            raise ValueError("The ZIP contains too many entries.")
        if sum(item.file_size for item in members) > payload["max_expanded_bytes"]:
            raise ValueError("The ZIP expands beyond the configured size limit.")
        files, seen, entries, unsupported = {}, set(), [], []
        for item in members:
            name = item.orig_filename
            path = PurePosixPath(name)
            if (not name or len(name) > 2048 or "\\" in name or name.startswith("/")
                    or any(part in {"", ".", ".."} for part in name.rstrip("/").split("/"))
                    or ":" in name or any(ord(char) < 32 for char in name)):
                raise ValueError("The ZIP contains an unsafe member path.")
            key = unicodedata.normalize("NFKC", name.rstrip("/")).casefold()
            if key in seen:
                raise ValueError("The ZIP contains duplicate member paths.")
            seen.add(key)
            mode = (item.external_attr >> 16) & 0o170000
            if mode not in {0, 0o100000, 0o040000}:
                raise ValueError("The ZIP contains a symbolic link or unsupported file type.")
            if item.flag_bits & 1:
                raise ValueError("Encrypted ZIP members cannot be validated.")
            if item.compress_type not in {ZIP_STORED, ZIP_DEFLATED, ZIP_BZIP2, ZIP_LZMA}:
                raise ValueError("The ZIP uses an unsupported compression method.")
            if item.is_dir():
                continue
            files[name] = item
            kind = "pdf" if path.suffix.lower() == ".pdf" else "html" if path.suffix.lower() in {".html", ".htm"} else None
            if kind:
                entries.append({"name": name, "kind": kind})
            else:
                unsupported.append(name)
        result = {"entries": entries, "unsupported": unsupported}
        if payload["discover"]:
            return result
        selected = payload.get("member")
        if selected is None and len(entries) == 1:
            selected = entries[0]["name"]
        entry = next((item for item in entries if item["name"] == selected), None)
        if selected and entry is None:
            raise ValueError("Select a supported PDF or HTML member listed in this ZIP.")
        if entry is None:
            return result
        expanded, cache = 0, {}

        def read(name):
            nonlocal expanded
            if name in cache:
                return cache[name]
            if name not in files:
                raise ValueError("The declared archive chapter is missing or outside the selected archive.")
            limit = payload["max_bytes"] if name.lower().endswith(".pdf") else payload["max_html_bytes"]
            if files[name].file_size > limit:
                raise ValueError("The selected archive member exceeds the configured document size limit.")
            parts, size = [], 0
            with archive.open(files[name]) as source:
                while True:
                    if time.monotonic() >= deadline:
                        raise ValueError("ZIP extraction reached its time limit.")
                    part = source.read(min(65536, limit + 1 - size))
                    if not part:
                        break
                    parts.append(part)
                    size += len(part)
                    expanded += len(part)
                    if size > limit or expanded > payload["max_expanded_bytes"]:
                        raise ValueError("ZIP extraction exceeds the configured expanded size limit.")
            cache[name] = b"".join(parts)
            return cache[name]

        content = read(selected)
        kind = entry["kind"]
        if kind == "pdf" and not content.startswith(b"%PDF-"):
            raise ValueError("The selected archive member is not a PDF document.")
        if kind == "html":
            from app.services.pdf_validation_collection import collect_document

            def local_fetch(url, hosts, max_bytes, timeout):
                parsed = urlsplit(url)
                if parsed.scheme != "https" or parsed.netloc != "archive.invalid" or parsed.query:
                    raise ValueError("External archive resources are not retrieved. Select an accessible document URL.")
                name = unquote(parsed.path.lstrip("/"))
                body = read(name)
                if len(body) > max_bytes:
                    raise ValueError("The archive chapter exceeds the collection size limit.")
                if PurePosixPath(name).suffix.lower() not in {".html", ".htm"}:
                    raise ValueError("A required archive chapter has an unsupported format. Select its document separately.")
                return SourceSnapshot(body, url, "html", "text/html")

            def no_browser(*args):
                raise ValueError("Interactive archived content cannot be executed. Select a readable PDF or HTML document.")

            root = local_fetch(ORIGIN + quote(selected, safe="/"), (), payload["max_html_bytes"], payload["timeout"])
            document = collect_document(root, ("archive.invalid",), local_fetch, render=no_browser)

            def public_url(value):
                target, fragment = urldefrag(value)
                if target.startswith(ORIGIN):
                    name = unquote(urlsplit(target).path.lstrip("/"))
                    return payload["url"] + "#archive-member=" + quote(name, safe="") + ("&section=" + quote(fragment, safe="") if fragment else "")
                return value

            for unit in document["units"]:
                unit["archive_member"] = unquote(urlsplit(unit.get("url", root.url)).path.lstrip("/"))
                unit["url"] = public_url(unit.get("url", root.url))
            for section in document["source_coverage"]["sections"]:
                section["label"] = unquote(urlsplit(section["url"]).path.lstrip("/")) + ": " + section["label"]
                section["url"] = public_url(section["url"])
            document["source_coverage"]["method"] = "zip_html"
            document["references"] = []
            result["html"] = document
        result.update(member=selected, kind=kind, data=base64.b64encode(content).decode("ascii"))
        return result


def main():
    try:
        from app.services.pdf_validation_limits import limit_memory
        payload = json.load(sys.stdin)
        limit_memory(payload["memory_mb"])
        result = inspect_archive(payload)
    except (BadZipFile, RuntimeError, NotImplementedError, EOFError):
        result = {"error": "The ZIP is corrupt, encrypted, or uses unsupported compression."}
    except ValueError as exc:
        result = {"error": str(exc)}
    except Exception:
        result = {"error": "The ZIP could not be read within its resource limits. Use a direct document URL."}
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
