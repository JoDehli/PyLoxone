import os

import pytest
from dotenv import load_dotenv


@pytest.fixture
def load_credentials_from_env():
    load_dotenv()
    return {
        "username": os.getenv("LOXONE_USERNAME"),
        "password": os.getenv("LOXONE_PASSWORD"),
        "port": os.getenv("LOXONE_PORT"),
    }


load_credentials_from_env()


def test_alone(load_credentials_from_env):
    pass
    # print("Username", username)
    # assert username is not None
    # assert password is not None
    # assert host is not None
