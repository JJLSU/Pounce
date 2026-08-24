import http.client
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from server import create_server


def build_multipart(filename: str, content: bytes, field_name: str = "game") -> tuple[str, bytes]:
    boundary = f"----PounceBoundary{uuid4().hex}"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
        "Content-Type: text/html\r\n\r\n"
    ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    return boundary, body


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.upload_dir = Path(self.temp_dir.name)
        self.server = create_server(port=0, upload_dir=self.upload_dir)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def request(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response, data

    def test_upload_redirects_and_serves_uploaded_game(self) -> None:
        game_html = b"<!doctype html><html><body><h1>Pounce!</h1></body></html>"
        boundary, body = build_multipart("game.html", game_html)

        response, _ = self.request(
            "POST",
            "/upload",
            body=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
            },
        )

        self.assertEqual(response.status, 303)
        location = response.getheader("Location")
        self.assertIsNotNone(location)
        self.assertTrue(location.startswith("/games/game-"))

        response, served_body = self.request("GET", location)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "text/html; charset=utf-8")
        self.assertEqual(served_body, game_html)

    def test_upload_rejects_non_html_files(self) -> None:
        boundary, body = build_multipart("game.js", b"alert('nope');")

        response, _ = self.request(
            "POST",
            "/upload",
            body=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
            },
        )

        self.assertEqual(response.status, 400)

    def test_upload_rejects_files_over_size_limit(self) -> None:
        boundary, body = build_multipart("game.html", b"<html>too big</html>")

        with patch("server.MAX_UPLOAD_SIZE", 10):
            response, _ = self.request(
                "POST",
                "/upload",
                body=body,
                headers={
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "Content-Length": str(len(body)),
                },
            )

        self.assertEqual(response.status, 413)

    @unittest.skipIf(os.name == "nt", "symlink permissions vary on Windows")
    def test_server_does_not_follow_symlinked_html_files(self) -> None:
        external_file = self.upload_dir.parent / "outside.html"
        external_file.write_text("<html>outside</html>", encoding="utf-8")
        symlink_path = self.upload_dir / "linked.html"
        symlink_path.symlink_to(external_file)

        response, _ = self.request("GET", "/games/linked.html")

        self.assertEqual(response.status, 404)


if __name__ == "__main__":
    unittest.main()
