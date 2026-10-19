import asyncio

from review_ticket.tui import ReviewTicketApp


def test_review_ticket_app_run_test_smoke():
    app = ReviewTicketApp()

    async def _boot() -> None:
        async with app.run_test() as pilot:
            assert pilot.app is app

    asyncio.run(_boot())
