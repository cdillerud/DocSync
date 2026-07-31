import asyncio

from services import email_polling_service as service


def test_overlapping_poll_returns_immediately(
    monkeypatch,
):
    async def scenario():
        monkeypatch.setattr(
            service,
            "_email_polling_lock",
            asyncio.Lock(),
        )

        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def fake_unlocked_poll():
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return {
                "status": "completed",
            }

        monkeypatch.setattr(
            service,
            "_poll_mailbox_for_attachments_unlocked",
            fake_unlocked_poll,
        )

        first = asyncio.create_task(
            service.poll_mailbox_for_attachments()
        )

        await asyncio.wait_for(
            started.wait(),
            timeout=1,
        )

        second = await asyncio.wait_for(
            service.poll_mailbox_for_attachments(),
            timeout=1,
        )

        assert second == {
            "skipped": True,
            "status": "already_running",
            "reason": (
                "An AP mailbox poll is already in progress"
            ),
            "mailbox": service.EMAIL_POLLING_USER,
        }

        assert calls == 1

        release.set()

        first_result = await asyncio.wait_for(
            first,
            timeout=1,
        )

        assert first_result == {
            "status": "completed",
        }

        third = await asyncio.wait_for(
            service.poll_mailbox_for_attachments(),
            timeout=1,
        )

        assert third == {
            "status": "completed",
        }

        assert calls == 2

    asyncio.run(scenario())
