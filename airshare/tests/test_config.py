"""Tests for airshare.config defaults."""
import importlib
import os

import pytest


@pytest.fixture
def fresh_config(monkeypatch):
    monkeypatch.delenv("AIRSHARE_PORT", raising=False)
    from airshare import config

    importlib.reload(config)
    yield config
    importlib.reload(config)


def test_default_port_avoids_airplay(fresh_config):
    assert fresh_config.RECEIVER_PORT == 5077
