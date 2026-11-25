"""Playwright tests of the operator console (REQ-011) against a live uvicorn server."""
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.req("REQ-011")


def load(page: Page, sample: str):
    page.get_by_label("Sample ID").fill(sample)
    page.get_by_role("button", name="Load sample").click()


def test_console_shows_idle_state(page: Page, server):
    page.goto(server)
    expect(page.get_by_test_id("state")).to_have_text("IDLE")
    expect(page.get_by_test_id("samples")).to_have_text("none")


def test_load_sample_and_run(page: Page, server):
    page.goto(server)
    load(page, "S001")
    expect(page.get_by_test_id("samples")).to_have_text("S001")
    page.get_by_role("button", name="Start run").click()
    expect(page.get_by_test_id("state")).to_have_text("RUNNING")
    page.get_by_role("button", name="Stop run").click()
    expect(page.get_by_test_id("state")).to_have_text("IDLE")


def test_start_without_sample_shows_message(page: Page, server):
    page.goto(server)
    page.get_by_role("button", name="Start run").click()
    expect(page.get_by_role("alert")).to_have_text("no samples loaded")


def test_fault_shows_error_and_recovers(page: Page, server):
    page.goto(server)
    page.get_by_label("Fault").select_option("overtemp")
    page.get_by_role("button", name="Inject fault").click()
    page.get_by_role("button", name="Read sensors").click()
    expect(page.get_by_test_id("error")).to_have_text("E101 Over-temperature")
    expect(page.get_by_test_id("state")).to_have_class("ERROR")
    page.get_by_role("button", name="Clear faults").click()
    page.get_by_role("button", name="Reset").click()
    expect(page.get_by_test_id("state")).to_have_text("IDLE")


def test_sensor_reading_displayed(page: Page, server):
    page.goto(server)
    page.get_by_role("button", name="Read sensors").click()
    expect(page.get_by_test_id("temp")).to_have_text(__import__("re").compile(r"^3[67]\.\d+$"))
