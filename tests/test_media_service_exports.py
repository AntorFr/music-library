"""Public surface of ``app.services.media_service`` after the split by responsibility."""

import pytest

from app.services import media_service

PUBLIC_NAMES = [
    "DuplicateMediaError",
    "add_tag_to_media",
    "create_media",
    "delete_media",
    "get_media",
    "get_or_create_owner_tag",
    "list_media",
    "remove_tag_from_media",
    "select_media",
    "select_media_by_query",
    "update_media",
    # private helpers other modules/tests reach through media_service
    "_apply_owner_scope",
    "_get_by_provider_source",
    "_get_or_create_tag",
    "_matching_owner_tag_ids",
    "_media_tag_index",
    "_resolve_tags",
]


@pytest.mark.parametrize("name", PUBLIC_NAMES)
def test_name_still_importable_from_media_service(name):
    assert hasattr(media_service, name)


def test_duplicate_error_is_an_exception_defined_in_media_service():
    assert issubclass(media_service.DuplicateMediaError, Exception)
