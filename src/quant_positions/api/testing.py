"""Thin WSGI test-client wrapper matching the FastAPI TestClient interface.

This lets existing tests change only the import line when switching
from FastAPI to Bottle.
"""
from __future__ import annotations

from webtest import TestApp


class _Response:
    __slots__ = ("_resp", "status_code")

    def __init__(self, webtest_response):
        self._resp = webtest_response
        self.status_code = webtest_response.status_int

    def json(self):
        return self._resp.json


class WSGIClient:
    __test__ = False  # prevent pytest collection

    def __init__(self, app):
        self._app = TestApp(app)

    def get(self, url: str, *, params=None):
        resp = self._app.get(url, params=params, expect_errors=True)
        return _Response(resp)

    def post(self, url: str, *, json=None):
        import json as _json
        resp = self._app.post_json(url, json or {}, expect_errors=True)
        return _Response(resp)


# Alias used by all test files.
TestClient = WSGIClient
