"""P11: functional testing screen."""

from __future__ import annotations

import asyncio

from review_ticket.storage import read_json
from review_ticket.tui import ReviewTicketApp
from review_ticket.tui.functional_testing_screen import FunctionalTestingScreen
from tests.support import ISSUE, SHA1, make_app
from tests.test_acceptance import _commit, _run, _seed_pr
from tests.test_status_projection import REF_A, _store

_RUN_TEST_SIZE = (110, 56)


def test_save_pass_and_comment(tmp_path):
    app, _runner, _world = make_app(tmp_path)
    _seed_pr(tmp_path, SHA1)
    _run(app, [ISSUE, "test", "prepare"])
    store = _store(tmp_path)
    tui = ReviewTicketApp(store=store, issue=ISSUE)

    async def _run_ui() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            tui.pop_screen()
            tui.push_screen(
                FunctionalTestingScreen(
                    store,
                    ISSUE,
                    app,
                    ref=REF_A,
                    owner="acme",
                    repo="widgets",
                    number=87,
                    sha=SHA1,
                )
            )
            await pilot.pause()
            await pilot.click("#btn-disp-comment")
            await pilot.click("#btn-save")
            await pilot.pause()
            payload = read_json(_commit(tmp_path, SHA1) / "testing" / "test-results.json")
            assert payload["result"] == "pass"
            assert payload["disposition"] == "COMMENT"

    asyncio.run(_run_ui())
