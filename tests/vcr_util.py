"""VCR cassettes for collector tests: gzip JSON under tests/cassettes, replay-only unless
NMT_VCR_RECORD=1. Secrets are stripped from headers and query strings before saving."""

from __future__ import annotations

import gzip
import os
from pathlib import Path

import vcr
from vcr.serialize import deserialize, serialize

from nmt_engine.collect.base import scrub_payload

CASSETTES = Path(__file__).parent / "cassettes"
SECRET_QUERY = ["key", "api_key", "app_key", "app_id", "client_secret", "token", "access_token"]


class GzipPersister:
    @staticmethod
    def load_cassette(cassette_path, serializer):
        path = Path(cassette_path)
        if not path.is_file():
            raise vcr.persisters.filesystem.CassetteNotFoundError()
        return deserialize(gzip.decompress(path.read_bytes()).decode("utf-8"), serializer)

    @staticmethod
    def save_cassette(cassette_path, cassette_dict, serializer):
        path = Path(cassette_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = serialize(cassette_dict, serializer).encode("utf-8")
        path.write_bytes(gzip.compress(data, mtime=0))


def _scrub_response(response):
    """Drop Set-Cookie and mask e-mails/phones in recorded bodies so cassettes carry no
    session cookies or contact details."""
    headers = response.get("headers", {})
    for k in [k for k in headers if k.lower() == "set-cookie"]:
        del headers[k]
    body = response.get("body", {}).get("string")
    if not isinstance(body, bytes):
        return response
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return response
    response["body"]["string"] = scrub_payload(text).encode("utf-8")
    headers = response.get("headers", {})
    for k in [k for k in headers if k.lower() == "content-length"]:
        del headers[k]
    return response


def _vcr() -> vcr.VCR:
    v = vcr.VCR(
        serializer="json",
        cassette_library_dir=str(CASSETTES),
        record_mode="once" if os.environ.get("NMT_VCR_RECORD") == "1" else "none",
        match_on=["method", "scheme", "host", "path", "query"],
        filter_headers=["authorization", "cookie", "set-cookie", "user-agent"],
        filter_query_parameters=SECRET_QUERY,
        decode_compressed_response=True,
        before_record_response=_scrub_response,
    )
    v.register_persister(GzipPersister)
    return v


def cassette(name: str):
    return _vcr().use_cassette(f"{name}.json.gz", allow_playback_repeats=True)
