"""Tests for daemon discovery and command line construction."""

from dataclasses import replace

from phoenix_gui.core.daemon import daemon_arguments, discover_daemon


def test_daemon_arguments_include_core_flags(settings, project, tmp_path):
    settings.daemon_datadir = str(tmp_path / "data")
    settings.daemon_extra_args = "-listen=0 -maxconnections=20"
    args = daemon_arguments(settings, project)
    assert f"-datadir={tmp_path / 'data'}" in args
    assert f"-rpcport={project.daemon_port}" in args
    assert "-server=1" in args
    assert "-listen=0" in args
    assert "-maxconnections=20" in args


def test_daemon_arguments_add_testnet(settings, project):
    args = daemon_arguments(settings, replace(project, testnet=True))
    assert "-testnet" in args
    assert "-testnet" not in daemon_arguments(settings, project)


def test_discover_daemon_prefers_configured_binary(project, tmp_path):
    binary = tmp_path / "novacoind"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    assert discover_daemon(project, str(binary)) == binary.resolve()
