import pytest

from coach import license as lic

DAY = 24 * 3600
OURS = {"store_id": 1, "product_id": 2}


@pytest.fixture
def product(monkeypatch):
    monkeypatch.setattr(lic, "STORE_ID", 1)
    monkeypatch.setattr(lic, "PRODUCT_ID", 2)


class Server:
    def __init__(self, answer=None, down=False):
        self.answer, self.down, self.calls = answer or {}, down, []

    def __call__(self, url, fields):
        self.calls.append((url.rsplit("/", 1)[1], fields))
        if self.down:
            raise OSError("offline")
        return self.answer


def test_licensing_is_off_until_the_store_is_set_up(tmp_path):
    assert not lic.required()
    assert lic.License(tmp_path, post=Server(down=True)).check().ok


def test_no_key_asks_for_one(tmp_path, product):
    result = lic.License(tmp_path, post=Server()).check()
    assert not result.ok and "licence key" in result.message


def test_activate_saves_the_key_and_instance(tmp_path, product):
    server = Server({"activated": True, "instance": {"id": "inst-1"}, "meta": OURS, "license_key": {"status": "active"}})
    key = lic.License(tmp_path, post=server, clock=lambda: 1000.0)
    assert key.activate("  ABC-123 ").ok
    assert server.calls[0][0] == "activate" and server.calls[0][1]["license_key"] == "ABC-123"
    assert key.check().ok and len(server.calls) == 1  # checked less than a day ago


def test_a_key_from_another_product_is_refused(tmp_path, product):
    server = Server({"activated": True, "instance": {"id": "x"}, "meta": {"store_id": 9, "product_id": 2}})
    key = lic.License(tmp_path, post=server)
    assert not key.activate("ABC").ok and not (tmp_path / lic.FILE_NAME).exists()


def test_activation_limit_and_offline_messages(tmp_path, product):
    limit = Server({"activated": False, "error": "This license key has reached the activation limit."})
    assert "another PC" in lic.License(tmp_path, post=limit).activate("ABC").message
    assert "internet" in lic.License(tmp_path, post=Server(down=True)).activate("ABC").message


def activated(tmp_path, now):
    server = Server({"activated": True, "instance": {"id": "inst-1"}, "meta": OURS})
    lic.License(tmp_path, post=server, clock=lambda: now).activate("ABC")


def test_daily_check_validates_with_the_instance(tmp_path, product):
    activated(tmp_path, 0)
    server = Server({"valid": True, "meta": OURS, "license_key": {"status": "active"}})
    key = lic.License(tmp_path, post=server, clock=lambda: 2 * DAY)
    assert key.check().ok
    assert server.calls == [("validate", {"license_key": "ABC", "instance_id": "inst-1"})]


def test_offline_works_for_the_grace_days_then_asks_to_connect(tmp_path, product):
    activated(tmp_path, 0)
    assert lic.License(tmp_path, post=Server(down=True), clock=lambda: 6 * DAY).check().ok
    late = lic.License(tmp_path, post=Server(down=True), clock=lambda: 8 * DAY).check()
    assert not late.ok and "internet" in late.message


def test_an_ended_subscription_asks_to_renew(tmp_path, product):
    activated(tmp_path, 0)
    server = Server({"valid": False, "meta": OURS, "license_key": {"status": "expired"}})
    result = lic.License(tmp_path, post=server, clock=lambda: 2 * DAY).check()
    assert not result.ok and "Renew" in result.message
