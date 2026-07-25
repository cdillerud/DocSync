from __future__ import annotations


def test_database_resources_are_adopted_by_platform_manager() -> None:
    import database

    assert database.mongo_manager.is_connected is True
    assert database.mongo_manager.owns_client is False
    assert database.mongo_manager.client is database.client
    assert database.mongo_manager.database is database.db


def test_platform_manager_does_not_create_a_second_client() -> None:
    import database

    resources = database.mongo_manager.adopt(
        database.client,
        database.db,
    )

    assert resources.client is database.client
    assert resources.database is database.db
    assert database.db.client is database.client
