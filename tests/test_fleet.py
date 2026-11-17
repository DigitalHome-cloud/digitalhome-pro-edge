# SPDX-License-Identifier: GPL-3.0-or-later
"""What a pro edge tells the Portal's Fleet: its kind and the homeIds of
its workspaces' homes, per connection, nothing else. Invented data."""

from __future__ import annotations

from digitalhome_pro_edge import fleet

WS = [
    {"workspace": "ws-a", "home": "XX-1", "instance": "prod"},
    {"workspace": "ws-b", "home": "XX-1", "instance": "prod"},
    {"workspace": "ws-c", "home": "XX-2", "instance": "prod"},
    {"workspace": "ws-d", "home": "XX-3", "instance": "stage"},
    {"workspace": "ws-e", "home": "XX-9", "instance": "prod"},   # the cloud does not list it
    {"workspace": "ws-f", "home": "XX-4", "instance": ""},       # not attached
]
LISTS = {
    "prod": [{"smartHomeId": "XX-1", "homeId": "h-aaaaaaaaaa"}, {"smartHomeId": "XX-2", "homeId": "h-bbbbbbbbbb"},
             {"smartHomeId": "XX-5", "homeId": "h-cccccccccc"}],
    "stage": [{"smartHomeId": "XX-3", "homeId": "h-dddddddddd"}],
    "test": [],
}


def test_each_connection_gets_the_homeids_of_its_own_workspaces_once():
    got = fleet.homes_by_connection(WS, lambda n: LISTS[n], ["prod", "stage", "test"])
    assert got == {"prod": ["h-aaaaaaaaaa", "h-bbbbbbbbbb"], "stage": ["h-dddddddddd"], "test": []}


class FakeCloud:
    def __init__(self, fail=()):
        self.sent, self.fail = [], set(fail)

    def linked_profiles(self):
        return ["prod", "stage"]

    def telemetry(self, kind, extra, profile=None):
        if profile in self.fail:
            raise RuntimeError("not reachable")
        self.sent.append((profile, kind, extra))


class FakeDesigns:
    def workspaces(self):
        return WS


class FakeHomes:
    @staticmethod
    def cloud_homes(refresh=False, profile=None):
        return {"homes": LISTS[profile]}


def test_the_report_says_pro_and_only_homeids_and_a_failure_waits_for_the_next():
    c = FakeCloud(fail={"stage"})
    res = fleet.report(FakeDesigns(), c, FakeHomes)
    assert c.sent == [("prod", "delta", {"edge_kind": "pro", "homes": ["h-aaaaaaaaaa", "h-bbbbbbbbbb"]})]
    assert res["prod"] == {"sent": 2} and "not reachable" in res["stage"]["error"]
    flat = repr(c.sent)
    assert "XX-" not in flat and "ws-" not in flat          # no SmartHome ID, no workspace
