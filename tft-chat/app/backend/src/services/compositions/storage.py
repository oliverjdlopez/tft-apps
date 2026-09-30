"""Select storage only for the private compositions development workspace."""

from common.paths import find_repo_root
from core.config import load_config
from db.session import open_db as open_application_db
from .utils import local_composition_engine


def offline_enabled():
    """Read the explicit development switch without changing application DB routing."""
    return load_config().chat.composition_offline


def local_store_path():
    """Locate disposable local experiment history outside the checked-in source."""
    return find_repo_root() / ".runtime" / "compositions" / "experiments.db"


def open_db(*, purpose="app"):
    """Open private local history in offline mode or retain the typed RDS target.

    Args:
        purpose: Existing worker target; isolated test targets always keep RDS routing.
    """
    if purpose != "app" or not offline_enabled():
        return open_application_db(purpose=purpose)
    from sqlalchemy.orm import Session

    return Session(local_composition_engine(local_store_path()), expire_on_commit=False)
