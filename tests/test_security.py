import secrets
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.db import (
    admin_password_is_ready,
    db_session,
    get_user,
    initialize,
    save_user,
    set_account_password,
    update_user_account,
)
from app.main import app, startup
from app.security import hash_password


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_database_path = settings.database_path
        self.original_secret_key = settings.secret_key
        object.__setattr__(settings, "database_path", Path(self.temporary_directory.name) / "security.sqlite3")
        object.__setattr__(settings, "secret_key", secrets.token_urlsafe(48))
        initialize()
        set_account_password("admin", hash_password("AdminTestPassword2026!"))
        save_user("viewer_test", "Usuario de prueba", hash_password("ViewerTestPassword2026!"), "viewer", None)
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        object.__setattr__(settings, "database_path", self.original_database_path)
        object.__setattr__(settings, "secret_key", self.original_secret_key)
        self.temporary_directory.cleanup()

    def test_admin_requires_rotation_and_password_is_not_reset_by_initialization(self):
        self.assertTrue(admin_password_is_ready())
        original_hash = get_user("admin")["password_hash"]
        initialize()
        self.assertEqual(get_user("admin")["password_hash"], original_hash)

    def test_application_rejects_missing_session_secret(self):
        object.__setattr__(settings, "secret_key", "")
        with self.assertRaises(RuntimeError):
            startup()

    def test_application_requires_admin_rotation_before_startup(self):
        with db_session() as connection:
            connection.execute("UPDATE users SET password_ready = 0 WHERE username = 'admin'")
        with self.assertRaises(RuntimeError):
            startup()
        set_account_password("admin", hash_password("OtraClaveSegura2026!"))
        startup()

    def test_browser_role_change_cannot_grant_server_permissions(self):
        response = self.client.post(
            "/api/login",
            json={"username": "viewer_test", "password": "ViewerTestPassword2026!"},
        )
        self.assertEqual(response.status_code, 200)
        csrf = response.json()["csrf_token"]
        self.assertEqual(self.client.get("/api/admin/users").status_code, 403)
        self.assertEqual(self.client.get("/api/attention/foreign-id/history").status_code, 404)
        self.assertEqual(self.client.get("/api/exports/completed-plans").status_code, 404)
        self.assertEqual(
            self.client.put(
                "/api/attention/foreign-id/plan",
                headers={"X-CSRF-Token": csrf},
                json={"status": "concluido", "completion_confirmed": True, "plan_text": "Cambio"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/api/admin/users",
                headers={"X-CSRF-Token": csrf},
                json={
                    "username": "intruso", "full_name": "Usuario intruso",
                    "password": "PasswordDePrueba2026!", "role": "admin",
                },
            ).status_code,
            403,
        )

    def test_role_change_invalidates_existing_session(self):
        response = self.client.post(
            "/api/login",
            json={"username": "viewer_test", "password": "ViewerTestPassword2026!"},
        )
        self.assertEqual(response.status_code, 200)
        update_user_account("viewer_test", "Usuario de prueba", "gerente_general", "")
        self.assertEqual(self.client.get("/api/me").status_code, 401)

    def test_modified_session_cookie_cannot_change_identity(self):
        response = self.client.post(
            "/api/login",
            json={"username": "viewer_test", "password": "ViewerTestPassword2026!"},
        )
        self.assertEqual(response.status_code, 200)
        signed_cookie = self.client.cookies.get("atencion_session")
        self.assertTrue(signed_cookie)
        self.client.cookies.set("atencion_session", "x" + signed_cookie)
        self.assertEqual(self.client.get("/api/admin/users").status_code, 401)

    def test_password_guessing_is_throttled(self):
        for _ in range(5):
            response = self.client.post(
                "/api/login",
                json={"username": "viewer_test", "password": "incorrecta"},
            )
            self.assertEqual(response.status_code, 401)
        response = self.client.post(
            "/api/login",
            json={"username": "viewer_test", "password": "ViewerTestPassword2026!"},
        )
        self.assertEqual(response.status_code, 429)

    def test_missing_csrf_and_security_headers(self):
        self.client.post(
            "/api/login",
            json={"username": "viewer_test", "password": "ViewerTestPassword2026!"},
        )
        response = self.client.post("/api/logout", json={})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertIn("script-src 'self'", response.headers["content-security-policy"])


if __name__ == "__main__":
    unittest.main()
