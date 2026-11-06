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


def test_custom_pointer_control_can_open_its_input(page) -> None:
    page.set_content(
        """<div role="tabpanel"><div id="destination"
        style="cursor:pointer;width:260px;height:60px"><span>Destination</span></div></div>
        <input id="city" hidden>
        <script>document.querySelector('#destination').addEventListener('click', () => {
          document.querySelector('#city').hidden = false;
        });</script>"""
    )
    controller = BrowserController(page)
    observation = controller.snapshot()
    line = next(line for line in observation.lines if "Destination" in line)
    assert "custom control" in line

    controller.perform(
        ToolCall(name="click", args={"ref": ref_for(observation, "Destination")}),
        observation,
        1,
    )

    assert page.locator("#city").is_visible()


def test_overlay_dismissal_waits_for_close_transition(page) -> None:
    page.set_content(
        """<button id="underlying" onclick="this.dataset.clicked = 'yes'">Stays</button>
        <div style="position:fixed;inset:0;z-index:9999">
          <button onclick="setTimeout(() => this.parentElement.remove(), 100)">
            I Understand and Continue
          </button>
        </div>"""
    )
    controller = BrowserController(page)
    observation = controller.snapshot()
    line = next(line for line in observation.lines if "I Understand and Continue" in line)
    assert "top-overlay" in line

    controller.perform(
        ToolCall(name="click", args={"ref": ref_for(observation, "I Understand")}),
        observation,
        1,
    )

    fresh_observation = controller.snapshot()
    controller.perform(
        ToolCall(name="click", args={"ref": ref_for(fresh_observation, "Stays")}),
        fresh_observation,
        2,
    )
    assert page.locator("#underlying").get_attribute("data-clicked") == "yes"


def test_newly_appeared_overlay_is_dismissed_after_blocked_click(page) -> None:
    page.set_content(
        """<button id="stays">Stays</button>
        <script>setTimeout(() => {
          const overlay = document.createElement('div');
          overlay.style.cssText = 'position:fixed;inset:0;z-index:9999';
          const button = document.createElement('button');
          button.textContent = 'I Understand and Continue';
          button.onclick = () => overlay.remove();
          overlay.append(button);
          document.body.append(overlay);
        }, 75);</script>"""
    )
    controller = BrowserController(page, timeout_ms=500)
    observation = controller.snapshot()
    stays_ref = ref_for(observation, "Stays")
    page.wait_for_timeout(125)

    result = controller.perform(ToolCall(name="click", args={"ref": stays_ref}), observation, 1)

    assert result.ok is False
    assert "notice was dismissed" in result.detail
    fresh_observation = controller.snapshot()
    controller.perform(
        ToolCall(name="click", args={"ref": ref_for(fresh_observation, "Stays")}),
        fresh_observation,
        2,
    )


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
