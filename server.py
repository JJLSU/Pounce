from __future__ import annotations

import html
import os
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote
from uuid import uuid4
from email.parser import BytesParser
from email.policy import default


DEFAULT_UPLOAD_DIR = Path(__file__).resolve().parent / "uploaded_games"
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
MAX_UPLOAD_SIZE = 5 * 1024 * 1024


class UploadTooLargeError(Exception):
    pass


def normalize_filename(filename: str) -> str:
    candidate = Path(filename).name
    stem = SAFE_NAME_RE.sub("-", Path(candidate).stem).strip(".-") or "game"
    suffix = Path(candidate).suffix.lower()
    return f"{stem}-{uuid4().hex[:8]}{suffix}"


class GameRequestHandler(BaseHTTPRequestHandler):
    server_version = "PounceHTTP/1.0"

    @property
    def max_upload_size(self) -> int:
        return getattr(self.server, "max_upload_size", MAX_UPLOAD_SIZE)

    def do_GET(self) -> None:
        if self.path == "/":
            self._serve_index()
            return

        if self.path.startswith("/games/"):
            self._serve_game()
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        if self.path != "/upload":
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/form-data"):
            self.send_error(HTTPStatus.BAD_REQUEST, "Expected multipart/form-data")
            return

        try:
            uploaded_file = self._parse_uploaded_file(content_type)
        except UploadTooLargeError:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "HTML file is too large")
            return

        if uploaded_file is None:
            self.send_error(HTTPStatus.BAD_REQUEST, "Missing game file")
            return

        original_name, file_contents = uploaded_file
        if Path(original_name).suffix.lower() not in {".html", ".htm"}:
            self.send_error(HTTPStatus.BAD_REQUEST, "Only HTML files are supported")
            return

        target_name = normalize_filename(original_name)
        target_path = self.upload_dir / target_name
        target_path.write_bytes(file_contents)

        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", f"/games/{target_name}")
        self.end_headers()

    @property
    def upload_dir(self) -> Path:
        return getattr(self.server, "upload_dir", DEFAULT_UPLOAD_DIR)

    def _parse_uploaded_file(self, content_type: str) -> tuple[str, bytes] | None:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            return None
        if content_length > self.max_upload_size:
            raise UploadTooLargeError

        message = BytesParser(policy=default).parsebytes(
            (
                f"Content-Type: {content_type}\r\n"
                "MIME-Version: 1.0\r\n\r\n"
            ).encode("utf-8")
            + self.rfile.read(content_length)
        )
        if not message.is_multipart():
            return None

        for part in message.iter_parts():
            if part.get_param("name", header="content-disposition") != "game":
                continue
            filename = part.get_filename()
            if not filename:
                return None
            return filename, part.get_payload(decode=True) or b""

        return None

    def _serve_index(self) -> None:
        games = sorted(
            game.name
            for game in [*self.upload_dir.glob("*.html"), *self.upload_dir.glob("*.htm")]
            if self._resolve_game_path(game.name) is not None
        )
        links = "".join(
            f'<li><a href="/games/{html.escape(game)}">{html.escape(game)}</a></li>'
            for game in games
        )
        page = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Pounce Game Upload</title>
  </head>
  <body>
    <h1>Upload a web game</h1>
    <form action="/upload" method="post" enctype="multipart/form-data">
      <input type="file" name="game" accept=".html,.htm" required>
      <button type="submit">Upload</button>
    </form>
    <h2>Uploaded games</h2>
    <ul>{links or "<li>No games uploaded yet.</li>"}</ul>
  </body>
</html>
"""
        body = page.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _resolve_game_path(self, filename: str) -> Path | None:
        target_path = self.upload_dir / filename
        try:
            resolved_target = target_path.resolve(strict=True)
        except FileNotFoundError:
            return None

        if (
            resolved_target.parent != self.upload_dir.resolve()
            or resolved_target.suffix.lower() not in {".html", ".htm"}
        ):
            return None

        return resolved_target

    def _serve_game(self) -> None:
        filename = Path(unquote(self.path.removeprefix("/games/"))).name
        if not filename:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        resolved_target = self._resolve_game_path(filename)
        if resolved_target is None:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        body = resolved_target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def create_server(host: str = "127.0.0.1", port: int = 8000, upload_dir: Path | None = None) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), GameRequestHandler)
    server.upload_dir = upload_dir or DEFAULT_UPLOAD_DIR
    server.max_upload_size = MAX_UPLOAD_SIZE
    server.upload_dir.mkdir(parents=True, exist_ok=True)
    return server


def main() -> None:
    host = os.environ.get("POUNCE_HOST", "127.0.0.1")
    port = int(os.environ.get("POUNCE_PORT", "8000"))
    upload_dir = Path(os.environ.get("POUNCE_UPLOAD_DIR", DEFAULT_UPLOAD_DIR))
    server = create_server(host=host, port=port, upload_dir=upload_dir)
    browser_host = "127.0.0.1" if host == "0.0.0.0" else host
    print(f"Serving uploaded games on http://{browser_host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
