from __future__ import annotations

import re

import pytest

from nlqa.actions import BrowserController, ToolExecutionError
from nlqa.models import ToolCall


def ref_for(snapshot, text: str) -> str:
    line = next(line for line in snapshot.lines if text in line)
    return re.match(r"\[([^]]+)\]", line).group(1)


def test_type_select_click_hover_and_wait(page) -> None:
    page.set_content(
        """<label for="email">Email</label><input id="email"><label for="region">Region</label>
        <select id="region"><option>West</option><option>East</option></select>
        <button id="save">Save</button><div id="notice"></div>
        <script>
        document.querySelector('#save').addEventListener('click', () => {
          document.querySelector('#notice').textContent = 'Saved successfully';
        });
        </script>"""
    )
    controller = BrowserController(page)
    observation = controller.snapshot()
    controller.perform(
        ToolCall(
            name="type", args={"ref": ref_for(observation, "Email"), "text": "user@example.test"}
        ),
        observation,
        1,
    )
    observation = controller.snapshot()
    controller.perform(
        ToolCall(
            name="select_option",
            args={"ref": ref_for(observation, "Region"), "option_label": "East"},
        ),
        observation,
        2,
    )
    observation = controller.snapshot()
    controller.perform(
        ToolCall(name="hover", args={"ref": ref_for(observation, "Save")}), observation, 3
    )
    controller.perform(
        ToolCall(name="click", args={"ref": ref_for(observation, "Save")}), observation, 4
    )
    assert page.locator("#email").input_value() == "user@example.test"
    assert page.locator("#region").input_value() == "East"
    assert page.locator("#notice").inner_text() == "Saved successfully"


def test_stale_reference_returns_clear_error(page) -> None:
    page.set_content("<button>Old button</button>")
    controller = BrowserController(page)
    observation = controller.snapshot()
    reference = ref_for(observation, "Old button")
    page.set_content("<button>New button</button>")
    with pytest.raises(ToolExecutionError, match="stale or missing"):
        controller.perform(ToolCall(name="click", args={"ref": reference}), observation, 1)


def test_new_tab_and_dialog_are_handled(page, site_server: str) -> None:
    page.goto(f"{site_server}/login_basic.html")
    page.set_content(
        f"""<a target="_blank" href="{site_server}/shop_basic.html">Open shop</a>
        <button id="alert" onclick="alert('Saved')">Show alert</button>"""
    )
    controller = BrowserController(page)
    observation = controller.snapshot()
    controller.perform(
        ToolCall(name="click", args={"ref": ref_for(observation, "Show alert")}), observation, 1
    )
    assert controller.dialog_messages == ["Saved"]
    observation = controller.snapshot()
    result = controller.perform(
        ToolCall(name="click", args={"ref": ref_for(observation, "Open shop")}), observation, 2
    )
    assert result.ok is True
    assert controller.page.url.endswith("/shop_basic.html")


def test_navigation_rejects_non_http_schemes(page) -> None:
    controller = BrowserController(page)
    observation = controller.snapshot()
    with pytest.raises(ToolExecutionError, match="Only absolute http"):
        controller.perform(
            ToolCall(name="navigate", args={"url": "javascript:alert(1)"}), observation, 1
        )
