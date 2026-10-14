#!/usr/bin/env python3
"""
Unit tests for TAK output: TAKClient reconnect/backoff, send() results,
and CotMessenger only logging "Sent" when a message actually went out.
"""

import logging
import socket
import ssl
import pytest
from unittest.mock import Mock, patch

from messaging import TAKClient, TAKUDPClient, CotMessenger


class TestBackoff:
    def test_backoff_grows_then_caps(self):
        client = TAKClient("tak.example", 8089, None)
        delays = []
        for n in range(8):
            client.retry_count = n
            delays.append(client._backoff_delay())
        assert delays == [1, 2, 4, 8, 16, 32, 60.0, 60.0]

    def test_backoff_does_not_overflow_after_many_failures(self):
        # 2.0 ** 1024 raises OverflowError; this used to kill the reconnect thread.
        client = TAKClient("tak.example", 8089, None)
        for n in (1023, 1024, 5000, 10**9):
            client.retry_count = n
            assert client._backoff_delay() == client.max_backoff

    def test_connect_survives_overflow_range_retry_count(self):
        client = TAKClient("tak.example", 8089, None, max_retries=2000)
        client.retry_count = 1024
        with patch("messaging.tak_client.socket.create_connection",
                   side_effect=socket.gaierror(-2, "Name or service not known")), \
             patch("messaging.tak_client.time.sleep") as sleep:
            client.connect()
        assert client.retry_count == 2000
        assert client.sock is None
        assert all(c.args[0] == client.max_backoff for c in sleep.call_args_list)


class TestConnect:
    def test_tls_handshake_failure_does_not_publish_raw_socket(self):
        raw = Mock()
        tls_ctx = Mock()
        tls_ctx.wrap_socket.side_effect = ssl.SSLError("handshake failed")
        client = TAKClient("tak.example", 8089, tls_ctx, max_retries=1)
        published = []

        def fake_sleep(_):
            # The connect loop sleeps between attempts; send() can run then.
            published.append(client.sock)

        with patch("messaging.tak_client.socket.create_connection", return_value=raw), \
             patch("messaging.tak_client.time.sleep", side_effect=fake_sleep):
            client.connect()

        assert published == [None]
        assert client.sock is None
        raw.close.assert_called_once()

    def test_successful_tls_connect_sets_wrapped_socket(self):
        raw, wrapped = Mock(), Mock()
        tls_ctx = Mock()
        tls_ctx.wrap_socket.return_value = wrapped
        client = TAKClient("tak.example", 8089, tls_ctx)
        client.retry_count = 7
        with patch("messaging.tak_client.socket.create_connection", return_value=raw):
            client.connect()
        assert client.sock is wrapped
        assert client.retry_count == 0
        raw.close.assert_not_called()


class TestConnectLoop:
    def test_loop_keeps_running_after_unexpected_error(self):
        client = TAKClient("tak.example", 8089, None)
        calls = {"n": 0}

        def flaky_connect():
            calls["n"] += 1
            if calls["n"] == 1:
                raise OverflowError("boom")
            client.sock = Mock()

        class Stop(BaseException):
            pass

        sleeps = {"n": 0}

        def fake_sleep(_):
            sleeps["n"] += 1
            if sleeps["n"] >= 3:
                raise Stop()

        with patch.object(client, "connect", side_effect=flaky_connect), \
             patch("messaging.tak_client.time.sleep", side_effect=fake_sleep):
            with pytest.raises(Stop):
                client.run_connect_loop()

        assert calls["n"] == 2
        assert client.sock is not None


class TestSendResult:
    def test_tcp_send_without_socket_returns_false(self):
        client = TAKClient("tak.example", 8089, None)
        assert client.send(b"<event/>") is False

    def test_tcp_send_success_returns_true(self):
        client = TAKClient("tak.example", 8089, None)
        client.sock = Mock()
        assert client.send(b"<event/>") is True
        client.sock.sendall.assert_called_once_with(b"<event/>")

    def test_tcp_send_error_returns_false_and_closes(self):
        client = TAKClient("tak.example", 8089, None)
        sock = Mock()
        sock.sendall.side_effect = BrokenPipeError()
        client.sock = sock
        assert client.send(b"<event/>") is False
        assert client.sock is None
        sock.close.assert_called_once()

    def test_udp_send_result(self):
        client = TAKUDPClient("tak.example", 8087)
        client.sock.close()
        client.sock = Mock()
        assert client.send(b"<event/>") is True
        client.sock.sendto.side_effect = socket.gaierror(-2, "Name or service not known")
        assert client.send(b"<event/>") is False


class TestCotMessengerLogging:
    def _sent_logs(self, caplog):
        return [r for r in caplog.records if r.getMessage().startswith("Sent CoT message to TAK")]

    def _not_sent_logs(self, caplog):
        return [r for r in caplog.records if r.getMessage().startswith("CoT message not sent to TAK")]

    def test_tcp_drop_is_not_logged_as_sent(self, caplog):
        tak = TAKClient("tak.example", 8089, None)  # no socket: dropped
        messenger = CotMessenger(tak_client=tak)
        with caplog.at_level(logging.DEBUG, logger="messaging.cot_messenger"), \
             patch("messaging.cot_messenger.time.sleep") as sleep:
            messenger.send_cot(b"<event/>")
        assert self._sent_logs(caplog) == []
        assert len(self._not_sent_logs(caplog)) == 1
        sleep.assert_not_called()  # must not block the calling thread

    def test_tcp_success_is_logged_as_sent(self, caplog):
        tak = TAKClient("tak.example", 8089, None)
        tak.sock = Mock()
        messenger = CotMessenger(tak_client=tak)
        with caplog.at_level(logging.INFO, logger="messaging.cot_messenger"):
            messenger.send_cot(b"<event/>")
        assert len(self._sent_logs(caplog)) == 1
        assert self._not_sent_logs(caplog) == []
        tak.sock.sendall.assert_called_once_with(b"<event/>")

    def test_udp_failure_is_not_logged_as_sent(self, caplog):
        udp = TAKUDPClient("tak.example", 8087)
        udp.sock.close()
        udp.sock = Mock()
        udp.sock.sendto.side_effect = OSError("Network is unreachable")
        messenger = CotMessenger(tak_udp_client=udp)
        with caplog.at_level(logging.DEBUG, logger="messaging.cot_messenger"), \
             patch("messaging.cot_messenger.time.sleep") as sleep:
            messenger.send_cot(b"<event/>")
        assert self._sent_logs(caplog) == []
        assert len(self._not_sent_logs(caplog)) == 1
        assert udp.sock.sendto.call_count == 1
        sleep.assert_not_called()
