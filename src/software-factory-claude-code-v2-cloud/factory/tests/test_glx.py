"""glx against a fake GitLab server: commands, JSON shape, pagination, drafts, merge."""
import json
import os
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.machinery import SourceFileLoader
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BIN = Path(__file__).resolve().parents[1] / "bin"
P = "/api/v4/projects/g%2Fp"

USER = {"username": "leo"}
ISSUE = {"iid": 7, "title": "Add booking", "description": "body", "author": USER,
         "labels": ["factory", "x"], "state": "opened", "web_url": "http://gl/g/p/-/issues/7"}
MR = {"iid": 3, "title": "Draft: Add booking", "state": "opened", "draft": True,
      "web_url": "http://gl/g/p/-/merge_requests/3", "source_branch": "factory/007", "target_branch": "main"}
NOTES = {"1": [{"system": True, "author": USER, "body": "added label", "created_at": "t0"},
               {"system": False, "author": USER, "body": "hello", "created_at": "t1"}],
         "2": [{"system": False, "author": USER, "body": "again", "created_at": "t2"}]}


class Fake(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *a):
        pass

    def reply(self, obj, headers=None):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_any(self):
        u = urlparse(self.path)
        qs = {k: v[0] for k, v in parse_qs(u.query).items()}
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n)) if n else None
        Fake.calls.append((self.command, u.path, qs, body, self.headers.get("PRIVATE-TOKEN")))
        m, p = self.command, u.path
        if (m, p) == ("GET", "/api/v4/user"):
            return self.reply(USER)
        if (m, p) == ("GET", f"{P}/issues/7"):
            return self.reply(ISSUE)
        if (m, p) == ("GET", f"{P}/issues/7/notes"):
            page = qs.get("page", "1")
            return self.reply(NOTES[page], {"X-Next-Page": "2"} if page == "1" else None)
        if (m, p) == ("GET", f"{P}/issues"):
            return self.reply([ISSUE])
        if (m, p) in (("POST", f"{P}/issues/7/notes"), ("POST", f"{P}/merge_requests/3/notes"),
                      ("PUT", f"{P}/issues/7"), ("PUT", f"{P}/merge_requests/3/merge")):
            return self.reply({})
        if (m, p) == ("GET", f"{P}/merge_requests"):
            return self.reply([MR])
        if (m, p) == ("GET", f"{P}/merge_requests/3"):
            return self.reply(MR)
        if (m, p) == ("POST", f"{P}/merge_requests"):
            return self.reply({"web_url": MR["web_url"]})
        if (m, p) == ("PUT", f"{P}/merge_requests/3"):
            MR.update({k: v for k, v in body.items() if k == "title"})
            if body.get("title") is not None:
                MR["draft"] = body["title"].startswith("Draft")
            return self.reply({})
        self.send_response(404)
        self.end_headers()

    do_GET = do_POST = do_PUT = handle_any


class GlxTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.env = {**os.environ, "GHX_TRANSPORT": "gitlab", "GITLAB_TOKEN": "tok",
                   "GITLAB_URL": f"http://127.0.0.1:{cls.srv.server_port}", "GITLAB_PROJECT": "g/p"}
        cls.env.pop("HTTPS_PROXY", None)
        cls.env["NO_PROXY"] = "127.0.0.1"
        cls.env.pop("HTTP_PROXY", None)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        Fake.calls.clear()
        MR["title"], MR["draft"] = "Draft: Add booking", True

    def ghx(self, *args, ok=True):
        r = subprocess.run([sys.executable, str(BIN / "ghx"), *args], env=self.env, capture_output=True, text=True)
        if ok:
            self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def test_operator_login(self):
        self.assertEqual(self.ghx("api", "user", "--jq", ".login").stdout.strip(), "leo")
        self.assertEqual(Fake.calls[0][4], "tok")

    def test_issue_view_shape_and_pagination(self):
        out = json.loads(self.ghx("issue", "view", "7", "--json", "number,title,body,author,labels,state,url,comments").stdout)
        self.assertEqual(out["number"], 7)
        self.assertEqual(out["author"], {"login": "leo"})
        self.assertEqual(out["labels"], [{"name": "factory"}, {"name": "x"}])
        self.assertEqual(out["state"], "OPEN")
        # the system note is dropped; both pages are read
        self.assertEqual([c["body"] for c in out["comments"]], ["hello", "again"])

    def test_issue_list_filters(self):
        out = json.loads(self.ghx("issue", "list", "--label", "factory", "--state", "open", "--limit", "200", "--json", "number,title").stdout)
        self.assertEqual(out, [{"number": 7, "title": "Add booking"}])
        _, _, qs, _, _ = Fake.calls[0]
        self.assertEqual((qs["state"], qs["labels"]), ("opened", "factory"))

    def test_comment_and_labels(self):
        self.ghx("issue", "comment", "7", "--body", "hi")
        self.ghx("issue", "edit", "7", "--add-label", "a", "--remove-label", "b,c")
        self.ghx("pr", "comment", "3", "--body", "mr note")
        calls = [(m, p, b) for m, p, _, b, _ in Fake.calls]
        self.assertIn(("POST", f"{P}/issues/7/notes", {"body": "hi"}), calls)
        self.assertIn(("PUT", f"{P}/issues/7", {"add_labels": "a", "remove_labels": "b,c"}), calls)
        self.assertIn(("POST", f"{P}/merge_requests/3/notes", {"body": "mr note"}), calls)

    def test_pr_view_by_branch_and_number(self):
        by_branch = json.loads(self.ghx("pr", "view", "factory/007", "--json", "state,isDraft,number").stdout)
        self.assertEqual(by_branch, {"state": "OPEN", "isDraft": True, "number": 3})
        by_number = json.loads(self.ghx("pr", "view", "3", "--json", "headRefName,baseRefName").stdout)
        self.assertEqual(by_number, {"headRefName": "factory/007", "baseRefName": "main"})

    def test_pr_list_head(self):
        out = json.loads(self.ghx("pr", "list", "--head", "factory/007", "--state", "open", "--json", "number,url").stdout)
        self.assertEqual(out, [{"number": 3, "url": MR["web_url"]}])
        self.assertEqual(Fake.calls[0][2]["source_branch"], "factory/007")

    def test_pr_create_draft_gets_prefix(self):
        url = self.ghx("pr", "create", "--draft", "--base", "main", "--head", "factory/007",
                       "--title", "Add booking", "--body", "Closes #7").stdout.strip()
        self.assertEqual(url, MR["web_url"])
        body = Fake.calls[0][3]
        self.assertEqual((body["title"], body["source_branch"], body["target_branch"]),
                         ("Draft: Add booking", "factory/007", "main"))

    def test_ready_strips_draft_then_merge_succeeds(self):
        self.ghx("pr", "ready", "3")
        self.assertIn(("PUT", f"{P}/merge_requests/3", {"title": "Add booking"}),
                      [(m, p, b) for m, p, _, b, _ in Fake.calls])
        self.ghx("pr", "merge", "3", "--merge")
        self.assertEqual(Fake.calls[-1][:2], ("PUT", f"{P}/merge_requests/3/merge"))
        self.assertEqual(Fake.calls[-1][3], {"squash": False})

    def test_merge_refuses_draft_and_rebase(self):
        r = self.ghx("pr", "merge", "3", "--merge", ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("draft", r.stderr)
        r = self.ghx("pr", "merge", "3", "--rebase", ok=False)
        self.assertIn("rebase", r.stderr)

    def test_unsupported_and_missing_token(self):
        self.assertIn("isn't supported", self.ghx("release", "list", ok=False).stderr)
        env = {k: v for k, v in self.env.items() if k != "GITLAB_TOKEN"}
        r = subprocess.run([sys.executable, str(BIN / "ghx"), "issue", "list"], env=env, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("GITLAB_TOKEN", r.stderr)


class ProjectPathTest(unittest.TestCase):
    def project_for(self, url):
        import importlib.util
        from importlib.machinery import SourceFileLoader
        from importlib.util import module_from_spec, spec_from_loader
        from unittest import mock
        env = {k: v for k, v in os.environ.items() if k != "GITLAB_PROJECT"}
        with mock.patch.dict(os.environ, env, clear=True):
            glx = module_from_spec(spec_from_loader("glx", SourceFileLoader("glx", str(BIN / "glx"))))
            glx.__spec__.loader.exec_module(glx)
            glx.CONFIG.pop("gitlab_project", None)
            fake = subprocess.CompletedProcess([], 0, stdout=url + "\n")
            with mock.patch.object(glx.subprocess, "run", return_value=fake):
                return glx.project()

    def test_origin_urls(self):
        for url, want in [
            ("https://gitlab.example.com/g/p.git", "g%2Fp"),
            ("https://oauth2:tok@gitlab.example.com/g/sub/p.git", "g%2Fsub%2Fp"),
            ("git@gitlab.example.com:g/p.git", "g%2Fp"),
            ("ssh://git@gitlab.example.com/g/sub/p", "g%2Fsub%2Fp"),
        ]:
            self.assertEqual(self.project_for(url), want, url)


if __name__ == "__main__":
    unittest.main()
